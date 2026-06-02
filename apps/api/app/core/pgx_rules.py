from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PGX_RULE_PATHS = [
    "/data/references/pgx/curated_pgx_rules.json",
    "/data/references/pgx/curated_pgx_rules.tsv",
    "/data/references/pgx/cpic_pharmgkb_rules.json",
    "/data/references/pgx/cpic_pharmgkb_rules.tsv",
]

PGX_CONFIDENCE_LEVELS = {"high", "moderate", "low", "insufficient"}


def pgx_rule_path_candidates() -> list[Path]:
    env = os.getenv("WGS_PGX_RULES_MANIFEST")
    paths = [Path(env)] if env else []
    paths.extend(Path(p) for p in DEFAULT_PGX_RULE_PATHS)
    return paths


def find_pgx_rules_manifest() -> Path | None:
    for path in pgx_rule_path_candidates():
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


def _variant_key(chrom: Any, pos: Any, ref: Any, alt: Any) -> tuple[str, int, str, str] | None:
    try:
        return (_norm_chrom(chrom), int(pos), str(ref).upper(), str(alt).upper())
    except Exception:
        return None


def _first(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, "", "."):
            return value
    return None


def _normalize_rule(row: dict[str, Any]) -> dict[str, Any] | None:
    key = _variant_key(
        _first(row, "chrom", "chr", "chromosome"),
        _first(row, "pos", "position"),
        _first(row, "ref", "reference_allele", "referenceallele"),
        _first(row, "alt", "alternate_allele", "alternateallele", "effect_allele"),
    )
    rule_id = str(_first(row, "rule_id", "id") or "").strip()
    gene = str(_first(row, "gene", "gene_symbol") or "").strip().upper()
    drug = str(_first(row, "drug", "medication", "drug_name") or "").strip()
    phenotype = str(_first(row, "phenotype", "pgx_phenotype", "diplotype_phenotype") or "").strip()
    recommendation = str(_first(row, "recommendation", "guidance", "interpretation") or "").strip()
    source = str(_first(row, "source", "source_database", "citation") or "").strip()
    if not key or not rule_id or not gene or not drug or not recommendation or not source:
        return None
    confidence = str(_first(row, "confidence", "confidence_level", "evidence_level") or "low").strip().lower()
    if confidence not in PGX_CONFIDENCE_LEVELS:
        confidence = "low"
    return {
        "rule_id": rule_id,
        "gene": gene,
        "drug": drug,
        "phenotype": phenotype or "variant-associated phenotype",
        "recommendation": recommendation,
        "chrom": key[0],
        "pos": key[1],
        "ref": key[2],
        "alt": key[3],
        "source": source,
        "source_version": _first(row, "source_version", "version"),
        "source_url": _first(row, "source_url", "url"),
        "genome_build": _first(row, "genome_build", "build"),
        "confidence": confidence,
        "caveat": _first(row, "caveat", "warning") or "Research-only PGx rule; confirm with validated clinical PGx workflow.",
    }


def load_pgx_rules_manifest(path: str | Path | None = None) -> list[dict[str, Any]]:
    manifest = Path(path) if path else find_pgx_rules_manifest()
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


def validate_pgx_rules_manifest(path: str | Path | None = None) -> dict[str, Any]:
    manifest = Path(path) if path else find_pgx_rules_manifest()
    if not manifest or not manifest.exists():
        return {
            "status": "missing",
            "valid": False,
            "path": str(manifest) if manifest else None,
            "count": 0,
            "errors": ["Curated PGx rule manifest not found."],
            "expected_paths": [str(p) for p in pgx_rule_path_candidates()],
            "required_columns": [
                "rule_id",
                "gene",
                "drug",
                "chrom",
                "pos",
                "ref",
                "alt",
                "recommendation",
                "source",
                "genome_build",
                "confidence",
            ],
            "non_diagnostic": True,
        }
    errors: list[str] = []
    try:
        rules = load_pgx_rules_manifest(manifest)
    except Exception as exc:
        rules = []
        errors.append(str(exc))
    if not rules:
        errors.append("No valid exact-variant PGx rules found.")
    missing_build = [r for r in rules if not r.get("genome_build")]
    missing_version = [r for r in rules if not r.get("source_version")]
    warnings: list[str] = []
    if missing_build:
        warnings.append(f"{len(missing_build)} rules lack genome_build metadata.")
    if missing_version:
        warnings.append(f"{len(missing_version)} rules lack source_version metadata.")
    return {
        "status": "valid" if rules and not errors else "invalid",
        "valid": bool(rules and not errors),
        "path": str(manifest),
        "count": len(rules),
        "gene_count": len({r["gene"] for r in rules}),
        "drug_count": len({r["drug"] for r in rules}),
        "errors": errors,
        "warnings": warnings,
        "items_preview": rules[:10],
        "expected_paths": [str(p) for p in pgx_rule_path_candidates()],
        "required_columns": [
            "rule_id",
            "gene",
            "drug",
            "chrom",
            "pos",
            "ref",
            "alt",
            "recommendation",
            "source",
            "genome_build",
            "confidence",
        ],
        "non_diagnostic": True,
    }


