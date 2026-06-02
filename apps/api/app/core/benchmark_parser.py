"""Enhanced benchmark parser supporting hap.py CSV, Truvari summary, and key=value formats.

hap.py output columns: Type, TRUTH.TOTAL, QUERY.TOTAL, TRUTH.TP, QUERY.TP,
TRUTH.FN, QUERY.FP, FP.gt, METRIC.Recall, METRIC.Precision, METRIC.F1_Score,
METRIC.Frac_NA, TRUTH.Ti.TV_ratio, QUERY.Ti.TV_ratio, TRUTH.Het_Hom_ratio,
QUERY.Het_Hom_ratio

Truvari summary JSON: { "TP-call": ..., "FP": ..., "FN": ..., "precision": ..., "recall": ..., "f1": ... }

GIAB stratification BED regions: Difficult, SegmentalDuplications, Homopolymers,
GCcontent, LowComplexity, VNTR, MHC, etc.
"""

from __future__ import annotations

import json
from pathlib import Path
import csv


def _to_float(value) -> float | None:
    if value is None:
        return None
    v = str(value).strip()
    if not v or v == "." or v == "nan" or v == "NA":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _pick(row: dict, names: list[str]) -> float | None:
    """Case-insensitive column lookup returning first numeric match."""
    low_map = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        for lk, lv in low_map.items():
            if lk == name.lower():
                fv = _to_float(lv)
                if fv is not None:
                    return fv
    return None


def _pick_str(row: dict, names: list[str]) -> str | None:
    low_map = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        for lk, lv in low_map.items():
            if lk == name.lower() and str(lv).strip():
                return str(lv).strip()
    return None


# ── hap.py CSV ─────────────────────────────────────────────────────────────────

def _parse_happy_csv(path: Path) -> dict:
    """Parse hap.py extended CSV output into a structured benchmark record."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if len(lines) < 2:
        return {}

    delim = "\t" if "\t" in lines[0] else ","
    reader = csv.DictReader(lines, delimiter=delim)
    rows = [dict(r) for r in reader if isinstance(r, dict)]
    if not rows:
        return {}

    out: dict = {
        "benchmark_type": "happy",
        "stratified_metrics": {},
        "type_breakdown": [],
        "filter_breakdown": [],
    }

    # Collect per-type metrics
    for row in rows:
        vtype = _pick_str(row, ["type", "varianttype", "label"]) or "unknown"
        vtype = vtype.strip().upper()

        entry = {
            "type": vtype,
            "filter": _pick_str(row, ["filter"]),
            "truth_total": _pick(row, ["truth.total", "TRUTH.TOTAL"]),
            "query_total": _pick(row, ["query.total", "QUERY.TOTAL"]),
            "truth_tp": _pick(row, ["truth.tp", "TRUTH.TP"]),
            "query_tp": _pick(row, ["query.tp", "QUERY.TP"]),
            "truth_fn": _pick(row, ["truth.fn", "TRUTH.FN"]),
            "query_fp": _pick(row, ["query.fp", "QUERY.FP"]),
            "fp_gt": _pick(row, ["fp.gt", "FP.GT"]),
            "recall": _pick(row, ["metric.recall", "recall", "METRIC.Recall"]),
            "precision": _pick(row, ["metric.precision", "precision", "METRIC.Precision"]),
            "f1": _pick(row, ["metric.f1_score", "f1_score", "f1", "METRIC.F1_Score"]),
            "frac_na": _pick(row, ["metric.frac_na", "frac_na", "METRIC.Frac_NA"]),
            "truth_titv": _pick(row, ["truth.ti.tv_ratio", "TRUTH.Ti.TV_ratio"]),
            "query_titv": _pick(row, ["query.ti.tv_ratio", "QUERY.Ti.TV_ratio"]),
            "truth_hethom": _pick(row, ["truth.het_hom_ratio", "TRUTH.Het_Hom_ratio"]),
            "query_hethom": _pick(row, ["query.het_hom_ratio", "QUERY.Het_Hom_ratio"]),
        }
        # Remove None values
        entry = {k: v for k, v in entry.items() if v is not None}
        out["type_breakdown"].append(entry)

    # Select TOTAL/ALL row for top-level summary
    total_row = None
    for entry in out["type_breakdown"]:
        if entry.get("type") in ("TOTAL", "ALL", "*"):
            total_row = entry
            break
    if not total_row:
        # Prefer SNP, then INDEL, then first
        for pref in ("SNP", "INDEL"):
            hit = next((e for e in out["type_breakdown"] if e.get("type") == pref), None)
            if hit:
                total_row = hit
                break
    if not total_row and out["type_breakdown"]:
        total_row = out["type_breakdown"][0]

    if total_row:
        out["precision"] = total_row.get("precision")
        out["recall"] = total_row.get("recall")
        out["f1"] = total_row.get("f1")
        out["truth_total"] = total_row.get("truth_total")
        out["query_total"] = total_row.get("query_total")
        out["query_fp"] = total_row.get("query_fp")
        out["truth_fn"] = total_row.get("truth_fn")

    # Build stratified metrics from per-type rows
    for entry in out["type_breakdown"]:
        t = entry.get("type", "").lower()
        f1 = entry.get("f1")
        if t and f1 is not None:
            out["stratified_metrics"][f"{t}_f1"] = f1
            out["stratified_metrics"][f"{t}_precision"] = entry.get("precision", 0)
            out["stratified_metrics"][f"{t}_recall"] = entry.get("recall", 0)

    return out


# ── Truvari summary JSON ───────────────────────────────────────────────────────

def _parse_truvari_json(path: Path) -> dict:
    """Parse Truvari summary.json into a structured benchmark record."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    out = {
        "benchmark_type": "truvari",
        "precision": _to_float(data.get("precision")),
        "recall": _to_float(data.get("recall")),
        "f1": _to_float(data.get("f1")),
        "stratified_metrics": {},
    }

    # Truvari includes per-SV-type breakdown sometimes
    for key in ("TP-call", "TP-base", "FP", "FN", "FP_gt", "FP_size", "FP_seqsim"):
        val = _to_float(data.get(key))
        if val is not None:
            out["stratified_metrics"][key.lower().replace("-", "_")] = val

    # Size-based stratification if present
    sz = data.get("size_dist", {})
    if isinstance(sz, dict):
        for size_bin, metrics in sz.items():
            if isinstance(metrics, dict):
                f1v = _to_float(metrics.get("f1"))
                if f1v is not None:
                    out["stratified_metrics"][f"sv_{size_bin}_f1"] = f1v

    return out


