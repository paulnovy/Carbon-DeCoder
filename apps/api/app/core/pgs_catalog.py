from __future__ import annotations

import csv
import json
import os
from collections import Counter

from app.core.prs_catalog import list_downloaded_scores
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST_PATHS = [
    "/data/references/pgs/curated_manifest.json",
    "/data/references/pgs/curated_manifest.tsv",
    "/data/references/pgs/manifest.json",
    "/data/references/pgs/manifest.tsv",
]


def _ftp_url(pgs_id: str) -> str:
    return f"https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/{pgs_id}/ScoringFiles/{pgs_id}.txt.gz"


def manifest_path_candidates() -> list[Path]:
    env = os.getenv("WGS_PGS_CURATED_MANIFEST")
    paths = [Path(env)] if env else []
    paths.extend(Path(p) for p in DEFAULT_MANIFEST_PATHS)
    return paths


def find_manifest_path() -> Path | None:
    for p in manifest_path_candidates():
        if p.exists() and p.is_file():
            return p
    return None


def _normalize_entry(row: dict[str, Any]) -> dict[str, Any] | None:
    pgs_id = str(row.get("pgs_id") or row.get("PGS ID") or row.get("id") or "").strip().upper()
    if not pgs_id.startswith("PGS"):
        return None
    trait = str(row.get("trait_reported") or row.get("trait") or row.get("name") or pgs_id).strip()
    category = str(row.get("trait_category") or row.get("category") or "Uncategorized").strip() or "Uncategorized"
    variants_raw = row.get("variants_number") or row.get("variants_count") or row.get("variant_count")
    try:
        variants_number = int(variants_raw) if variants_raw not in {None, ""} else None
    except Exception:
        variants_number = None
    min_overlap_raw = row.get("min_overlap") or row.get("min_match_rate") or row.get("minimum_overlap")
    try:
        min_overlap = float(min_overlap_raw) if min_overlap_raw not in {None, ""} else 0.5
    except Exception:
        min_overlap = 0.5
    if min_overlap > 1:
        min_overlap = min_overlap / 100.0
    return {
        "pgs_id": pgs_id,
        "name": str(row.get("name") or trait),
        "trait_reported": trait,
        "trait_category": category,
        "variants_number": variants_number,
        "publication": row.get("publication") or row.get("citation") or "unknown",
        "genome_build": row.get("genome_build") or row.get("build"),
        "effect_type": row.get("effect_type") or row.get("weight_type"),
        "ancestry": row.get("ancestry") or row.get("development_ancestry"),
        "min_overlap": max(0.0, min(1.0, min_overlap)),
        "confidence": row.get("confidence") or row.get("confidence_level") or "curated",
        "caveat": row.get("caveat") or row.get("notes") or "Research-only; population portability and clinical utility are limited.",
        "ftp_url": row.get("ftp_url") or _ftp_url(pgs_id),
    }


def load_curated_pgs_manifest(path: str | Path | None = None) -> list[dict[str, Any]]:
    manifest = Path(path) if path else find_manifest_path()
    if not manifest:
        return []
    if manifest.suffix.lower() == ".json":
        data = json.loads(manifest.read_text(encoding="utf-8"))
        rows = data.get("items", data) if isinstance(data, dict) else data
    else:
        with manifest.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows or []:
        item = _normalize_entry(row)
        if not item or item["pgs_id"] in seen:
            continue
        seen.add(item["pgs_id"])
        out.append(item)
    return out


def validate_curated_pgs_manifest(path: str | Path | None = None) -> dict[str, Any]:
    manifest = Path(path) if path else find_manifest_path()
    if not manifest or not manifest.exists():
        return {
            "status": "missing",
            "path": str(manifest) if manifest else None,
            "valid": False,
            "count": 0,
            "errors": ["Curated PGS manifest not found."],
            "required_columns": ["pgs_id", "trait_reported", "trait_category", "genome_build", "min_overlap", "publication"],
            "expected_paths": [str(p) for p in manifest_path_candidates()],
            "non_diagnostic": True,
        }
    errors: list[str] = []
    try:
        items = load_curated_pgs_manifest(manifest)
    except Exception as exc:
        items = []
        errors.append(str(exc))
    if not items:
        errors.append("No valid PGS entries found.")

    ids = [x["pgs_id"] for x in items]
    duplicate_ids = sorted({x for x in ids if ids.count(x) > 1})
    if duplicate_ids:
        errors.append(f"Duplicate PGS IDs: {', '.join(duplicate_ids[:10])}")
    missing_build = [x["pgs_id"] for x in items if not x.get("genome_build")]
    missing_publication = [x["pgs_id"] for x in items if not x.get("publication") or x.get("publication") == "unknown"]
    weak_overlap = [x["pgs_id"] for x in items if float(x.get("min_overlap") or 0) < 0.5]
    warnings: list[str] = []
    if missing_build:
        warnings.append(f"{len(missing_build)} entries lack genome_build metadata.")
    if missing_publication:
        warnings.append(f"{len(missing_publication)} entries lack publication/citation metadata.")
    if weak_overlap:
        warnings.append(f"{len(weak_overlap)} entries use min_overlap below 0.50.")
    return {
        "status": "valid" if items and not errors else "invalid",
        "path": str(manifest),
        "valid": bool(items and not errors),
        "count": len(items),
        "categories": dict(Counter(item["trait_category"] for item in items)),
        "genome_builds": dict(Counter(str(item.get("genome_build") or "unknown") for item in items)),
        "errors": errors,
        "warnings": warnings,
        "items_preview": items[:10],
        "required_columns": ["pgs_id", "trait_reported", "trait_category", "genome_build", "min_overlap", "publication"],
        "expected_paths": [str(p) for p in manifest_path_candidates()],
        "non_diagnostic": True,
    }