def evaluate_pgx_rules(
    variants: list[Any],
    *,
    sample_id: str,
    run_id: str | None,
    genome_build: str | None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    rules = load_pgx_rules_manifest(path)
    manifest = Path(path) if path else find_pgx_rules_manifest()
    provenance = {
        "source_database": "CPIC/PharmGKB curated rule manifest",
        "source_version": str(manifest) if manifest else None,
        "genome_build": genome_build,
        "rule_id": "exact_variant_pgx_rule_manifest",
        "input_variant_count": len(variants),
        "matched_variant_count": 0,
        "overlap_pct": 0.0,
        "confidence_level": "insufficient",
        "sample_id": sample_id,
        "last_run_id": run_id,
        "warnings": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if not rules:
        provenance["warnings"] = ["Curated CPIC/PharmGKB PGx rule manifest is not configured."]
        return {
            "sample_id": sample_id,
            "run_id": run_id,
            "status": "not_configured",
            "count": 0,
            "items": [],
            "provenance": provenance,
            "non_diagnostic": True,
        }

    index: dict[tuple[str, int, str, str], Any] = {}
    for variant in variants:
        key = _variant_key(
            getattr(variant, "chrom", None),
            getattr(variant, "pos", None),
            getattr(variant, "ref", None),
            getattr(variant, "alt", None),
        )
        if key:
            index[key] = variant

    items: list[dict[str, Any]] = []
    for rule in rules:
        variant = index.get((rule["chrom"], rule["pos"], rule["ref"], rule["alt"]))
        if not variant:
            continue
        items.append(
            {
                "rule_id": rule["rule_id"],
                "variant_id": getattr(variant, "id", None),
                "gene": rule["gene"],
                "drug": rule["drug"],
                "phenotype": rule["phenotype"],
                "recommendation": rule["recommendation"],
                "chrom": getattr(variant, "chrom", None),
                "pos": getattr(variant, "pos", None),
                "ref": getattr(variant, "ref", None),
                "alt": getattr(variant, "alt", None),
                "source": rule["source"],
                "source_version": rule.get("source_version"),
                "source_url": rule.get("source_url"),
                "confidence": rule["confidence"],
                "technical_trust_score": getattr(variant, "trust_score", None),
                "caveat": rule["caveat"],
            }
        )

    provenance["matched_variant_count"] = len(items)
    provenance["overlap_pct"] = round((len(items) / max(1, len(rules))) * 100.0, 3)
    provenance["confidence_level"] = "low" if items else "insufficient"
    if items:
        provenance["warnings"] = ["Curated PGx exact-variant rules are incomplete; use PharmCAT/validated PGx workflow before medication action."]
    else:
        provenance["warnings"] = ["No curated PGx exact-variant rule matched; this is not a negative PGx screen."]

    return {
        "sample_id": sample_id,
        "run_id": run_id,
        "status": "pgx_rules_matched" if items else "no_reportable_pgx_rule_matches",
        "count": len(items),
        "items": items,
        "drug_count": len({item["drug"] for item in items}),
        "gene_count": len({item["gene"] for item in items}),
        "provenance": provenance,
        "non_diagnostic": True,
    }
