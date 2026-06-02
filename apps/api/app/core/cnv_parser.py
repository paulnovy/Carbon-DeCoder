from pathlib import Path
import math


def _to_float(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        raw = str(v).strip()
        if raw in {"", ".", "NA", "NaN"}:
            return None
        return float(raw)
    except ValueError:
        return None


def _to_int(v: str | None) -> int | None:
    if v is None:
        return None
    try:
        raw = str(v).strip().replace(",", "")
        if raw in {"", ".", "NA"}:
            return None
        return int(float(raw))
    except ValueError:
        return None


def _copy_number_from_log2(log2_ratio: float) -> float:
    return round(2 * math.pow(2.0, log2_ratio), 4)


def _cnv_type_from_copy_number(copy_number: float, call: str = "") -> str:
    normalized = call.strip().lower()
    if normalized in {"del", "deletion", "loss", "-", "0", "1"}:
        return "loss"
    if normalized in {"dup", "duplication", "gain", "+", "3", "4"}:
        return "gain"
    return "gain" if copy_number > 2.15 else "loss" if copy_number < 1.85 else "neutral"


def _split_row(raw: str) -> list[str]:
    if "\t" in raw:
        return [x.strip() for x in raw.split("\t")]
    if "," in raw:
        return [x.strip() for x in raw.split(",")]
    return raw.split()


def _norm_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _header_index(header_tokens: list[str]) -> dict[str, int]:
    return {_norm_header(name): idx for idx, name in enumerate(header_tokens)}


def _value(tokens: list[str], idx: dict[str, int], *names: str) -> str | None:
    for name in names:
        key = _norm_header(name)
        if key in idx and idx[key] < len(tokens):
            return tokens[idx[key]]
    return None


def _parse_cnvnator_line(raw: str) -> dict | None:
    # Typical CNVnator line starts with deletion/duplication and coordinate chr:start-end
    tokens = raw.replace(",", " ").split()
    if len(tokens) < 2:
        return None
    event = tokens[0].strip().lower()
    if event not in {"deletion", "duplication", "del", "dup"}:
        return None

    coord = tokens[1].strip()
    if ":" not in coord or "-" not in coord:
        return None
    chrom, rng = coord.split(":", 1)
    start_s, end_s = rng.split("-", 1)
    start = _to_int(start_s)
    end = _to_int(end_s)
    if start is None or end is None:
        return None

    rd = _to_float(tokens[3] if len(tokens) > 3 else None)
    if rd is not None:
        copy_number = round(rd * 2.0, 4)
    else:
        copy_number = 1.0 if event in {"deletion", "del"} else 3.0

    return {
        "chrom": chrom,
        "start": start,
        "end": end,
        "copy_number": copy_number,
        "cnv_type": "loss" if event in {"deletion", "del"} else "gain",
        "method": "CNVnator",
        "trust_score": None,
    }


def _parse_generic(tokens: list[str], idx: dict[str, int]) -> dict | None:
    chrom = _value(tokens, idx, "chrom", "chr", "contig", "chromosome")
    start = _to_int(_value(tokens, idx, "start", "loc.start", "begin"))
    end = _to_int(_value(tokens, idx, "end", "loc.end", "stop"))
    if not chrom or start is None or end is None:
        return None

    copy_number = _to_float(_value(tokens, idx, "copy_number", "copy.number", "cn", "copy", "cnv_copy_number"))
    log2_ratio = _to_float(
        _value(tokens, idx, "mean_log2_copy_ratio", "log2_copy_ratio", "log2", "seg.mean", "seg_mean")
    )
    ratio = _to_float(_value(tokens, idx, "ratio", "median_ratio", "normalized_coverage"))

    if copy_number is None and log2_ratio is not None:
        copy_number = _copy_number_from_log2(log2_ratio)
    if copy_number is None and ratio is not None:
        copy_number = round(ratio * 2.0, 4)
    if copy_number is None:
        return None

    call = _value(tokens, idx, "cnv_type", "call", "type", "status", "event") or ""
    cnv_type = _cnv_type_from_copy_number(copy_number, call)
    method = _value(tokens, idx, "method", "caller", "source")
    trust_score = _to_float(_value(tokens, idx, "trust_score", "quality", "qual", "score"))

    if method is None:
        headers = set(idx)
        if "contig" in headers and "call" in headers:
            method = "gCNV"
        elif "mean_log2_copy_ratio" in headers or "num_points_copy_ratio" in headers:
            method = "GATK-ModelSegments"
        elif "log2" in headers and "probes" in headers:
            method = "CNVkit"
        elif "ratio" in headers and ("copy_number" in headers or "status" in headers):
            method = "Control-FREEC"
        else:
            method = "generic"

    return {
        "chrom": chrom,
        "start": start,
        "end": end,
        "copy_number": copy_number,
        "cnv_type": cnv_type,
        "method": method,
        "trust_score": trust_score,
    }


def parse_cnv_segments_tsv(path: Path) -> list[dict]:
    """Parse CNV segments from real-world TSV/CSV/whitespace tables.

    Supported inputs:
    - generic columns: chrom,start,end,copy_number,cnv_type,method[,trust_score]
    - GATK ModelSegments / gCNV-like tables with contig/start/end/log2/call fields
    - CNVkit .cns-like tables (chromosome,start,end,gene,log2,depth,probes,...)
    - Control-FREEC ratio tables (chromosome/start/end/ratio/copy number/status)
    - CNVnator event lines: deletion/duplication chr:start-end ...
    """
    if not path.exists():
        return []

    lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith("#")]
    if not lines:
        return []

    header_tokens = _split_row(lines[0])
    header_norm = [_norm_header(h) for h in header_tokens]
    header_set = set(header_norm)
    known_header_markers = {
        "chrom",
        "chr",
        "contig",
        "chromosome",
        "start",
        "end",
        "loc.start",
        "loc.end",
        "copy_number",
        "copy.number",
        "cn",
        "cnv_type",
        "mean_log2_copy_ratio",
        "log2_copy_ratio",
        "seg.mean",
        "log2",
        "ratio",
        "median_ratio",
    }
    has_header = bool(header_set & known_header_markers) and not (_to_int(header_tokens[1] if len(header_tokens) > 1 else None))
    rows = lines[1:] if has_header else lines
    idx = _header_index(header_tokens) if has_header else {}

    out: list[dict] = []
    for raw in rows:
        tokens = _split_row(raw)
        try:
            parsed: dict | None = None
            if has_header:
                parsed = _parse_generic(tokens, idx)
            if parsed is None:
                parsed_cnvnator = _parse_cnvnator_line(raw)
                if parsed_cnvnator is not None:
                    parsed = parsed_cnvnator
            if parsed is None:
                if len(tokens) < 6:
                    continue
                chrom = tokens[0].strip()
                start = int(tokens[1])
                end = int(tokens[2])
                copy_number = float(tokens[3])
                cnv_type = tokens[4].strip()
                method = tokens[5].strip()
                trust_score = float(tokens[6]) if len(tokens) > 6 else None
                parsed = {
                    "chrom": chrom,
                    "start": start,
                    "end": end,
                    "copy_number": copy_number,
                    "cnv_type": cnv_type,
                    "method": method,
                    "trust_score": trust_score,
                }
        except (ValueError, IndexError):
            continue

        if parsed["end"] <= parsed["start"]:
            continue
        out.append(parsed)

    return out