def curated_manifest_status() -> dict[str, Any]:
    checked = validate_curated_pgs_manifest()
    return {
        "status": "available" if checked["valid"] else "missing",
        "path": checked.get("path"),
        "count": checked.get("count", 0),
        "categories": checked.get("categories", {}),
        "expected_paths": checked.get("expected_paths", []),
        "warning": None if checked["valid"] else "No valid curated PGS manifest configured; PRS panel remains disabled.",
        "validation": checked,
    }


def _category_from_trait(trait: str | None) -> str:
    text = str(trait or "").lower()
    if any(x in text for x in ["cancer", "carcinoma", "tumor", "breast", "prostate", "colorectal"]):
        return "Cancer"
    if any(x in text for x in ["diabetes", "glucose", "insulin", "bmi", "obesity", "cholesterol"]):
        return "Metabolic"
    if any(x in text for x in ["coronary", "heart", "cardio", "blood pressure", "stroke"]):
        return "Cardiovascular"
    if any(x in text for x in ["alzheimer", "parkinson", "depression", "neuro"]):
        return "Neurological"
    return "Uncategorized"


def draft_manifest_from_downloaded_scores(dest_dir: str = "/data/references/pgs", limit: int = 500) -> dict[str, Any]:
    """Build a non-reporting draft manifest from already-downloaded PGS metadata.

    This helps an operator review what is present locally without silently
    turning downloaded score files into an approved clinical/consumer panel.
    Entries are marked `curation_status=needs_review`; `/prs/panel/run` still
    requires an explicit curated manifest file.
    """
    metas = list_downloaded_scores(dest_dir)[: max(1, min(limit, 5000))]
    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    for meta in metas:
        pgs_id = str(meta.get("pgs_id") or "").upper()
        if not pgs_id.startswith("PGS"):
            continue
        genome_build = meta.get("genome_build")
        item_warnings: list[str] = []
        if not genome_build or str(genome_build).upper() in {"NR", "NA", "UNKNOWN"}:
            item_warnings.append("genome_build_missing_or_not_reported")
        if not meta.get("trait_reported"):
            item_warnings.append("trait_reported_missing")
        if not meta.get("variants_number"):
            item_warnings.append("variants_number_missing")
        items.append({
            "pgs_id": pgs_id,
            "name": meta.get("pgs_name") or meta.get("trait_reported") or pgs_id,
            "trait_reported": meta.get("trait_reported") or pgs_id,
            "trait_category": _category_from_trait(meta.get("trait_reported") or meta.get("trait_mapped")),
            "variants_number": meta.get("variants_number"),
            "publication": meta.get("publication") or "needs_manual_citation_review",
            "genome_build": None if item_warnings and "genome_build_missing_or_not_reported" in item_warnings else genome_build,
            "effect_type": meta.get("weight_type"),
            "ancestry": meta.get("ancestry") or "needs_manual_ancestry_review",
            "min_overlap": 0.70,
            "confidence": "needs_review",
            "caveat": "Draft only from local PGS metadata; not approved for reporting until manually curated.",
            "ftp_url": meta.get("ftp_url") or _ftp_url(pgs_id),
            "local_path": meta.get("local_path"),
            "curation_status": "needs_review",
            "warnings": item_warnings,
        })
    if not items:
        warnings.append("No downloaded PGS score metadata found.")
    needs_build = sum(1 for x in items if any(w == "genome_build_missing_or_not_reported" for w in x["warnings"]))
    if needs_build:
        warnings.append(f"{needs_build} draft entries need genome_build review before use.")
    return {
        "status": "draft_available" if items else "empty",
        "count": len(items),
        "items": items,
        "warnings": warnings,
        "message": "Draft manifest only. Save/review as curated_manifest.tsv/json before PRS panel reporting is enabled.",
        "non_diagnostic": True,
    }


