from pathlib import Path


def _infer_variant_type(ref: str, alt: str) -> str:
    if len(ref) == 1 and len(alt) == 1:
        return "SNV"
    if len(ref) > len(alt):
        return "DEL"
    if len(ref) < len(alt):
        return "INS"
    return "MNV"


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


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        raw = str(value).strip()
        if raw in {"", ".", "NA", "NaN"}:
            return None
        return float(raw)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    parsed = _to_float(value)
    return int(parsed) if parsed is not None else None


def _first_csv_float(value: str | None) -> float | None:
    if value is None:
        return None
    for part in str(value).replace("|", ",").split(","):
        parsed = _to_float(part)
        if parsed is not None:
            return parsed
    return None


def _parse_format(fmt: str, sample_values: list[str]) -> dict[str, list[str]]:
    keys = [k.strip() for k in (fmt or "").split(":") if k.strip()]
    out: dict[str, list[str]] = {k: [] for k in keys}
    for sample in sample_values:
        values = sample.split(":")
        for idx, key in enumerate(keys):
            if idx < len(values) and values[idx] not in {"", "."}:
                out.setdefault(key, []).append(values[idx])
    return out


def _first_format_float(fmt_values: dict[str, list[str]], *keys: str) -> float | None:
    for key in keys:
        for value in fmt_values.get(key, []):
            parsed = _first_csv_float(value)
            if parsed is not None:
                return parsed
    return None


