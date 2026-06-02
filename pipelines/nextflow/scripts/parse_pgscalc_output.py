#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
from pathlib import Path


def open_text(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return path.open("rt", encoding="utf-8", errors="ignore")


def read_table(path: Path) -> list[dict[str, str]]:
    with open_text(path) as handle:
        rows = [line.strip() for line in handle if line.strip() and not line.startswith("#")]
    if not rows:
        return []
    delimiter = "\t" if "\t" in rows[0] else None
    header = rows[0].split(delimiter)
    out: list[dict[str, str]] = []
    for line in rows[1:]:
        parts = line.split(delimiter)
        out.append({header[idx]: parts[idx] if idx < len(parts) else "" for idx in range(len(header))})
    return out


def read_match_summary(path: Path | None) -> dict[str, dict[str, float | bool]]:
    if not path or not path.exists():
        return {}

    with path.open("rt", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        out: dict[str, dict[str, float | bool]] = {}
        for row in reader:
            accession = row.get("accession") or row.get("PGS") or row.get("Scoring file") or ""
            if not accession:
                continue
            count = float(row.get("count") or row.get("Count") or 0)
            status = (row.get("match_status") or row.get("Match type") or "").strip().lower()
            score_pass = str(row.get("score_pass") or row.get("Passed matching") or "").strip().lower()
            rec = out.setdefault(accession, {"matched": 0.0, "total": 0.0, "score_pass": False})
            rec["total"] = float(rec.get("total") or 0.0) + count
            if status == "matched":
                rec["matched"] = float(rec.get("matched") or 0.0) + count
            if score_pass in {"true", "1", "yes", "pass", "passed"}:
                rec["score_pass"] = True
    return out


def first_value(row: dict[str, str], *keys: str) -> str:
    lowered = {key.lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in {None, "", ".", "NA"}:
            return str(value)
    return ""


def as_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: float) -> int:
    return max(0, int(round(value)))


def quality_label(overlap_pct: float, score_pass: bool | None) -> str:
    if score_pass is False:
        return "low"
    if overlap_pct >= 80.0:
        return "high"
    if overlap_pct >= 50.0:
        return "medium"
    return "low"


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert pgsc_calc score output to WGS Cockpit PRS ingest format.")
    parser.add_argument("--scores", required=True)
    parser.add_argument("--summary")
    parser.add_argument("--out", required=True)
    parser.add_argument("--trait-prefix", default="")
    args = parser.parse_args()

    scores_path = Path(args.scores)
    summary_path = Path(args.summary) if args.summary else None
    rows = read_table(scores_path)
    if not rows:
        raise SystemExit("pgscalc_scores_empty")

    row = rows[0]
    accession = first_value(row, "PGS", "accession", "pgs_id") or "PGS_UNKNOWN"
    score = as_float(first_value(row, "SUM", "score", "score_avg", "AVG"))
    matched_from_row = as_float(first_value(row, "n_matched", "DENOM", "allele_count"))
    summary = read_match_summary(summary_path).get(accession, {})
    matched = float(summary.get("matched") or matched_from_row)
    total = float(summary.get("total") or matched or 0.0)
    overlap_pct = (matched / total * 100.0) if total else 0.0
    score_pass = summary.get("score_pass") if summary else None
    warnings = ["Research-use PRS from pgsc_calc; not diagnostic."]
    if not summary:
        warnings.append("pgsc_calc match summary not found; overlap is estimated from score output only.")
    if overlap_pct < 50.0:
        warnings.append("Variant overlap is low; do not interpret this score as meaningful.")

    trait = f"{args.trait_prefix}{accession}" if args.trait_prefix else accession
    out_path = Path(args.out)
    out_path.write_text(
        "\n".join(
            [
                f"trait={trait}",
                f"score_value={score}",
                f"overlap_pct={overlap_pct:.4f}",
                f"variant_count_total={as_int(total)}",
                f"variant_count_matched={as_int(matched)}",
                f"quality_label={quality_label(overlap_pct, score_pass if isinstance(score_pass, bool) else None)}",
                f"warning={' '.join(warnings)}",
                "non_diagnostic=true",
                f"source_tool=pgsc_calc",
                f"source_scores_path={scores_path}",
                f"source_match_summary_path={summary_path or ''}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