# ── GIAB stratification BED summary ─────────────────────────────────────────────

def _parse_giab_stratification(path: Path) -> dict[str, float]:
    """Parse GIAB stratification summary (key=value or JSON) into region-specific metrics."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    # Try JSON first
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            out = {}
            for region, val in data.items():
                if isinstance(val, (int, float)):
                    out[region] = float(val)
                elif isinstance(val, dict):
                    # Nested: { "region_name": { "f1": 0.95, ... } }
                    f1v = _to_float(val.get("f1") or val.get("F1_Score"))
                    if f1v is not None:
                        out[f"{region}_f1"] = f1v
            return out
    except json.JSONDecodeError:
        pass

    # key=value format
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" in line:
            k, v = line.split("=", 1)
            fv = _to_float(v)
            if fv is not None:
                out[k.strip()] = fv
    return out


# ── GIAB confidence region BED parser ──────────────────────────────────────────

GIAB_HIGH_CONFIDENCE_REGIONS = {
    "GRCh38": {
        "description": "HG002_GRCh38_1_22_v4.2.1_callable_multinter_gtconf.bed.gz",
        "source": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/latest/GRCh38/",
        "regions_kb": 2_649_000_000,  # ~2.65 Gb high-confidence
    },
    "GRCh37": {
        "description": "union13callableMQonlymerged_addcert_nouncert_excluderampsites_phvar2.bed.gz",
        "source": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/latest/GRCh37/",
        "regions_kb": 2_519_000_000,
    },
}

GIAB_STRATIFICATION_BEDS = [
    "AllDifficultRegions",
    "AllLowmap",
    "AllTandemRepeatsandHomopolymers_slop5",
    "CHM1-CHM132_callable",
    "CMC_unstable",
    "CodingRegions",
    "ComplexDuplications",
    "CRChighConfidenceBed",
    "FractionatedGaps",
    "GCcontent",
    "GRCh38_notinT2T",
    "Heterochromatin",
    "HighGC",
    "LowComplexity",
    "Lowmap",
    "MHC",
    "OtherDifficultregions",
    "PolyG",
    "PolyX",
    "Satellites",
    "SegmentalDuplications",
    "SimpleRepeat",
    "VNTR",
    "all_difficultregions_hg38",
    "notinCDSorphan",
    "notinT2TCMv1callable",
]


def get_giab_stratification_info() -> dict:
    """Return metadata about available GIAB stratification resources."""
    return {
        "high_confidence_regions": GIAB_HIGH_CONFIDENCE_REGIONS,
        "stratification_beds": GIAB_STRATIFICATION_BEDS,
        "truth_sets": {
            "HG002": {
                "description": "Ashkenazi Jewish son (NA24385) — Genome in a Bottle tier 1",
                "sample": "HG002",
                "truth_version": "v4.2.1",
                "variants_snv": 3_406_030,
                "variants_indel": 532_759,
                "callable_genome_fraction": 0.9208,
                "source": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/",
            },
            "HG003": {
                "description": "Father",
                "truth_version": "v4.2.1",
            },
            "HG004": {
                "description": "Mother",
                "truth_version": "v4.2.1",
            },
        },
    }


# ── Main entry point ────────────────────────────────────────────────────────────

def parse_benchmark_report(path: Path) -> dict:
    """Auto-detect and parse benchmark report from file extension/content.

    Supported formats:
    1. hap.py CSV/TSV — extended columns with Type, TRUTH.*, QUERY.*, METRIC.*
    2. Truvari summary.json — JSON with precision/recall/f1
    3. GIAB stratification summary — JSON or key=value with region-specific F1
    4. Generic key=value or TSV (legacy)

    Returns dict with: benchmark_type, precision, recall, f1, stratified_metrics, type_breakdown
    """
    if not path.exists():
        return {}

    suffix = path.suffix.lower()
    text_head = ""
    try:
        text_head = path.read_text(encoding="utf-8", errors="ignore")[:500]
    except OSError:
        pass

    # Auto-detect format
    if suffix == ".json":
        # Check if Truvari
        if "TP-call" in text_head or '"precision"' in text_head:
            result = _parse_truvari_json(path)
            if result:
                return result
        # Maybe GIAB stratification
        strat = _parse_giab_stratification(path)
        if strat:
            return {"benchmark_type": "giab_stratification", "stratified_metrics": strat}

    # hap.py CSV detection: look for METRIC.Recall or Type column
    if "METRIC.Recall" in text_head or "METRIC.Precision" in text_head or "TRUTH.TOTAL" in text_head:
        result = _parse_happy_csv(path)
        if result:
            return result

    # Generic header-table CSV/TSV (existing parser logic)
    lines = [ln.strip() for ln in text_head.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if any("=" in ln for ln in lines):
        return _parse_legacy_keyvalue(path)

    if len(lines) >= 2:
        return _parse_legacy_table(path, lines)

    return {}


def _parse_legacy_keyvalue(path: Path) -> dict:
    """Parse legacy key=value format."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    out: dict = {"benchmark_type": "legacy", "stratified_metrics": {}}
    for ln in lines:
        if "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        key = k.strip().lower()
        val = v.strip()
        if key == "benchmark_id":
            out["benchmark_id"] = val
        elif key in {"precision", "recall", "f1"}:
            fv = _to_float(val)
            if fv is not None:
                out[key] = fv
        elif key.startswith("stratified_"):
            metric = key.replace("stratified_", "", 1)
            fv = _to_float(val)
            if fv is not None:
                out["stratified_metrics"][metric] = fv
    return out