def _parse_vcf_info(info: str) -> dict[str, str]:
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


def _infer_cnv_vcf_caller(headers: list[str]) -> str:
    text = "\n".join(headers).lower()
    if "gcnv" in text or "gatk" in text:
        return "GATK-gCNV"
    if "cnvnator" in text:
        return "CNVnator"
    if "canvas" in text:
        return "Canvas"
    if "manta" in text:
        return "Manta"
    if "delly" in text:
        return "Delly"
    return "VCF-CNV"


def _parse_vcf_format(fmt: str, samples: list[str]) -> dict[str, list[str]]:
    keys = [k.strip() for k in (fmt or "").split(":") if k.strip()]
    out: dict[str, list[str]] = {k: [] for k in keys}
    for sample in samples:
        values = sample.split(":")
        for idx, key in enumerate(keys):
            if idx < len(values) and values[idx] not in {"", "."}:
                out.setdefault(key, []).append(values[idx])
    return out


def _first_number_from_values(values: list[str]) -> float | None:
    for raw in values:
        for part in str(raw).replace("|", ",").split(","):
            parsed = _to_float(part)
            if parsed is not None:
                return parsed
    return None


def _vcf_trust_score(qual: str, filt: str, info: dict[str, str], fmt_values: dict[str, list[str]]) -> float | None:
    score = 50.0
    q = _to_float(qual)
    if q is not None:
        score += min(22.0, q / 5.0)
    if filt in {"PASS", "."}:
        score += 12.0
    elif filt:
        score -= 18.0

    for key in ("CNQ", "QS", "QSS", "GQ"):
        v = _to_float(info.get(key))
        if v is None:
            v = _first_number_from_values(fmt_values.get(key, []))
        if v is not None:
            score += min(16.0, v / 6.0)
            break

    if "IMPRECISE" in info:
        score -= 5.0
    if "PRECISE" in info:
        score += 4.0
    if "LOWQUAL" in filt.upper():
        score -= 15.0
    return round(max(0.0, min(100.0, score)), 2)


