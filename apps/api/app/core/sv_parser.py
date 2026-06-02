from pathlib import Path
import re


def _parse_info(info: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in (info or "").split(";"):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            k, v = token.split("=", 1)
            out[k] = v
        else:
            out[token] = "true"
    return out


def _infer_caller_from_header(headers: list[str]) -> str | None:
    h = "\n".join(headers).lower()
    if "source=delly" in h or "delly" in h:
        return "Delly"
    if "source=manta" in h or "manta" in h:
        return "Manta"
    if "source=lumpy" in h or "lumpy" in h:
        return "Lumpy"
    if "gridss" in h:
        return "GRIDSS"
    if "svaba" in h:
        return "SvABA"
    return None


def _parse_breakend_alt(alt: str) -> tuple[str | None, int | None]:
    # BND ALT examples: N]chr2:321682], ]chr2:321682]N, N[chr2:321682[
    m = re.search(r"[\[\]]([^\[\]:]+):(\d+)[\[\]]", alt)
    if not m:
        return None, None
    chrom = m.group(1)
    try:
        pos = int(m.group(2))
    except ValueError:
        return chrom, None
    return chrom, pos


def _first_int(value: str | None) -> int | None:
    if value is None:
        return None
    for part in str(value).replace("|", ",").split(","):
        try:
            return int(float(part))
        except ValueError:
            continue
    return None


def _alt_depth(value: str | None) -> int | None:
    """Return ALT-side depth from VCF sample fields like 12,5 or 12|5."""
    if value is None:
        return None
    parts = str(value).replace("|", ",").split(",")
    if len(parts) >= 2:
        try:
            return int(float(parts[-1]))
        except ValueError:
            return None
    return _first_int(value)


def _parse_format_samples(fmt: str, sample_values: list[str]) -> dict[str, list[str]]:
    keys = [k.strip() for k in (fmt or "").split(":") if k.strip()]
    out: dict[str, list[str]] = {k: [] for k in keys}
    if not keys:
        return out
    for sample in sample_values:
        vals = sample.split(":")
        for idx, key in enumerate(keys):
            if idx < len(vals) and vals[idx] not in {"", "."}:
                out.setdefault(key, []).append(vals[idx])
    return out


def _sum_alt_depth(format_values: dict[str, list[str]], keys: tuple[str, ...]) -> int:
    total = 0
    for key in keys:
        for value in format_values.get(key, []):
            depth = _alt_depth(value)
            if depth is not None and depth > 0:
                total += depth
    return total


def _evidence_from_info_and_format(info: dict[str, str], format_values: dict[str, list[str]]) -> list[str]:
    evidence: set[str] = {x for x in str(info.get("EVIDENCE", "")).split(",") if x}

    # INFO-level evidence used by Delly/Lumpy/SURVIVOR-style records.
    for key, label in {
        "PE": "PE",
        "SR": "SR",
        "SU": "SU",
        "CT": "CT",
        "PRECISE": "PRECISE",
        "IMPRECISE": "IMPRECISE",
    }.items():
        if key in info:
            evidence.add(label)

    # Manta FORMAT: PR/SR = ref,alt paired-read/split-read support.
    if _sum_alt_depth(format_values, ("PR",)) > 0:
        evidence.add("PE")
    if _sum_alt_depth(format_values, ("SR",)) > 0:
        evidence.add("SR")

    # Delly FORMAT: DV/RV are variant paired-end/split-read counts.
    if _sum_alt_depth(format_values, ("DV", "PE")) > 0:
        evidence.add("PE")
    if _sum_alt_depth(format_values, ("RV",)) > 0:
        evidence.add("SR")

    # GRIDSS/SvABA often expose assembly/split/pair support with these names.
    if _sum_alt_depth(format_values, ("AS", "RAS", "IC", "RP")) > 0:
        evidence.add("ASSEMBLY")
    if _sum_alt_depth(format_values, ("VF", "AD")) > 0:
        evidence.add("ALT_DEPTH")

    return sorted(evidence)


def _infer_trust_score(qual: str, filt: str, evidence: list[str], info: dict[str, str], format_values: dict[str, list[str]]) -> float:
    score = 52.0
    try:
        q = float(qual) if qual not in {"", "."} else None
    except ValueError:
        q = None

    if filt in {"PASS", "."}:
        score += 12.0
    elif filt:
        score -= 18.0

    if q is not None:
        score += min(18.0, q / 5.0)

    ev = set(evidence)
    if "PE" in ev:
        score += 7.0
    if "SR" in ev:
        score += 9.0
    if "ASSEMBLY" in ev:
        score += 8.0
    if "PRECISE" in ev:
        score += 5.0
    if "IMPRECISE" in ev:
        score -= 5.0

    alt_support = _sum_alt_depth(format_values, ("PR", "SR", "DV", "RV", "AD", "VF", "AS", "RAS", "RP"))
    if alt_support >= 20:
        score += 8.0
    elif alt_support >= 8:
        score += 4.0
    elif alt_support > 0:
        score += 2.0

    if "LOWQUAL" in filt.upper() or "LowQual" in filt:
        score -= 15.0

    return round(max(0.0, min(100.0, score)), 2)


def _caller_from_record(info: dict[str, str], detected_caller: str | None) -> list[str]:
    callers = [x for x in str(info.get("CALLERS", "")).split(",") if x]
    for key in ("SVMETHOD", "SOURCE"):
        value = info.get(key)
        if value and value not in {".", "true"}:
            callers.append(value.split(":" )[0])
    if not callers and detected_caller:
        callers = [detected_caller]
    # Preserve order while de-duplicating.
    return list(dict.fromkeys(callers))


def parse_sv_vcf(path: Path) -> list[dict]:
    """Parse SV records from real-world VCFs into import-ready dicts.

    Supported features include symbolic SV alleles, breakend ALT parsing,
    Delly CHR2 translocations, Manta PR/SR FORMAT support, Delly DV/RV FORMAT
    support, basic GRIDSS/SvABA assembly evidence, caller detection from headers,
    and a conservative trust-score heuristic from FILTER/QUAL/evidence.
    """
    if not path.exists():
        return []

    items: list[dict] = []
    headers: list[str] = []
    detected_caller: str | None = None

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line:
                continue
            if line.startswith("##"):
                headers.append(line.strip())
                detected_caller = _infer_caller_from_header(headers) or detected_caller
                continue
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 8:
                continue

            chrom = parts[0].strip()
            try:
                pos = int(parts[1])
            except ValueError:
                continue

            ref = parts[3].strip()
            alt = parts[4].split(",")[0].strip()
            qual = parts[5].strip() if len(parts) > 5 else "."
            filt = parts[6].strip() if len(parts) > 6 else "."
            info = _parse_info(parts[7])
            format_values = _parse_format_samples(parts[8], parts[9:]) if len(parts) > 9 else {}

            sv_type = info.get("SVTYPE")
            if not sv_type and alt.startswith("<") and alt.endswith(">"):
                sv_type = alt[1:-1]
            if not sv_type and ("[" in alt or "]" in alt):
                sv_type = "BND"
            sv_type = (sv_type or "UNK").upper()

            end = _first_int(info.get("END")) or pos
            if sv_type in {"BND", "TRA"}:
                bnd_chrom, bnd_pos = _parse_breakend_alt(alt)
                if bnd_pos is not None:
                    end = bnd_pos
                elif _first_int(info.get("POS2")) is not None:
                    end = _first_int(info.get("POS2")) or end
                # Delly represents translocations with CHR2 and no same-contig END.
                if end <= pos and "CHR2" in info and str(info["CHR2"]).strip() != chrom:
                    end = pos + 1

            if end <= pos and "SVLEN" in info:
                svlen = _first_int(info.get("SVLEN"))
                if svlen is not None and svlen != 0:
                    end = pos + abs(svlen)

            if end <= pos:
                end = pos + max(len(ref), 1)

            size_bp = max(1, abs(end - pos))
            evidence = _evidence_from_info_and_format(info, format_values)
            callers = _caller_from_record(info, detected_caller)
            trust_score = _infer_trust_score(qual, filt, evidence, info, format_values)

            items.append(
                {
                    "chrom": chrom,
                    "start": pos,
                    "end": end,
                    "sv_type": sv_type,
                    "size_bp": size_bp,
                    "evidence_types": evidence,
                    "caller_list": callers,
                    "trust_score": trust_score,
                }
            )

    return items
