from pathlib import Path
import gzip


def _open_text(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return path.open("rt", encoding="utf-8", errors="ignore")


def _read_fasta_stats(path: Path) -> dict:
    total = 0
    counts = {"A": 0, "C": 0, "G": 0, "T": 0, "N": 0}

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(">"):
                continue
            seq = line.upper()
            for ch in seq:
                if ch in counts:
                    counts[ch] += 1
                    total += 1

    if total == 0:
        return {"length": 0, "gc_fraction": 0.0, "n_fraction": 0.0, "base_fraction": {k: 0.0 for k in counts}}

    gc = (counts["G"] + counts["C"]) / total
    n_frac = counts["N"] / total
    base_fraction = {k: counts[k] / total for k in counts}
    return {
        "length": total,
        "gc_fraction": gc,
        "n_fraction": n_frac,
        "base_fraction": base_fraction,
    }


def _ratio(a: float, b: float) -> float:
    hi = max(a, b)
    lo = min(a, b)
    return 1.0 if hi == 0 else lo / hi


def _read_fasta_sequence(path: Path) -> str:
    chunks: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(">"):
                continue
            chunks.append(line.upper())
    return "".join(chunks)


def _kmer_set(seq: str, k: int) -> set[str]:
    if len(seq) < k or k <= 0:
        return set()
    return {seq[i : i + k] for i in range(len(seq) - k + 1)}


def _normalize_chrom(chrom: str) -> str:
    return str(chrom or "").removeprefix("chr")


def _read_vcf_records(path: Path) -> set[tuple[str, int, str, str]]:
    records: set[tuple[str, int, str, str]] = set()
    with _open_text(path) as handle:
        for raw in handle:
            if not raw.strip() or raw.startswith("#"):
                continue
            parts = raw.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            chrom, pos_raw, _id, ref, alts = parts[:5]
            try:
                pos = int(pos_raw)
            except ValueError:
                continue
            for alt in alts.split(","):
                if alt and alt != ".":
                    records.add((_normalize_chrom(chrom), pos, ref.upper(), alt.upper()))
    return records


def _variant_type(record: tuple[str, int, str, str]) -> str:
    _chrom, _pos, ref, alt = record
    if alt.startswith("<") and alt.endswith(">"):
        return "sv"
    return "snp" if len(ref) == 1 and len(alt) == 1 else "indel"


def _metrics(truth: set, query: set) -> dict:
    tp = len(truth & query)
    fp = len(query - truth)
    fn = len(truth - query)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "truth_total": len(truth),
        "query_total": len(query),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def compare_vendor_vcfs(vendor_vcf_path: Path, pipeline_vcf_path: Path) -> dict:
    """Compare vendor and pipeline VCFs by exact normalized CHROM/POS/REF/ALT records."""
    truth = _read_vcf_records(vendor_vcf_path)
    query = _read_vcf_records(pipeline_vcf_path)
    overall = _metrics(truth, query)
    by_type = {}
    for kind in ("snp", "indel", "sv"):
        t = {rec for rec in truth if _variant_type(rec) == kind}
        q = {rec for rec in query if _variant_type(rec) == kind}
        if t or q:
            by_type[kind] = _metrics(t, q)

    return {
        "similarity_score": overall["f1"],
        "snv_concordance": by_type.get("snp", {}).get("f1"),
        "indel_concordance": by_type.get("indel", {}).get("f1"),
        "structural_concordance": by_type.get("sv", {}).get("f1"),
        "stats": {
            "comparator_method": "vcf_exact",
            "vendor_vcf_path": str(vendor_vcf_path),
            "pipeline_vcf_path": str(pipeline_vcf_path),
            "overall": overall,
            "by_type": by_type,
        },
    }


def compare_vendor_assemblies(
    vendor_path: Path,
    pipeline_path: Path,
    method: str = "proxy",
    kmer_size: int | None = None,
) -> dict:
    """Compute lightweight proxy concordance metrics between two assemblies.

    This is a technical scaffold metric (non-diagnostic), not a true variant-level concordance.
    """
    v = _read_fasta_stats(vendor_path)
    p = _read_fasta_stats(pipeline_path)

    if method == "exact":
        vendor_seq = _read_fasta_sequence(vendor_path)
        pipeline_seq = _read_fasta_sequence(pipeline_path)
        min_len = min(len(vendor_seq), len(pipeline_seq))
        max_len = max(len(vendor_seq), len(pipeline_seq))

        matches = 0
        if min_len > 0:
            matches = sum(1 for i in range(min_len) if vendor_seq[i] == pipeline_seq[i])
        mismatches = min_len - matches
        identity = (matches / min_len) if min_len > 0 else 0.0
        coverage = (min_len / max_len) if max_len > 0 else 0.0

        snv_concordance = identity
        indel_concordance = coverage
        structural_concordance = coverage
        similarity_score = (0.7 * snv_concordance) + (0.3 * indel_concordance)

        return {
            "similarity_score": round(similarity_score, 6),
            "snv_concordance": round(snv_concordance, 6),
            "indel_concordance": round(indel_concordance, 6),
            "structural_concordance": round(structural_concordance, 6),
            "stats": {
                "vendor": v,
                "pipeline": p,
                "comparator_method": "exact",
                "vendor_seq_len": len(vendor_seq),
                "pipeline_seq_len": len(pipeline_seq),
                "shared_prefix_len": min_len,
                "matches": matches,
                "mismatches": mismatches,
                "length_delta": abs(len(vendor_seq) - len(pipeline_seq)),
                "identity": round(identity, 6),
                "coverage": round(coverage, 6),
            },
        }

    if method == "kmer":
        vendor_seq = _read_fasta_sequence(vendor_path)
        pipeline_seq = _read_fasta_sequence(pipeline_path)
        k = kmer_size if (kmer_size is not None and kmer_size > 0) else 21
        shortest = min(len(vendor_seq), len(pipeline_seq))
        if shortest < k:
            k = max(5, shortest)

        vendor_k = _kmer_set(vendor_seq, k)
        pipeline_k = _kmer_set(pipeline_seq, k)
        union = vendor_k | pipeline_k
        inter = vendor_k & pipeline_k
        kmer_jaccard = (len(inter) / len(union)) if union else 0.0

        length_score = _ratio(float(v["length"]), float(p["length"]))
        snv_concordance = kmer_jaccard
        indel_concordance = length_score
        structural_concordance = (kmer_jaccard + length_score) / 2.0
        similarity_score = (snv_concordance + indel_concordance + structural_concordance) / 3.0

        return {
            "similarity_score": round(similarity_score, 6),
            "snv_concordance": round(snv_concordance, 6),
            "indel_concordance": round(indel_concordance, 6),
            "structural_concordance": round(structural_concordance, 6),
            "stats": {
                "vendor": v,
                "pipeline": p,
                "comparator_method": "kmer",
                "kmer_k": k,
                "vendor_kmers": len(vendor_k),
                "pipeline_kmers": len(pipeline_k),
                "shared_kmers": len(inter),
                "union_kmers": len(union),
                "kmer_jaccard": round(kmer_jaccard, 6),
                "length_score": round(length_score, 6),
            },
        }

    if method != "proxy":
        raise ValueError(f"unsupported_comparator_method:{method}")

    length_score = _ratio(float(v["length"]), float(p["length"]))
    gc_score = max(0.0, 1.0 - abs(float(v["gc_fraction"]) - float(p["gc_fraction"])))
    n_score = max(0.0, 1.0 - abs(float(v["n_fraction"]) - float(p["n_fraction"])))

    base_scores = []
    for b in ["A", "C", "G", "T"]:
        base_scores.append(_ratio(float(v["base_fraction"][b]), float(p["base_fraction"][b])))
    base_comp_score = sum(base_scores) / len(base_scores)

    snv_concordance = base_comp_score
    indel_concordance = length_score
    structural_concordance = (gc_score + n_score) / 2.0
    similarity_score = (snv_concordance + indel_concordance + structural_concordance) / 3.0

    return {
        "similarity_score": round(similarity_score, 6),
        "snv_concordance": round(snv_concordance, 6),
        "indel_concordance": round(indel_concordance, 6),
        "structural_concordance": round(structural_concordance, 6),
        "stats": {
            "vendor": v,
            "pipeline": p,
            "comparator_method": "proxy",
            "length_score": round(length_score, 6),
            "gc_score": round(gc_score, 6),
            "n_score": round(n_score, 6),
            "base_composition_score": round(base_comp_score, 6),
        },
    }