def parse_cnv_vcf(path: Path) -> list[dict]:
    """Parse CNV-like records from VCF into import-ready CNV segments.

    Handles symbolic `<DEL>`, `<DUP>`, `<CNV>` alleles and common INFO/FORMAT
    fields used by gCNV/GATK-style and VCF-emitting CNV callers: `END`, `SVLEN`,
    `SVTYPE`, `CN`, `MCN`, `CNQ`, `QS`, `GQ`.
    """
    if not path.exists():
        return []

    out: list[dict] = []
    headers: list[str] = []

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line:
                continue
            if line.startswith("##"):
                headers.append(line.strip())
                continue
            if line.startswith("#"):
                continue

            parts = line.rstrip("\n").split("\t")
            if len(parts) < 8:
                continue

            chrom = parts[0].strip()
            start = _to_int(parts[1])
            if start is None:
                continue
            alt = parts[4].split(",")[0].strip()
            qual = parts[5].strip() if len(parts) > 5 else "."
            filt = parts[6].strip() if len(parts) > 6 else "."
            info = _parse_vcf_info(parts[7])
            fmt_values = _parse_vcf_format(parts[8], parts[9:]) if len(parts) > 9 else {}

            svtype = (info.get("SVTYPE") or "").upper()
            if not svtype and alt.startswith("<") and alt.endswith(">"):
                svtype = alt[1:-1].upper()
            if svtype not in {"DEL", "DUP", "CNV", "MCNV"}:
                continue

            end = _to_int(info.get("END"))
            if end is None:
                svlen = _to_int(info.get("SVLEN"))
                if svlen is not None and svlen != 0:
                    end = start + abs(svlen)
            if end is None or end <= start:
                continue

            cn = _to_float(info.get("CN"))
            if cn is None:
                cn = _to_float(info.get("MCN"))
            if cn is None:
                cn = _first_number_from_values(fmt_values.get("CN", []) + fmt_values.get("MCN", []))
            if cn is None:
                cn = 1.0 if svtype == "DEL" else 3.0 if svtype == "DUP" else 2.0

            call = info.get("CNVTYPE") or info.get("CALL") or svtype
            cnv_type = _cnv_type_from_copy_number(cn, call)
            method = info.get("CALLER") or info.get("SOURCE") or _infer_cnv_vcf_caller(headers)
            trust_score = _vcf_trust_score(qual, filt, info, fmt_values)

            out.append(
                {
                    "chrom": chrom,
                    "start": start,
                    "end": end,
                    "copy_number": cn,
                    "cnv_type": cnv_type,
                    "method": method,
                    "trust_score": trust_score,
                }
            )

    return out
