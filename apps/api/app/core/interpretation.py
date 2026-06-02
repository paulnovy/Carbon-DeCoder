from __future__ import annotations

import csv
import gzip
import json
import os
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.monogenic_catalog import MONOGENIC_CATALOG_VERSION, match_monogenic_catalog
from app.core.pgx_rules import find_pgx_rules_manifest, validate_pgx_rules_manifest
from app.core.traits_engine import find_traits_manifest, validate_traits_manifest


CONFIDENCE_LEVELS = {"high", "moderate", "low", "insufficient"}
PATHOGENIC_SIGS = {"pathogenic", "likely_pathogenic", "pathogenic/likely_pathogenic"}
VUS_SIGS = {"uncertain_significance", "vus"}
BENIGN_SIGS = {"benign", "likely_benign", "benign/likely_benign"}

# ACMG SF v3.x actionable gene set. Keep this as an explicit resource so the
# app can do opt-in secondary-findings scans without pretending to diagnose.
# The label uses v3.3 because that is the roadmap target; update provenance when
# this list is refreshed from ACMG.
ACMG_SF_VERSION = "ACMG SF v3.3"
ACMG_SF_GENES = {
    "ABCD1", "ACTA2", "ACTC1", "ACVRL1", "APC", "APOB", "ATP7B", "BMPR1A", "BRCA1", "BRCA2",
    "BTD", "CACNA1S", "CALM1", "CALM2", "CALM3", "CASQ2", "COL3A1", "CYP27A1", "DES", "DSC2",
    "DSG2", "DSP", "ENG", "FBN1", "FH", "FLNC", "GAA", "GLA", "HFE", "HNF1A", "KCNH2",
    "KCNJ2", "KCNQ1", "LDLR", "LMNA", "MAX", "MEN1", "MLH1", "MSH2", "MSH6", "MUTYH",
    "MYBPC3", "MYH11", "MYH7", "MYL2", "MYL3", "NF2", "OTC", "PALB2", "PCSK9", "PKP2",
    "PMS2", "PRKAG2", "PTEN", "RB1", "RET", "RYR1", "RYR2", "SDHAF2", "SDHB", "SDHC",
    "SDHD", "SMAD3", "SMAD4", "STK11", "TGFBR1", "TGFBR2", "TMEM43", "TNNI3", "TNNT2",
    "TP53", "TPM1", "TSC1", "TSC2", "VHL", "WT1", "PLN",
}

DEFAULT_CLINVAR_PATHS = [
    "/data/references/clinvar/clinvar.tsv",
    "/data/references/clinvar/clinvar.tsv.gz",
    "/data/references/clinvar/variant_summary.tsv.gz",
    "/data/references/clinvar/variant_summary.txt.gz",
]


