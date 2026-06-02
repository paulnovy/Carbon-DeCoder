from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_TRAITS_MANIFEST_PATHS = [
    "/data/references/traits/curated_traits.json",
    "/data/references/traits/curated_traits.tsv",
    "/data/references/traits/manifest.json",
    "/data/references/traits/manifest.tsv",
]


def manifest_path_candidates() -> list[Path]:
    env = os.getenv("WGS_TRAITS_MANIFEST")
    paths = [Path(env)] if env else []
    paths.extend(Path(p) for p in DEFAULT_TRAITS_MANIFEST_PATHS)
    return paths


def find_traits_manifest() -> Path | None:
    for path in manifest_path_candidates():
        if path.exists() and path.is_file():
            return path
    return None


def _norm_chrom(chrom: Any) -> str:
    raw = str(chrom or "").strip()
    if raw.lower().startswith("chr"):
        raw = raw[3:]
    if raw in {"M", "MT"}:
        return "M"
    return raw.upper()


def _key(chrom: Any, pos: Any, ref: Any, alt: Any) -> tuple[str, int, str, str] | None:
    try:
        return (_norm_chrom(chrom), int(pos), str(ref).upper(), str(alt).upper())
    except Exception:
        return None


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in {None, "", "."}:
            return default
        return float(value)
    except Exception:
        return default


def _normalize_rule(row: dict[str, Any]) -> dict[str, Any] | None:
    trait_id = str(row.get("trait_id") or row.get("id") or row.get("trait") or "").strip()
    trait_name = str(row.get("trait_name") or row.get("trait") or trait_id).strip()
    key = _key(row.get("chrom") or row.get("chr"), row.get("pos") or row.get("position"), row.get("ref"), row.get("alt") or row.get("effect_allele"))
    if not trait_id or not key:
        return None
    effect = str(row.get("effect") or row.get("interpretation") or row.get("label") or "associated variant observed").strip()
    confidence = str(row.get("confidence") or row.get("confidence_level") or "low").strip().lower()
    if confidence not in {"high", "moderate", "low", "insufficient"}:
        confidence = "low"
    return {
        "trait_id": trait_id,
        "trait_name": trait_name,
        "category": row.get("category") or "Traits & Wellness",
        "chrom": key[0],
        "pos": key[1],
        "ref": key[2],
        "alt": key[3],
        "gene": row.get("gene"),
        "effect": effect,
        "effect_direction": row.get("effect_direction") or row.get("direction"),
        "source": row.get("source") or row.get("publication") or row.get("citation") or "operator_curated",
        "source_version": row.get("source_version") or row.get("version"),
        "genome_build": row.get("genome_build") or row.get("build"),
        "confidence": confidence,
        "min_trust_score": _as_float(row.get("min_trust_score"), 50.0),
        "caveat": row.get("caveat") or "Research-only trait association; effect may be small and population-dependent.",
    }


def load_traits_manifest(path: str | Path | None = None) -> list[dict[str, Any]]:
    manifest = Path(path) if path else find_traits_manifest()
    if not manifest:
        return []
    if manifest.suffix.lower() == ".json":
        data = json.loads(manifest.read_text(encoding="utf-8"))
        rows = data.get("items", data.get("rules", data)) if isinstance(data, dict) else data
    else:
        with manifest.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    rules: list[dict[str, Any]] = []
    for row in rows or []:
        rule = _normalize_rule(row)
        if rule:
            rules.append(rule)
    return rules