HIGH_VALUE_TRAIT_KEYWORDS = {
    "Cancer": ["cancer", "carcinoma", "melanoma", "leukemia", "lymphoma", "tumor", "breast", "prostate", "colorectal", "ovarian"],
    "Cardiovascular": ["coronary", "heart", "cardio", "stroke", "blood pressure", "hypertension", "atrial", "cholesterol", "ldl"],
    "Metabolic": ["diabetes", "glucose", "insulin", "bmi", "obesity", "body mass", "lipid", "triglyceride"],
    "Neurological": ["alzheimer", "parkinson", "dementia", "depression", "migraine", "schizophrenia", "bipolar"],
    "Inflammatory/Immune": ["asthma", "allergy", "inflammatory", "crohn", "colitis", "rheumatoid", "psoriasis", "celiac"],
    "Kidney/Liver": ["kidney", "renal", "liver", "hepatic", "gallstone"],
    "Bone/Endocrine": ["bone", "osteoporosis", "thyroid", "hormone", "vitamin d"],
}


def pgs_storage_estimate(total_catalog_count: int = 5337, dest_dir: str = "/data/references/pgs") -> dict[str, Any]:
    root = Path(dest_dir)
    files = sorted(root.glob("PGS*.txt.gz")) if root.exists() else []
    downloaded_bytes = sum(f.stat().st_size for f in files)
    avg = downloaded_bytes / len(files) if files else 2_200_000
    estimated_total = int(avg * total_catalog_count)
    remaining = max(0, total_catalog_count - len(files))
    return {
        "downloaded_count": len(files),
        "downloaded_bytes": downloaded_bytes,
        "downloaded_gb": round(downloaded_bytes / (1024 ** 3), 3),
        "average_file_mb": round(avg / (1024 ** 2), 3),
        "estimated_catalog_count": total_catalog_count,
        "estimated_total_bytes": estimated_total,
        "estimated_total_gb": round(estimated_total / (1024 ** 3), 2),
        "remaining_count_estimate": remaining,
        "estimated_remaining_gb": round(max(0, estimated_total - downloaded_bytes) / (1024 ** 3), 2),
        "storage_path": str(root),
    }


def recommended_pgs_from_downloaded(dest_dir: str = "/data/references/pgs", per_category: int = 25, max_total: int = 300) -> dict[str, Any]:
    metas = list_downloaded_scores(dest_dir)
    buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in HIGH_VALUE_TRAIT_KEYWORDS}
    for meta in metas:
        text = " ".join(str(meta.get(k) or "") for k in ["trait_reported", "trait_mapped", "pgs_name"]).lower()
        for category, keywords in HIGH_VALUE_TRAIT_KEYWORDS.items():
            if any(k in text for k in keywords):
                buckets[category].append(meta)
                break
    items: list[dict[str, Any]] = []
    for category, entries in buckets.items():
        entries = sorted(entries, key=lambda m: int(m.get("variants_number") or 0), reverse=True)[:per_category]
        for meta in entries:
            pgs_id = str(meta.get("pgs_id") or "").upper()
            if not pgs_id:
                continue
            items.append({
                "pgs_id": pgs_id,
                "name": meta.get("pgs_name") or meta.get("trait_reported") or pgs_id,
                "trait_reported": meta.get("trait_reported") or pgs_id,
                "trait_category": category,
                "variants_number": meta.get("variants_number"),
                "genome_build": meta.get("genome_build"),
                "local_path": meta.get("local_path"),
                "reason": "high-value broad coverage heuristic from downloaded PGS Catalog scores",
            })
    seen: set[str] = set()
    deduped = []
    for item in items:
        if item["pgs_id"] in seen:
            continue
        seen.add(item["pgs_id"])
        deduped.append(item)
    return {
        "status": "available" if deduped else "empty",
        "count": min(len(deduped), max_total),
        "items": deduped[:max_total],
        "categories": {k: min(len(v), per_category) for k, v in buckets.items() if v},
        "message": "Development recommended coverage: broad, useful PRS categories selected from downloaded scores; not limited to consumer-provider panels.",
        "non_diagnostic": True,
    }


def draft_manifest_tsv(items: list[dict[str, Any]]) -> str:
    columns = ["pgs_id", "trait_reported", "trait_category", "variants_number", "publication", "genome_build", "min_overlap", "ancestry", "confidence", "caveat", "ftp_url"]
    lines = ["\t".join(columns)]
    for item in items:
        lines.append("\t".join(str(item.get(col) or "") for col in columns))
    return "\n".join(lines) + "\n"


def search_curated_pgs(q: str = "", trait: str = "", limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    q_norm = (q or "").strip().lower()
    trait_norm = (trait or "").strip().lower()

    items = load_curated_pgs_manifest()
    if trait_norm and trait_norm != "all":
        items = [x for x in items if x["trait_category"].lower() == trait_norm]

    if q_norm:
        items = [
            x
            for x in items
            if q_norm in x["pgs_id"].lower()
            or q_norm in (x.get("name") or "").lower()
            or q_norm in (x.get("trait_reported") or "").lower()
        ]

    count = len(items)
    return items[offset : offset + limit], count


def category_counts() -> dict[str, int]:
    return curated_manifest_status()["categories"]


# Backward-compatible name for legacy code paths. Deliberately empty unless a
# real operator-provided manifest is loaded through search_curated_pgs().
CURATED_PGS: list[dict] = []