class InterpretationProvenance(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    source_database: str
    source_version: str | None = None
    source_date: str | None = None
    genome_build: str | None = None
    rule_id: str | None = None
    model_id: str | None = None
    input_variant_count: int = 0
    matched_variant_count: int = 0
    overlap_pct: float = 0.0
    confidence_level: str = "insufficient"
    warnings: list[str] = Field(default_factory=list)
    sample_id: str | None = None
    last_run_id: str | None = None
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class InterpretationResource(BaseModel):
    id: str
    module: str
    source_database: str
    source_version: str | None = None
    source_date: str | None = None
    genome_build: str | None = None
    path: str | None = None
    status: str = "missing"
    required: bool = False
    size_bytes: int | None = None
    warnings: list[str] = Field(default_factory=list)


class BuildValidationResult(BaseModel):
    status: str
    reference_id: str | None = None
    expected_build: str | None = None
    expected_contig_style: str | None = None
    observed_contig_style: str | None = None
    variant_count: int = 0
    mismatch_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    ready_for_interpretation: bool = False


@dataclass(frozen=True)
class ClinVarRecord:
    chrom: str
    pos: int
    ref: str
    alt: str
    gene: str
    condition: str
    clinical_significance: str
    review_status: str
    accession: str | None = None
    inheritance: str | None = None
    source_version: str | None = None


def today_version() -> str:
    return date.today().isoformat()


def normalize_contig(chrom: str) -> str:
    raw = str(chrom or "").strip()
    if raw.lower().startswith("chr"):
        raw = raw[3:]
    if raw in {"23", "X"}:
        return "X"
    if raw in {"24", "Y"}:
        return "Y"
    if raw in {"M", "MT", "chrM"}:
        return "M"
    return raw.upper()


def variant_key(chrom: str, pos: int, ref: str, alt: str) -> tuple[str, int, str, str]:
    return (normalize_contig(chrom), int(pos), str(ref).upper(), str(alt).upper())


def infer_observed_contig_style(chroms: list[str]) -> str | None:
    if not chroms:
        return None
    chr_count = sum(1 for c in chroms if str(c).lower().startswith("chr"))
    numeric_count = sum(1 for c in chroms if not str(c).lower().startswith("chr"))
    return "chr" if chr_count >= numeric_count else "numeric"


def validate_build(reference: Any | None, variants: list[Any]) -> BuildValidationResult:
    ref_id = getattr(reference, "id", None)
    expected_build = getattr(reference, "version", None)
    expected_style = getattr(reference, "contig_style", None)
    chroms = [str(getattr(v, "chrom", "")) for v in variants if getattr(v, "chrom", None)]
    observed_style = infer_observed_contig_style(chroms)
    warnings: list[str] = []
    mismatch_count = 0

    if not variants:
        warnings.append("No variants imported for this sample yet.")
    if expected_style and observed_style and expected_style != observed_style:
        mismatch_count = len(chroms)
        warnings.append(f"Contig style mismatch: expected {expected_style}, observed {observed_style}.")
    if reference is None:
        warnings.append("Reference metadata not found.")

    ready = bool(variants) and reference is not None and mismatch_count == 0
    status = "ready" if ready else "no_variants" if not variants else "build_mismatch" if mismatch_count else "reference_unknown"
    return BuildValidationResult(
        status=status,
        reference_id=ref_id,
        expected_build=expected_build,
        expected_contig_style=expected_style,
        observed_contig_style=observed_style,
        variant_count=len(variants),
        mismatch_count=mismatch_count,
        warnings=warnings,
        ready_for_interpretation=ready,
    )


def clinvar_path_candidates() -> list[Path]:
    env_path = os.getenv("WGS_CLINVAR_TSV")
    paths = [Path(env_path)] if env_path else []
    paths.extend(Path(p) for p in DEFAULT_CLINVAR_PATHS)
    return paths


def find_clinvar_tsv() -> Path | None:
    for p in clinvar_path_candidates():
        if p.exists() and p.is_file():
            return p
    return None


def _file_resource(
    *,
    id: str,
    module: str,
    source_database: str,
    path: Path | None,
    required: bool,
    source_version: str | None = None,
    source_date: str | None = None,
    genome_build: str | None = None,
    warnings: list[str] | None = None,
) -> InterpretationResource:
    exists = bool(path and path.exists() and path.is_file())
    size = path.stat().st_size if exists and path else None
    return InterpretationResource(
        id=id,
        module=module,
        source_database=source_database,
        source_version=source_version or (path.name if exists and path else None),
        source_date=source_date,
        genome_build=genome_build,
        path=str(path) if path else None,
        status="available" if exists else "missing",
        required=required,
        size_bytes=size,
        warnings=warnings or [],
    )


def interpretation_resource_registry() -> list[InterpretationResource]:
    clinvar = find_clinvar_tsv()
    pgs_dir = Path(os.getenv("WGS_PGS_DIR", "/data/references/pgs"))
    pgs_files = sorted(pgs_dir.glob("*.txt.gz")) if pgs_dir.exists() else []
    traits_manifest = find_traits_manifest()
    traits_validation = validate_traits_manifest()
    pgx_manifest = find_pgx_rules_manifest()
    pgx_validation = validate_pgx_rules_manifest()
    resources = [
        _file_resource(
            id="clinvar_exact_match_tsv",
            module="clinvar_monogenic",
            source_database="ClinVar",
            path=clinvar,
            required=True,
            source_date=today_version() if clinvar else None,
            genome_build=os.getenv("WGS_CLINVAR_BUILD"),
            warnings=[] if clinvar else ["Set WGS_CLINVAR_TSV or install /data/references/clinvar/clinvar.tsv(.gz)."],
        ),
        InterpretationResource(
            id="acmg_sf_gene_set",
            module="acmg_secondary_findings",
            source_database="ACMG",
            source_version=ACMG_SF_VERSION,
            source_date=today_version(),
            status="available",
            required=True,
            size_bytes=len(ACMG_SF_GENES),
            warnings=["Opt-in only; not a diagnostic screen."],
        ),
        InterpretationResource(
            id="pgs_catalog_score_directory",
            module="polygenic_risk_scores",
            source_database="PGS Catalog",
            source_version=f"{len(pgs_files)} downloaded score files",
            path=str(pgs_dir),
            status="available" if pgs_files else "missing",
            required=True,
            warnings=[] if pgs_files else ["Download/version curated PGS score manifests before reporting PRS."],
        ),
        InterpretationResource(
            id="curated_traits_manifest",
            module="traits_wellness",
            source_database="operator_curated_traits_manifest",
            source_version=f"{traits_validation.get('count', 0)} rules" if traits_validation.get("valid") else None,
            path=str(traits_manifest) if traits_manifest else None,
            status="available" if traits_validation.get("valid") else "missing",
            required=True,
            warnings=(traits_validation.get("warnings") or []) + ([] if traits_validation.get("valid") else traits_validation.get("errors", [])),
        ),
        InterpretationResource(
            id="pharmcat_executable",
            module="pharmacogenetics",
            source_database="PharmCAT/CPIC",
            source_version="local executable" if (shutil.which("pharmcat") or Path("/opt/pharmcat/pharmcat.jar").exists()) else None,
            path=shutil.which("pharmcat") or ("/opt/pharmcat/pharmcat.jar" if Path("/opt/pharmcat/pharmcat.jar").exists() else None),
            status="available" if (shutil.which("pharmcat") or Path("/opt/pharmcat/pharmcat.jar").exists()) else "missing",
            required=True,
            warnings=[] if (shutil.which("pharmcat") or Path("/opt/pharmcat/pharmcat.jar").exists()) else ["Install/wire PharmCAT before PGx reporting."],
        ),
        InterpretationResource(
            id="cpic_pharmgkb_rule_manifest",
            module="pharmacogenetics",
            source_database="CPIC/PharmGKB curated rule manifest",
            source_version=f"{pgx_validation.get('count', 0)} rules" if pgx_validation.get("valid") else None,
            path=str(pgx_manifest) if pgx_manifest else None,
            status="available" if pgx_validation.get("valid") else "missing",
            required=True,
            warnings=(pgx_validation.get("warnings") or []) + ([] if pgx_validation.get("valid") else pgx_validation.get("errors", [])),
        ),
        InterpretationResource(
            id="haplogrep_executable",
            module="haplogroups",
            source_database="HaploGrep/PhyloTree",
            source_version="local executable" if (shutil.which("haplogrep3") or shutil.which("haplogrep") or shutil.which("haplogrep2") or Path("/opt/haplogrep/haplogrep.jar").exists()) else None,
            path=shutil.which("haplogrep3") or shutil.which("haplogrep") or shutil.which("haplogrep2") or ("/opt/haplogrep/haplogrep.jar" if Path("/opt/haplogrep/haplogrep.jar").exists() else None),
            status="available" if (shutil.which("haplogrep3") or shutil.which("haplogrep") or shutil.which("haplogrep2") or Path("/opt/haplogrep/haplogrep.jar").exists()) else "missing",
            required=True,
            warnings=[] if (shutil.which("haplogrep3") or shutil.which("haplogrep") or shutil.which("haplogrep2") or Path("/opt/haplogrep/haplogrep.jar").exists()) else ["Install/wire HaploGrep before mtDNA haplogroup reporting."],
        ),
        InterpretationResource(
            id="vep_executable",
            module="gene_transcript_annotation",
            source_database="Ensembl VEP",
            source_version="local executable" if shutil.which("vep") else None,
            path=shutil.which("vep"),
            status="available" if shutil.which("vep") else "missing",
            required=True,
            warnings=[] if shutil.which("vep") else ["Install VEP/offline cache before transcript-level reporting."],
        ),
    ]
    return resources


def resources_by_module() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for res in interpretation_resource_registry():
        grouped.setdefault(res.module, []).append(res.model_dump())
    return grouped


def _open_text(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return path.open("rt", encoding="utf-8", errors="ignore")


def _norm_name(name: str) -> str:
    return str(name or "").strip().lower().replace(" ", "_").replace("-", "_")


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        key = _norm_name(name)
        if key in row and row[key] not in {None, "", ".", "-"}:
            return str(row[key]).strip()
    return ""


def normalize_clinical_significance(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_").replace("/", "/")
    raw = raw.replace("likely_pathogenic,pathogenic", "pathogenic/likely_pathogenic")
    if "conflicting" in raw:
        return "conflicting"
    if "pathogenic" in raw and "benign" not in raw:
        return "likely_pathogenic" if "likely" in raw and "pathogenic" in raw else "pathogenic"
    if "uncertain" in raw or raw == "vus":
        return "uncertain_significance"
    if "benign" in raw:
        return "likely_benign" if "likely" in raw else "benign"
    return raw or "unknown"


def validate_clinvar_tsv(path: str | Path | None = None, max_rows: int = 5000) -> dict[str, Any]:
    target = Path(path) if path else find_clinvar_tsv()
    if not target or not target.exists():
        return {
            "status": "missing",
            "path": str(target) if target else None,
            "valid": False,
            "rows_checked": 0,
            "valid_exact_match_rows": 0,
            "errors": ["ClinVar TSV file not found."],
            "required_columns": ["chrom", "pos", "ref", "alt", "gene", "clinical_significance", "review_status"],
        }

    rows_checked = 0
    valid_rows = 0
    genes: set[str] = set()
    sig_counts: dict[str, int] = {}
    errors: list[str] = []
    fieldnames: list[str] = []
    try:
        with _open_text(target) as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fieldnames = [_norm_name(f) for f in (reader.fieldnames or [])]
            for row in reader:
                rows_checked += 1
                norm = {_norm_name(k): v for k, v in row.items()}
                chrom = _first(norm, "chrom", "chr", "contig", "chromosome", "chromosomeaccession")
                pos_s = _first(norm, "pos", "position", "start", "start_position")
                ref = _first(norm, "ref", "referenceallele", "reference_allele")
                alt = _first(norm, "alt", "alternateallele", "alternate_allele", "alternate")
                gene = _first(norm, "gene", "gene_symbol", "genesymbol")
                sig = normalize_clinical_significance(_first(norm, "clinical_significance", "clin_sig", "significance"))
                try:
                    int(float(str(pos_s).replace(",", "")))
                    pos_ok = True
                except Exception:
                    pos_ok = False
                if chrom and pos_ok and ref and alt:
                    valid_rows += 1
                    if gene:
                        genes.add(gene)
                    sig_counts[sig] = sig_counts.get(sig, 0) + 1
                if rows_checked >= max_rows:
                    break
    except Exception as exc:
        errors.append(str(exc))

    if rows_checked == 0:
        errors.append("No data rows found.")
    if valid_rows == 0:
        errors.append("No exact-match rows found. Expected chr/pos/ref/alt-style ClinVar export, not only NCBI variant_summary coordinates without alleles.")
    return {
        "status": "valid" if valid_rows > 0 and not errors else "invalid",
        "path": str(target),
        "valid": valid_rows > 0 and not errors,
        "rows_checked": rows_checked,
        "valid_exact_match_rows": valid_rows,
        "fieldnames": fieldnames,
        "gene_count_seen": len(genes),
        "clinical_significance_counts": sig_counts,
        "errors": errors,
        "required_columns": ["chrom", "pos", "ref", "alt", "gene", "clinical_significance", "review_status"],
        "non_diagnostic": True,
    }


def parse_clinvar_tsv(path: Path) -> dict[tuple[str, int, str, str], list[ClinVarRecord]]:
    try:
        stat = path.stat()
    except OSError:
        return {}
    return _parse_clinvar_tsv_cached(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _parse_clinvar_tsv_cached(path_s: str, mtime_ns: int, size_bytes: int) -> dict[tuple[str, int, str, str], list[ClinVarRecord]]:
    path = Path(path_s)
    records: dict[tuple[str, int, str, str], list[ClinVarRecord]] = {}
    with _open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            return records
        reader.fieldnames = [_norm_name(f) for f in reader.fieldnames]
        for row in reader:
            norm = {_norm_name(k): v for k, v in row.items()}
            chrom = _first(norm, "chrom", "chr", "contig", "chromosome", "chromosomeaccession")
            # NCBI variant_summary may not include REF/ALT in a simple way; this
            # parser intentionally supports exact-match TSV exports first.
            pos_s = _first(norm, "pos", "position", "start", "start_position")
            ref = _first(norm, "ref", "referenceallele", "reference_allele")
            alt = _first(norm, "alt", "alternateallele", "alternate_allele", "alternate")
            if not chrom or not pos_s or not ref or not alt:
                continue
            try:
                pos = int(float(pos_s.replace(",", "")))
            except ValueError:
                continue
            rec = ClinVarRecord(
                chrom=chrom,
                pos=pos,
                ref=ref,
                alt=alt,
                gene=_first(norm, "gene", "gene_symbol", "genesymbol") or "unknown",
                condition=_first(norm, "condition", "disease", "phenotype", "trait", "condition_name") or "unspecified",
                clinical_significance=normalize_clinical_significance(_first(norm, "clinical_significance", "clin_sig", "significance")),
                review_status=_first(norm, "review_status", "review", "stars") or "not_provided",
                accession=_first(norm, "accession", "variationid", "vcv", "rcv") or None,
                inheritance=_first(norm, "inheritance", "mode_of_inheritance") or None,
                source_version=_first(norm, "source_version", "version", "date_last_evaluated") or None,
            )
            records.setdefault(variant_key(rec.chrom, rec.pos, rec.ref, rec.alt), []).append(rec)
    return records


def _review_rank(status: str) -> int:
    s = str(status or "").lower()
    if "practice_guideline" in s or "practice guideline" in s:
        return 4
    if "expert_panel" in s or "expert panel" in s:
        return 3
    if "multiple" in s or "2" in s or "two" in s:
        return 2
    if "criteria" in s or "single" in s or "1" in s:
        return 1
    return 0


def parse_annotation_tokens(raw: str | None) -> dict[str, str | None]:
    if not raw:
        return {"gene": None, "transcript": None, "impact": None, "consequence": None}
    first = str(raw).split(",", 1)[0]
    parts = first.split("|")
    if len(parts) >= 11:  # VEP CSQ common order: allele|consequence|impact|symbol|gene|feature_type|feature...
        return {"gene": parts[3] or None, "transcript": parts[6] or None, "impact": parts[2] or None, "consequence": parts[1] or None}
    if len(parts) >= 5:  # SnpEff ANN common order: allele|annotation|impact|gene|gene_id|feature_type|feature...
        return {"gene": parts[3] or None, "transcript": parts[6] if len(parts) > 6 else None, "impact": parts[2] or None, "consequence": parts[1] or None}
    return {"gene": None, "transcript": None, "impact": None, "consequence": first or None}


def annotation_summary(variants: list[Any], *, sample_id: str, run_id: str | None, genome_build: str | None) -> dict[str, Any]:
    annotated = []
    gene_counts: dict[str, int] = {}
    impact_counts: dict[str, int] = {}
    for v in variants:
        parsed = parse_annotation_tokens(getattr(v, "consequence", None))
        if not any(parsed.values()):
            continue
        gene = parsed.get("gene") or "unknown"
        impact = parsed.get("impact") or "unknown"
        gene_counts[gene] = gene_counts.get(gene, 0) + 1
        impact_counts[impact] = impact_counts.get(impact, 0) + 1
        annotated.append({
            "variant_id": getattr(v, "id", None),
            "chrom": getattr(v, "chrom", None),
            "pos": getattr(v, "pos", None),
            "ref": getattr(v, "ref", None),
            "alt": getattr(v, "alt", None),
            **parsed,
            "clinical_annotation": getattr(v, "clinical_annotation", None),
            "gnomad_freq": getattr(v, "gnomad_freq", None),
            "trust_score": getattr(v, "trust_score", None),
        })
    provenance = InterpretationProvenance(
        source_database="VCF ANN/CSQ imported annotation",
        source_version="parser-derived",
        genome_build=genome_build,
        rule_id="annotation_summary_from_imported_consequence_field",
        input_variant_count=len(variants),
        matched_variant_count=len(annotated),
        overlap_pct=round((len(annotated) / max(1, len(variants))) * 100.0, 3),
        confidence_level="moderate" if annotated else "insufficient",
        sample_id=sample_id,
        last_run_id=run_id,
    )
    if not annotated:
        provenance.warnings.append("No ANN/CSQ/BCSQ annotation fields imported; run VEP/SnpEff annotation before gene-level interpretation.")
    return {
        "status": "annotated" if annotated else "annotation_missing",
        "count": len(annotated),
        "items": annotated[:200],
        "top_genes": sorted(gene_counts.items(), key=lambda x: (-x[1], x[0]))[:25],
        "impact_counts": impact_counts,
        "provenance": provenance.model_dump(),
        "non_diagnostic": True,
    }


def _variant_technical_evidence(v: Any) -> dict[str, Any]:
    explainability = getattr(v, "explainability", None) or {}
    if not isinstance(explainability, dict):
        explainability = {}
    depth = explainability.get("depth")
    allele_balance = explainability.get("allele_balance")
    variant_quality = explainability.get("variant_quality")
    trust_score = getattr(v, "trust_score", None)
    genotype = getattr(v, "genotype", None)
    zygosity = getattr(v, "zygosity", None)
    if depth is None:
        local_status = "coverage_unknown"
        assessability = "not_assessable"
        warning = "Local depth/callability evidence is missing for this ClinVar hit."
    elif depth < 10:
        local_status = "low_depth"
        assessability = "limited"
        warning = "ClinVar hit is observed, but local read depth is low; confirm before interpretation."
    elif genotype in {None, "./.", ".|.", "."} or zygosity in {None, "no_call"}:
        local_status = "genotype_uncalled"
        assessability = "not_assessable"
        warning = "ClinVar hit matched by allele, but genotype/zygosity is missing or no-call."
    else:
        local_status = "variant_observed_with_depth"
        assessability = "variant_assessable"
        warning = None
    return {
        "genotype": genotype,
        "zygosity": zygosity,
        "local_depth": depth,
        "allele_balance": allele_balance,
        "variant_quality": variant_quality,
        "technical_trust_score": trust_score,
        "local_coverage_status": local_status,
        "assessability": assessability,
        "warning": warning,
    }


def classify_monogenic_variants(
    *,
    variants: list[Any],
    sample_id: str,
    run_id: str | None,
    genome_build: str | None,
    clinvar_path: Path | None = None,
    min_review_rank: int = 1,
    include_vus: bool = True,
    acmg_only: bool = False,
) -> dict[str, Any]:
    path = clinvar_path or find_clinvar_tsv()
    provenance = InterpretationProvenance(
        source_database="ClinVar",
        source_version=str(path.name) if path else None,
        source_date=today_version() if path else None,
        genome_build=genome_build,
        rule_id="clinvar_exact_chr_pos_ref_alt",
        input_variant_count=len(variants),
        sample_id=sample_id,
        last_run_id=run_id,
    )

    if not variants:
        provenance.warnings.append("No variants available for monogenic interpretation.")
        return {"status": "no_variants", "items": [], "count": 0, "provenance": provenance.model_dump(), "non_diagnostic": True}
    if not path:
        provenance.warnings.append("ClinVar exact-match TSV is not installed/configured.")
        return {
            "status": "not_configured",
            "items": [],
            "count": 0,
            "expected_paths": [str(p) for p in clinvar_path_candidates()],
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }

    index = parse_clinvar_tsv(path)
    items: list[dict[str, Any]] = []
    for v in variants:
        key = variant_key(getattr(v, "chrom"), getattr(v, "pos"), getattr(v, "ref"), getattr(v, "alt"))
        for rec in index.get(key, []):
            sig = rec.clinical_significance
            if _review_rank(rec.review_status) < min_review_rank:
                continue
            if acmg_only and rec.gene.upper() not in ACMG_SF_GENES:
                continue
            if sig in BENIGN_SIGS:
                continue
            if sig in VUS_SIGS and not include_vus:
                continue
            tier = "pathogenic_or_likely_pathogenic" if sig in PATHOGENIC_SIGS else "uncertain" if sig in VUS_SIGS else "conflicting" if sig == "conflicting" else "other"
            catalog_matches = match_monogenic_catalog(rec.condition, rec.gene)
            technical = _variant_technical_evidence(v)
            items.append({
                "variant_id": getattr(v, "id", None),
                "chrom": getattr(v, "chrom"),
                "pos": getattr(v, "pos"),
                "ref": getattr(v, "ref"),
                "alt": getattr(v, "alt"),
                "genotype": technical["genotype"],
                "zygosity": technical["zygosity"],
                "gene": rec.gene,
                "condition": rec.condition,
                "clinical_significance": sig,
                "review_status": rec.review_status,
                "accession": rec.accession,
                "inheritance": rec.inheritance,
                "tier": tier,
                "is_acmg_sf": rec.gene.upper() in ACMG_SF_GENES,
                "technical_trust_score": technical["technical_trust_score"],
                "technical_evidence": technical,
                "local_coverage_status": technical["local_coverage_status"],
                "assessability": technical["assessability"],
                "catalog_matches": catalog_matches,
                "catalog_match": catalog_matches[0] if catalog_matches else None,
                "warning": technical["warning"] or "Research-only; confirm clinically before action.",
            })

    provenance.matched_variant_count = len(items)
    provenance.overlap_pct = round((len(items) / max(1, len(variants))) * 100.0, 3)
    pathogenic_count = sum(1 for item in items if item["tier"] == "pathogenic_or_likely_pathogenic")
    uncertain_count = sum(1 for item in items if item["tier"] in {"uncertain", "conflicting"})
    other_count = max(0, len(items) - pathogenic_count - uncertain_count)
    not_assessable_count = sum(1 for item in items if item.get("assessability") == "not_assessable")
    limited_evidence_count = sum(1 for item in items if item.get("assessability") == "limited")

    condition_map: dict[str, dict[str, Any]] = {}
    for item in items:
        condition = item.get("condition") or "Unspecified condition"
        rec = condition_map.setdefault(condition, {
            "condition": condition,
            "genes": set(),
            "inheritance": set(),
            "highest_tier": item.get("tier") or "other",
            "variant_count": 0,
            "pathogenic_or_likely_pathogenic_count": 0,
            "uncertain_or_conflicting_count": 0,
            "accessions": set(),
            "items": [],
            "catalog_matches": [],
        })
        rec["variant_count"] += 1
        if item.get("gene"):
            rec["genes"].add(item["gene"])
        if item.get("inheritance"):
            rec["inheritance"].add(item["inheritance"])
        if item.get("accession"):
            rec["accessions"].add(item["accession"])
        if item.get("tier") == "pathogenic_or_likely_pathogenic":
            rec["pathogenic_or_likely_pathogenic_count"] += 1
            rec["highest_tier"] = "pathogenic_or_likely_pathogenic"
        elif item.get("tier") in {"uncertain", "conflicting"}:
            rec["uncertain_or_conflicting_count"] += 1
            if rec["highest_tier"] != "pathogenic_or_likely_pathogenic":
                rec["highest_tier"] = "uncertain_or_conflicting"
        for match in item.get("catalog_matches") or []:
            if not any(existing.get("id") == match.get("id") for existing in rec["catalog_matches"]):
                rec["catalog_matches"].append(match)
        rec["items"].append(item)

    conditions = []
    for rec in condition_map.values():
        rec["genes"] = sorted(rec["genes"])
        rec["inheritance"] = sorted(rec["inheritance"])
        rec["accessions"] = sorted(rec["accessions"])
        conditions.append(rec)
    conditions.sort(key=lambda rec: (
        0 if rec["highest_tier"] == "pathogenic_or_likely_pathogenic" else 1,
        -rec["variant_count"],
        rec["condition"],
    ))

    summary = {
        "condition_count": len(conditions),
        "pathogenic_or_likely_pathogenic_count": pathogenic_count,
        "uncertain_or_conflicting_count": uncertain_count,
        "other_count": other_count,
        "not_assessable_count": not_assessable_count,
        "limited_evidence_count": limited_evidence_count,
        "reviewed_variant_count": len(items),
        "catalog_version": MONOGENIC_CATALOG_VERSION,
        "catalog_matched_condition_count": sum(1 for rec in conditions if rec.get("catalog_matches")),
    }
    if not_assessable_count or limited_evidence_count:
        provenance.warnings.append(
            f"{not_assessable_count} ClinVar hit(s) missing local callability/genotype evidence; "
            f"{limited_evidence_count} have limited local evidence."
        )

    if pathogenic_count:
        status = "pathogenic_or_likely_pathogenic_found"
        provenance.confidence_level = "moderate"
    elif items:
        status = "vus_or_conflicting_only"
        provenance.confidence_level = "low"
    else:
        status = "no_reportable_findings"
        provenance.confidence_level = "insufficient"
        provenance.warnings.append("No reportable ClinVar matches found; this is not a negative clinical screen.")

    return {
        "status": status,
        "items": items,
        "conditions": conditions,
        "summary": summary,
        "count": len(items),
        "condition_count": len(conditions),
        "provenance": provenance.model_dump(),
        "non_diagnostic": True,
    }


def find_clinvar_vcf() -> Path | None:
    candidate = CLINVAR_VCF_DIR / "clinvar.vcf.gz"
    return candidate if candidate.exists() and candidate.is_file() else None


def clinvar_resource_pipeline_status() -> dict[str, Any]:
    tsv = find_clinvar_tsv()
    vcf = find_clinvar_vcf()
    tbi = CLINVAR_VCF_DIR / "clinvar.vcf.gz.tbi"
    return {
        "exact_match_tsv": str(tsv) if tsv else None,
        "vcf": str(vcf) if vcf else None,
        "vcf_index": str(tbi) if tbi.exists() else None,
        "ready_for_monogenic_exact_match": bool(tsv),
        "ready_for_vcf_annotation": bool(vcf and tbi.exists()),
        "install_endpoint": "/interpretation/resources/clinvar/install",
        "validate_endpoint": "/interpretation/resources/clinvar/validate",
        "non_diagnostic": True,
    }


def tool_status() -> dict[str, Any]:
    clinvar_pipeline = clinvar_resource_pipeline_status()
    haplogrep_available = (
        bool(shutil.which("haplogrep3") or shutil.which("haplogrep") or shutil.which("haplogrep2"))
        or Path("/opt/haplogrep/haplogrep.jar").exists()
    )
    return {
        "pharmcat": bool(shutil.which("pharmcat")) or Path("/opt/pharmcat/pharmcat.jar").exists(),
        "cyrius": bool(shutil.which("cyrius")),
        "stellarpgx": bool(shutil.which("StellarPGx") or shutil.which("stellarpgx")),
        "haplogrep": haplogrep_available,
        "vep": bool(shutil.which("vep")),
        "bcftools": bool(shutil.which("bcftools")),
        "clinvar_tsv": clinvar_pipeline["exact_match_tsv"],
        "clinvar_vcf": clinvar_pipeline["vcf"],
        "clinvar_vcf_index": clinvar_pipeline["vcf_index"],
        "clinvar_pipeline": clinvar_pipeline,
    }


# ---------------------------------------------------------------------------
# PharmCAT
# ---------------------------------------------------------------------------

PHARMCAT_INSTALL_DIR = Path(os.getenv("WGS_PHARMCAT_DIR", "/opt/pharmcat"))
PHARMCAT_JAR_NAME = "pharmcat.jar"
PHARMCAT_RELEASES_URL = "https://api.github.com/repos/pharmcat/pharmcat/releases/latest"


def _pharmcat_jar_path() -> Path:
    return PHARMCAT_INSTALL_DIR / PHARMCAT_JAR_NAME


def install_pharmcat(*, force: bool = False) -> dict[str, Any]:
    """Download the latest PharmCAT JAR from GitHub releases.

    Returns a provenance-wrapped result with install status.
    Research-only; not a diagnostic tool.
    """
    jar = _pharmcat_jar_path()
    provenance = InterpretationProvenance(
        source_database="PharmCAT/CPIC",
        source_version=None,
        genome_build=None,
        rule_id="pharmcat_installer",
    )

    if jar.exists() and not force:
        provenance.source_version = "already_installed"
        return {
            "status": "already_installed",
            "path": str(jar),
            "size_bytes": jar.stat().st_size,
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
            "warning": "PharmCAT is a research/pharmacogenomics tool; results are not diagnostic.",
        }

    PHARMCAT_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    try:
        # Discover latest release
        req = urllib.request.Request(
            PHARMCAT_RELEASES_URL,
            headers={"Accept": "application/json", "User-Agent": "wgs-cockpit"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            release = json.loads(resp.read())

        tag = release.get("tag_name", "unknown")
        provenance.source_version = tag

        # Find the JAR asset
        jar_asset = None
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".jar") and "pharmcat" in name.lower():
                jar_asset = asset
                break
        if not jar_asset:
            provenance.warnings.append("No JAR asset found in latest PharmCAT release.")
            return {
                "status": "error",
                "error": "no_jar_asset_found",
                "provenance": provenance.model_dump(),
                "non_diagnostic": True,
            }

        download_url = jar_asset["browser_download_url"]
        provenance.warnings.append(f"Downloading PharmCAT {tag} from GitHub.")

        # Download JAR
        urllib.request.urlretrieve(download_url, str(jar))  # nosec B310

        provenance.source_version = tag
        return {
            "status": "installed",
            "path": str(jar),
            "version": tag,
            "size_bytes": jar.stat().st_size,
            "download_url": download_url,
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
            "warning": "PharmCAT is a research/pharmacogenomics tool; results are not diagnostic.",
        }
    except Exception as exc:
        provenance.warnings.append(str(exc))
        return {
            "status": "error",
            "error": str(exc),
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }


def run_pharmcat(vcf_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Run PharmCAT on a VCF file.

    Requires Java 11+ and the PharmCAT JAR to be installed.
    Returns a provenance-wrapped PGx result.
    Research-only; not a diagnostic tool.
    """
    jar = _pharmcat_jar_path()
    vcf = Path(vcf_path)
    out = Path(output_dir)
    provenance = InterpretationProvenance(
        source_database="PharmCAT/CPIC",
        source_version="local_executable",
        rule_id="pharmcat_pgx_runner",
    )

    if not jar.exists():
        provenance.warnings.append("PharmCAT JAR not installed. Run install_pharmcat first.")
        return {
            "status": "not_installed",
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }

    if not vcf.exists():
        provenance.warnings.append(f"VCF not found: {vcf}")
        return {
            "status": "input_not_found",
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }

    out.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            ["java", "-jar", str(jar), "-vcf", str(vcf), "-o", str(out), "-json"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        provenance.warnings.extend([
            line for line in (result.stderr or "").splitlines() if line.strip()
        ][:10])

        # Find PharmCAT JSON output
        json_files = list(out.glob("*.json"))
        pgx_report = {}
        if json_files:
            report_path = max(json_files, key=lambda p: p.stat().st_mtime)
            try:
                pgx_report = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        return {
            "status": "completed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "output_dir": str(out),
            "report": pgx_report,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
            "warning": "PharmCAT PGx results are research-only; confirm with clinical pharmacist before medication changes.",
        }
    except subprocess.TimeoutExpired:
        provenance.warnings.append("PharmCAT execution timed out (300s).")
        return {
            "status": "timeout",
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }
    except Exception as exc:
        provenance.warnings.append(str(exc))
        return {
            "status": "error",
            "error": str(exc),
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }


# ---------------------------------------------------------------------------
# HaploGrep
# ---------------------------------------------------------------------------

HAPLOGREP_INSTALL_DIR = Path(os.getenv("WGS_HAPLOGREP_DIR", "/opt/haplogrep"))
HAPLOGREP_JAR_NAME = "haplogrep.jar"
HAPLOGREP_RELEASES_URL = "https://api.github.com/repos/genepi/haplogrep3/releases/latest"


def _haplogrep_jar_path() -> Path:
    return HAPLOGREP_INSTALL_DIR / HAPLOGREP_JAR_NAME


def _haplogrep_executable() -> str | None:
    return shutil.which("haplogrep3") or shutil.which("haplogrep") or shutil.which("haplogrep2")


def _haplogrep_command(vcf: Path, out_file: Path) -> tuple[list[str] | None, str | None]:
    tree = os.getenv("WGS_HAPLOGREP_TREE", "").strip()
    exe = _haplogrep_executable()
    if exe:
        name = Path(exe).name.lower()
        if name == "haplogrep3":
            cmd = [exe, "classify", "--in", str(vcf), "--out", str(out_file)]
        else:
            cmd = [exe, "--in", str(vcf), "--out", str(out_file)]
        if tree:
            cmd.extend(["--tree", tree])
        return cmd, exe

    jar = _haplogrep_jar_path()
    if jar.exists():
        cmd = ["java", "-jar", str(jar), "classify", "--in", str(vcf), "--out", str(out_file)]
        if tree:
            cmd.extend(["--tree", tree])
        return cmd, str(jar)
    return None, None


def install_haplogrep(*, force: bool = False) -> dict[str, Any]:
    """Download the latest HaploGrep3 JAR from GitHub releases.

    Returns a provenance-wrapped result with install status.
    Research-only; not a diagnostic tool.
    """
    jar = _haplogrep_jar_path()
    provenance = InterpretationProvenance(
        source_database="HaploGrep/PhyloTree",
        source_version=None,
        genome_build=None,
        rule_id="haplogrep_installer",
    )

    if jar.exists() and not force:
        provenance.source_version = "already_installed"
        return {
            "status": "already_installed",
            "path": str(jar),
            "size_bytes": jar.stat().st_size,
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }

    HAPLOGREP_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    try:
        req = urllib.request.Request(
            HAPLOGREP_RELEASES_URL,
            headers={"Accept": "application/json", "User-Agent": "wgs-cockpit"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            release = json.loads(resp.read())

        tag = release.get("tag_name", "unknown")
        provenance.source_version = tag

        jar_asset = None
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".jar"):
                jar_asset = asset
                break
        if not jar_asset:
            provenance.warnings.append("No JAR asset found in latest HaploGrep release.")
            return {
                "status": "error",
                "error": "no_jar_asset_found",
                "provenance": provenance.model_dump(),
                "non_diagnostic": True,
            }

        download_url = jar_asset["browser_download_url"]
        urllib.request.urlretrieve(download_url, str(jar))  # nosec B310

        provenance.source_version = tag
        return {
            "status": "installed",
            "path": str(jar),
            "version": tag,
            "size_bytes": jar.stat().st_size,
            "download_url": download_url,
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }
    except Exception as exc:
        provenance.warnings.append(str(exc))
        return {
            "status": "error",
            "error": str(exc),
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }


def run_haplogrep(vcf_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Run HaploGrep3 on a VCF file for mtDNA haplogroup classification.

    Requires a HaploGrep CLI binary or Java 11+ with the HaploGrep JAR.
    Returns a provenance-wrapped haplogroup result.
    Research-only; not a diagnostic tool.
    """
    vcf = Path(vcf_path)
    out = Path(output_dir)
    provenance = InterpretationProvenance(
        source_database="HaploGrep/PhyloTree",
        source_version="local_executable",
        rule_id="haplogrep_runner",
    )

    if not vcf.exists():
        provenance.warnings.append(f"VCF not found: {vcf}")
        return {
            "status": "input_not_found",
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }

    out.mkdir(parents=True, exist_ok=True)
    out_file = out / f"{vcf.stem}.haplogroups.txt"
    cmd, command_source = _haplogrep_command(vcf, out_file)
    if not cmd:
        provenance.warnings.append("HaploGrep executable/JAR not installed. Run install_haplogrep first.")
        return {
            "status": "not_installed",
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        haplogroups: list[dict[str, Any]] = []
        if out_file.exists():
            haplogroups = parse_haplogrep_output(out_file)

        provenance.matched_variant_count = len(haplogroups)
        provenance.confidence_level = "moderate" if haplogroups else "insufficient"

        return {
            "status": "completed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "input_vcf_path": str(vcf),
            "output_dir": str(out),
            "output_path": str(out_file),
            "command_source": command_source,
            "haplogroups": haplogroups,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
            "warning": "mtDNA haplogroup results are for ancestry/informational purposes; not clinical.",
        }
    except subprocess.TimeoutExpired:
        provenance.warnings.append("HaploGrep execution timed out (300s).")
        return {
            "status": "timeout",
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }
    except Exception as exc:
        provenance.warnings.append(str(exc))
        return {
            "status": "error",
            "error": str(exc),
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }


def parse_haplogrep_output(path: Path) -> list[dict[str, Any]]:
    """Parse HaploGrep3 text output into structured haplogroup records."""
    results: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        header: list[str] | None = None
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            delimiter = "\t" if "\t" in line else ","
            parts = next(csv.reader([line], delimiter=delimiter))
            norm = [_norm_name(p) for p in parts]
            if "haplogroup" in norm and any(p in norm for p in {"quality", "quality_score"}):
                header = norm
                continue

            if header:
                row = {header[idx]: value.strip() for idx, value in enumerate(parts) if idx < len(header)}
                haplogroup = _first(row, "haplogroup", "haplogroup_rank")
                quality = _first(row, "quality", "quality_score", "score")
                sample_id = _first(row, "sample_id", "sampleid", "sample", "name")
                if haplogroup:
                    results.append({
                        "sample_id": sample_id,
                        "haplogroup": haplogroup,
                        "quality_score": float(quality) if _is_float(quality) else None,
                        "n_count": _first(row, "n", "n_count", "no_of_ns", "no._of_ns") or None,
                        "covered_positions": _first(row, "covered_positions", "coverage") or None,
                        "range": _first(row, "range") or None,
                        "input_mutations": _first(row, "input_mutations", "input_sample") or None,
                    })
                continue

            if len(parts) >= 3:
                results.append({
                    "sample_id": parts[0],
                    "haplogroup": parts[1],
                    "quality_score": float(parts[2]) if _is_float(parts[2]) else None,
                    "n_count": parts[3] if len(parts) > 3 else None,
                    "covered_positions": parts[4] if len(parts) > 4 else None,
                    "range": parts[5] if len(parts) > 5 else None,
                    "input_mutations": parts[6] if len(parts) > 6 else None,
                    "remaining_parts": parts[7:] if len(parts) > 7 else [],
                })
    except Exception:
        pass
    return results


def _parse_haplogrep_output(path: Path) -> list[dict[str, Any]]:
    return parse_haplogrep_output(path)


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# ClinVar VCF Download
# ---------------------------------------------------------------------------

CLINVAR_VCF_URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz"
CLINVAR_VCF_TBI_URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz.tbi"
CLINVAR_VCF_DIR = Path(os.getenv("WGS_CLINVAR_VCF_DIR", "/data/references/clinvar"))


def install_clinvar_vcf(*, force: bool = False) -> dict[str, Any]:
    """Download ClinVar VCF from NCBI FTP.

    Downloads the GRCh38 ClinVar VCF and its tabix index.
    Returns a provenance-wrapped result.
    Research-only; not a diagnostic tool.
    """
    dest_vcf = CLINVAR_VCF_DIR / "clinvar.vcf.gz"
    dest_tbi = CLINVAR_VCF_DIR / "clinvar.vcf.gz.tbi"
    provenance = InterpretationProvenance(
        source_database="ClinVar",
        source_version="latest",
        source_date=today_version(),
        genome_build="GRCh38",
        rule_id="clinvar_vcf_installer",
    )

    if dest_vcf.exists() and not force:
        provenance.source_version = "already_installed"
        return {
            "status": "already_installed",
            "path": str(dest_vcf),
            "size_bytes": dest_vcf.stat().st_size,
            "index_exists": dest_tbi.exists(),
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }

    CLINVAR_VCF_DIR.mkdir(parents=True, exist_ok=True)

    try:
        provenance.warnings.append("Downloading ClinVar VCF from NCBI FTP. This may take several minutes.")
        urllib.request.urlretrieve(CLINVAR_VCF_URL, str(dest_vcf))  # nosec B310
        urllib.request.urlretrieve(CLINVAR_VCF_TBI_URL, str(dest_tbi))  # nosec B310

        return {
            "status": "installed",
            "path": str(dest_vcf),
            "size_bytes": dest_vcf.stat().st_size,
            "index_path": str(dest_tbi),
            "index_exists": dest_tbi.exists(),
            "download_url": CLINVAR_VCF_URL,
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
            "warning": "ClinVar VCF is a research/annotation resource; confirm variants clinically before action.",
        }
    except Exception as exc:
        provenance.warnings.append(str(exc))
        return {
            "status": "error",
            "error": str(exc),
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }
