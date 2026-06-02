#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_fasta(path: Path) -> str:
    chunks: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(">"):
                continue
            chunks.append(line.upper())
    return "".join(chunks)


def _stats(seq: str) -> dict:
    total = len(seq)
    if total == 0:
        return {
            "length": 0,
            "gc_fraction": 0.0,
            "n_fraction": 0.0,
            "base_fraction": {"A": 0.0, "C": 0.0, "G": 0.0, "T": 0.0, "N": 0.0},
        }
    counts = {"A": 0, "C": 0, "G": 0, "T": 0, "N": 0}
    for ch in seq:
        if ch in counts:
            counts[ch] += 1
    return {
        "length": total,
        "gc_fraction": (counts["G"] + counts["C"]) / total,
        "n_fraction": counts["N"] / total,
        "base_fraction": {k: counts[k] / total for k in counts},
    }


def _ratio(a: float, b: float) -> float:
    hi = max(a, b)
    lo = min(a, b)
    return 1.0 if hi == 0 else lo / hi


def _kmer_set(seq: str, k: int) -> set[str]:
    if len(seq) < k or k <= 0:
        return set()
    return {seq[i : i + k] for i in range(len(seq) - k + 1)}


def compare(vendor_seq: str, pipeline_seq: str, method: str, kmer_size: int | None) -> dict:
    v = _stats(vendor_seq)
    p = _stats(pipeline_seq)

    if method == "exact":
        min_len = min(len(vendor_seq), len(pipeline_seq))
        max_len = max(len(vendor_seq), len(pipeline_seq))
        matches = sum(1 for i in range(min_len) if vendor_seq[i] == pipeline_seq[i]) if min_len > 0 else 0
        identity = (matches / min_len) if min_len > 0 else 0.0
        coverage = (min_len / max_len) if max_len > 0 else 0.0
        return {
            "similarity_score": round((0.7 * identity) + (0.3 * coverage), 6),
            "snv_concordance": round(identity, 6),
            "indel_concordance": round(coverage, 6),
            "structural_concordance": round(coverage, 6),
            "summary": {
                "comparator_method": "exact",
                "vendor": v,
                "pipeline": p,
                "identity": round(identity, 6),
                "coverage": round(coverage, 6),
                "matches": matches,
                "mismatches": min_len - matches,
            },
        }

    if method == "kmer":
        k = kmer_size if (kmer_size is not None and kmer_size > 0) else 21
        shortest = min(len(vendor_seq), len(pipeline_seq))
        if shortest < k:
            k = max(5, shortest)
        vk = _kmer_set(vendor_seq, k)
        pk = _kmer_set(pipeline_seq, k)
        uni = vk | pk
        inter = vk & pk
        j = (len(inter) / len(uni)) if uni else 0.0
        length_score = _ratio(float(v["length"]), float(p["length"]))
        snv = j
        indel = length_score
        structural = (j + length_score) / 2.0
        return {
            "similarity_score": round((snv + indel + structural) / 3.0, 6),
            "snv_concordance": round(snv, 6),
            "indel_concordance": round(indel, 6),
            "structural_concordance": round(structural, 6),
            "summary": {
                "comparator_method": "kmer",
                "kmer_size": k,
                "vendor": v,
                "pipeline": p,
                "kmer_jaccard": round(j, 6),
                "shared_kmers": len(inter),
                "union_kmers": len(uni),
            },
        }

    # proxy
    length_score = _ratio(float(v["length"]), float(p["length"]))
    gc_score = max(0.0, 1.0 - abs(float(v["gc_fraction"]) - float(p["gc_fraction"])))
    n_score = max(0.0, 1.0 - abs(float(v["n_fraction"]) - float(p["n_fraction"])))
    base_scores = [_ratio(float(v["base_fraction"][b]), float(p["base_fraction"][b])) for b in ["A", "C", "G", "T"]]
    base_comp_score = sum(base_scores) / len(base_scores)
    snv = base_comp_score
    indel = length_score
    structural = (gc_score + n_score) / 2.0
    return {
        "similarity_score": round((snv + indel + structural) / 3.0, 6),
        "snv_concordance": round(snv, 6),
        "indel_concordance": round(indel, 6),
        "structural_concordance": round(structural, 6),
        "summary": {
            "comparator_method": "proxy",
            "vendor": v,
            "pipeline": p,
            "length_score": round(length_score, 6),
            "gc_score": round(gc_score, 6),
            "n_score": round(n_score, 6),
            "base_composition_score": round(base_comp_score, 6),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Vendor assembly validation comparator")
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--pipeline", required=True)
    ap.add_argument("--method", default="proxy", choices=["proxy", "kmer", "exact"])
    ap.add_argument("--kmer-size", type=int, default=21)
    ap.add_argument("--pass-threshold", type=float, default=0.98)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    vendor = Path(args.vendor)
    pipeline = Path(args.pipeline)
    if not vendor.exists():
        raise SystemExit(f"vendor_assembly_not_found: {vendor}")
    if not pipeline.exists():
        raise SystemExit(f"pipeline_assembly_not_found: {pipeline}")

    out_path = Path(args.output)
    vendor_seq = _read_fasta(vendor)
    pipeline_seq = _read_fasta(pipeline)
    compared = compare(vendor_seq, pipeline_seq, args.method, args.kmer_size)
    similarity = compared["similarity_score"]
    status = "passed" if similarity >= args.pass_threshold else "failed"

    payload = {
        "vendor_assembly_path": str(vendor),
        "pipeline_assembly_path": str(pipeline),
        "comparator_method": args.method,
        "kmer_size": args.kmer_size if args.method == "kmer" else None,
        "similarity_score": compared["similarity_score"],
        "snv_concordance": compared["snv_concordance"],
        "indel_concordance": compared["indel_concordance"],
        "structural_concordance": compared["structural_concordance"],
        "pass_threshold": args.pass_threshold,
        "status": status,
        "non_diagnostic": True,
        "summary": compared["summary"],
    }

    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out_path), "status": status, "similarity_score": similarity}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