def _parse_legacy_table(path: Path, lines: list[str]) -> dict:
    """Parse legacy TSV/CSV table."""
    delim = "\t" if "\t" in lines[0] else ("," if "," in lines[0] else None)
    if not delim:
        return {}
    reader = csv.DictReader(lines, delimiter=delim)
    rows = [dict(r) for r in reader if isinstance(r, dict)]
    if not rows:
        return {}

    def row_type(r):
        low = {str(k).strip().lower(): str(v).strip().lower() for k, v in r.items()}
        return low.get("type") or low.get("varianttype") or low.get("label") or ""

    # Select row by priority
    selected = None
    for pref in ["total", "all", "overall", "snp", "indel"]:
        selected = next((r for r in rows if row_type(r) == pref), None)
        if selected:
            break
    if not selected:
        selected = rows[0]

    out: dict = {"benchmark_type": "legacy_table", "stratified_metrics": {}}

    # Extract benchmark_id if present as a column
    bid = _pick_str(selected, ["benchmark_id", "benchmark", "id"])
    if bid:
        out["benchmark_id"] = bid

    for k, v in selected.items():
        fv = _to_float(v)
        if fv is None:
            continue
        lk = str(k).strip().lower()
        if lk in {"precision", "recall", "f1", "f1_score"}:
            out["f1" if "f1" in lk else lk] = fv
        elif lk.startswith("stratified_"):
            metric = lk.replace("stratified_", "", 1)
            out["stratified_metrics"][metric] = fv

    # Per-type stratification from all rows
    for r in rows:
        t = row_type(r)
        f1v = _pick(r, ["f1", "f1_score", "metric.f1_score", "metric.f1"])
        if t and f1v is not None:
            out["stratified_metrics"][f"{t}_f1"] = f1v

    return out