def _first_format_value(fmt_values: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        for value in fmt_values.get(key, []):
            raw = str(value).strip()
            if raw and raw != ".":
                return raw
    return None


def _zygosity_from_gt(genotype: str | None) -> str | None:
    if not genotype:
        return None
    alleles = genotype.replace("|", "/").split("/")
    if not alleles or any(a in {"", "."} for a in alleles):
        return "no_call"
    if len(alleles) == 1:
        return "hemizygous_alt" if alleles[0] != "0" else "hemizygous_ref"
    unique = set(alleles)
    if unique == {"0"}:
        return "homozygous_ref"
    if len(unique) == 1 and "0" not in unique:
        return "homozygous_alt"
    if "0" in unique:
        return "heterozygous"
    return "heterozygous_alt"


def _allele_balance(fmt_values: dict[str, list[str]], info: dict[str, str]) -> float | None:
    # Common FORMAT AD = ref,alt[,alt2...]. We import first ALT only.
    for ad in fmt_values.get("AD", []):
        parts = [_to_float(x) for x in str(ad).replace("|", ",").split(",")]
        if len(parts) >= 2 and parts[0] is not None and parts[1] is not None:
            total = parts[0] + parts[1]
            if total > 0:
                return round(parts[1] / total, 4)

    for key in ("AF", "VAF", "FA", "AO"):
        value = _first_format_float(fmt_values, key)
        if value is not None:
            if key == "AO":
                dp = _depth(fmt_values, info)
                if dp and dp > 0:
                    return round(value / dp, 4)
            return round(value, 4) if value <= 1.0 else None

    for key in ("AF", "VAF", "ALLELE_FRACTION"):
        value = _first_csv_float(info.get(key))
        if value is not None and value <= 1.0:
            return round(value, 4)
    return None


def _depth(fmt_values: dict[str, list[str]], info: dict[str, str]) -> int | None:
    value = _first_format_float(fmt_values, "DP", "MIN_DP")
    if value is None:
        value = _first_csv_float(info.get("DP"))
    return int(value) if value is not None else None


def _caller_list(info: dict[str, str], headers: list[str]) -> list[str]:
    callers = [x for x in str(info.get("CALLERS", "")).split(",") if x]
    if callers:
        return list(dict.fromkeys(callers))

    text = "\n".join(headers).lower()
    detected: list[str] = []
    if "haplotypecaller" in text or "gatk" in text:
        detected.append("HaplotypeCaller")
    if "deepvariant" in text:
        detected.append("DeepVariant")
    if "bcftools" in text:
        detected.append("bcftools")
    if "strelka" in text:
        detected.append("Strelka2")
    return detected


def _caller_agreement(info: dict[str, str], callers: list[str]) -> float:
    explicit = _to_float(info.get("CALLER_AGREEMENT"))
    if explicit is not None:
        return round(max(0.0, min(1.0, explicit)), 4)
    if len(callers) >= 3:
        return 0.95
    if len(callers) == 2:
        return 0.82
    if len(callers) == 1:
        return 0.55
    return 0.5


def _score01(value: float | None, cap: float) -> float:
    if value is None:
        return 0.5
    return round(max(0.0, min(1.0, value / cap)), 4)


def _trust_from_vcf(*, qual: float | None, filt: str, depth: int | None, gq: float | None, allele_balance: float | None, caller_agreement_score: float) -> tuple[float, dict[str, float]]:
    qual_score = _score01(qual, 100.0)
    depth_score = _score01(float(depth) if depth is not None else None, 30.0)
    genotype_quality_score = _score01(gq, 99.0)
    filter_score = 1.0 if filt in {"PASS", "."} else 0.15

    if allele_balance is None:
        allele_balance_score = 0.5
    else:
        # Heterozygous germline-like balance is best near 0.5; homozygous alt near 1.0 also okay.
        het_score = max(0.0, 1.0 - abs(allele_balance - 0.5) / 0.5)
        hom_alt_score = max(0.0, 1.0 - abs(allele_balance - 1.0) / 0.35)
        allele_balance_score = round(max(het_score, hom_alt_score), 4)

    trust = (
        0.25 * caller_agreement_score
        + 0.20 * qual_score
        + 0.20 * genotype_quality_score
        + 0.15 * depth_score
        + 0.10 * allele_balance_score
        + 0.10 * filter_score
    )
    explainability = {
        "caller_agreement_score": round(caller_agreement_score, 4),
        "variant_quality_score": qual_score,
        "genotype_quality_score": genotype_quality_score,
        "depth_score": depth_score,
        "allele_balance_score": allele_balance_score,
        "filter_pass_score": filter_score,
    }
    return round(max(0.0, min(100.0, trust * 100.0)), 2), explainability


def _first_info(info: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = info.get(key)
        if value not in {None, "", "."}:
            return str(value).split(",")[0]
    return None


def parse_variants_vcf(path: Path) -> list[dict]:
    """Parse VCF records into variant-import payload items.

    The parser keeps the public import contract small, but derives technical
    quality fields from real VCF columns/FORMAT: QUAL, FILTER, DP, AD, GQ,
    AF/VAF and caller hints. Derived values are stored in `trust_score` and
    `explainability`, so downstream API/UI can show why a variant is considered
    more or less technically reliable without claiming clinical meaning.
    """
    if not path.exists():
        return []

    items: list[dict] = []
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
            try:
                pos = int(parts[1])
            except ValueError:
                continue
            variant_id = parts[2].strip() if len(parts) > 2 else "."
            ref = parts[3].strip()
            alt = parts[4].split(",")[0].strip()
            qual = _to_float(parts[5] if len(parts) > 5 else None)
            filt = parts[6].strip() if len(parts) > 6 else "."
            info = _parse_info(parts[7])
            fmt_values = _parse_format(parts[8], parts[9:]) if len(parts) > 9 else {}

            callers = _caller_list(info, headers)
            caller_agreement_score = _caller_agreement(info, callers)
            dp = _depth(fmt_values, info)
            gq = _first_format_float(fmt_values, "GQ", "RGQ")
            ab = _allele_balance(fmt_values, info)
            genotype = _first_format_value(fmt_values, "GT")
            zygosity = _zygosity_from_gt(genotype)
            trust_score, explainability = _trust_from_vcf(
                qual=qual,
                filt=filt,
                depth=dp,
                gq=gq,
                allele_balance=ab,
                caller_agreement_score=caller_agreement_score,
            )
            if dp is not None:
                explainability["depth"] = float(dp)
            if gq is not None:
                explainability["genotype_quality"] = round(gq, 4)
            if qual is not None:
                explainability["variant_quality"] = round(qual, 4)
            if ab is not None:
                explainability["allele_balance"] = ab

            gnomad_freq = _first_csv_float(_first_info(info, "GNOMAD_AF", "gnomAD_AF", "AF_POPMAX"))
            consequence = _first_info(info, "CSQ", "ANN", "BCSQ")
            clinical_annotation = _first_info(info, "CLNSIG", "CLIN_SIG", "CLINVAR_CLNSIG")
            if clinical_annotation is None and variant_id.startswith("rs"):
                clinical_annotation = f"dbSNP:{variant_id}"

            items.append(
                {
                    "chrom": chrom,
                    "pos": pos,
                    "ref": ref,
                    "alt": alt,
                    "variant_type": _infer_variant_type(ref, alt),
                    "caller_list": callers,
                    "caller_agreement_score": caller_agreement_score,
                    "trust_score": trust_score,
                    "genotype": genotype,
                    "zygosity": zygosity,
                    "explainability": explainability,
                    "clinical_annotation": clinical_annotation,
                    "gnomad_freq": gnomad_freq,
                    "consequence": consequence,
                }
            )

    return items