def validate_traits_manifest(path: str | Path | None = None) -> dict[str, Any]:
    manifest = Path(path) if path else find_traits_manifest()
    if not manifest or not manifest.exists():
        return {
            "status": "missing",
            "valid": False,
            "path": str(manifest) if manifest else None,
            "count": 0,
            "errors": ["Curated traits manifest not found."],
            "expected_paths": [str(p) for p in manifest_path_candidates()],
            "required_columns": ["trait_id", "trait_name", "chrom", "pos", "ref", "alt", "effect", "source", "genome_build", "confidence"],
            "non_diagnostic": True,
        }
    errors: list[str] = []
    try:
        rules = load_traits_manifest(manifest)
    except Exception as exc:
        rules = []
        errors.append(str(exc))
    if not rules:
        errors.append("No valid exact-variant trait rules found.")
    missing_source = [r for r in rules if r.get("source") == "operator_curated"]
    missing_build = [r for r in rules if not r.get("genome_build")]
    warnings: list[str] = []
    if missing_source:
        warnings.append(f"{len(missing_source)} rules lack explicit source/citation metadata.")
    if missing_build:
        warnings.append(f"{len(missing_build)} rules lack genome_build metadata.")
    return {
        "status": "valid" if rules and not errors else "invalid",
        "valid": bool(rules and not errors),
        "path": str(manifest),
        "count": len(rules),
        "trait_count": len({r["trait_id"] for r in rules}),
        "errors": errors,
        "warnings": warnings,
        "items_preview": rules[:10],
        "expected_paths": [str(p) for p in manifest_path_candidates()],
        "required_columns": ["trait_id", "trait_name", "chrom", "pos", "ref", "alt", "effect", "source", "genome_build", "confidence"],
        "non_diagnostic": True,
    }


def evaluate_traits(variants: list[Any], *, sample_id: str, run_id: str | None, genome_build: str | None, path: str | Path | None = None) -> dict[str, Any]:
    rules = load_traits_manifest(path)
    if not rules:
        return {
            "sample_id": sample_id,
            "run_id": run_id,
            "status": "not_configured",
            "count": 0,
            "items": [],
            "provenance": {
                "source_database": "operator_curated_traits_manifest",
                "genome_build": genome_build,
                "input_variant_count": len(variants),
                "matched_variant_count": 0,
                "confidence_level": "insufficient",
                "warnings": ["Curated traits manifest is not configured."],
            },
            "non_diagnostic": True,
        }
    index: dict[tuple[str, int, str, str], Any] = {}
    for v in variants:
        key = _key(getattr(v, "chrom", None), getattr(v, "pos", None), getattr(v, "ref", None), getattr(v, "alt", None))
        if key:
            index[key] = v
    hits: list[dict[str, Any]] = []
    for rule in rules:
        key = (rule["chrom"], rule["pos"], rule["ref"], rule["alt"])
        variant = index.get(key)
        if not variant:
            continue
        trust = float(getattr(variant, "trust_score", 0.0) or 0.0)
        if trust < float(rule.get("min_trust_score") or 0.0):
            continue
        hits.append({
            "trait_id": rule["trait_id"],
            "trait_name": rule["trait_name"],
            "category": rule["category"],
            "variant_id": getattr(variant, "id", None),
            "chrom": getattr(variant, "chrom", None),
            "pos": getattr(variant, "pos", None),
            "ref": getattr(variant, "ref", None),
            "alt": getattr(variant, "alt", None),
            "gene": rule.get("gene"),
            "effect": rule["effect"],
            "effect_direction": rule.get("effect_direction"),
            "source": rule["source"],
            "source_version": rule.get("source_version"),
            "confidence": rule["confidence"],
            "technical_trust_score": trust,
            "caveat": rule["caveat"],
        })
    return {
        "sample_id": sample_id,
        "run_id": run_id,
        "status": "traits_found" if hits else "no_reportable_trait_matches",
        "count": len(hits),
        "items": hits,
        "provenance": {
            "source_database": "operator_curated_traits_manifest",
            "source_version": str(find_traits_manifest() or path),
            "genome_build": genome_build,
            "input_variant_count": len(variants),
            "matched_variant_count": len(hits),
            "overlap_pct": round((len(hits) / max(1, len(rules))) * 100.0, 3),
            "confidence_level": "low" if hits else "insufficient",
            "warnings": ["Trait rules are research-only and not comprehensive."],
        },
        "non_diagnostic": True,
    }
