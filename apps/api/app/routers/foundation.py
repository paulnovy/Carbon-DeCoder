import json
import hashlib
import os
import signal
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import re
from uuid import uuid4

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import String as SqlString, cast, func, or_
from sqlalchemy.exc import SQLAlchemyError

from app.core.qc_parser import build_qc_summary
from app.core.alignment_parser import parse_flagstat_text, parse_idxstats_text
from app.core.coverage_parser import parse_mosdepth_summary_txt, summarize_mosdepth_regions_thresholds
from app.core.coverage_tiles_parser import build_tiles_from_regions, parse_mosdepth_regions
from app.core.reference_masks import (
    annotate_coverage_interpretation_tracks,
    annotate_reference_masks,
    summarize_coverage_interpretation_tracks,
    summarize_reference_masks,
)
from app.core.stage_runner import (
    build_stage_command,
    find_stage_script,
    sanitize_stage_script,
    stage_script_name as core_stage_script_name,
    variant_calling_backend as core_variant_calling_backend,
)
from app.core.sv_parser import parse_sv_vcf
from app.core.cnv_parser import parse_cnv_segments_tsv, parse_cnv_vcf
from app.core.taxonomy_parser import enrich_taxonomy_hits_with_lineage, parse_taxonomy_report
from app.core.mtdna_parser import parse_mtdna_report
from app.core.prs_parser import parse_prs_result
from app.core.prs_catalog import download_pgs_score, calculate_prs, list_downloaded_scores
from app.core.pgs_catalog import curated_manifest_status, category_counts as pgs_category_counts, draft_manifest_from_downloaded_scores, draft_manifest_tsv, load_curated_pgs_manifest, pgs_storage_estimate, recommended_pgs_from_downloaded, search_curated_pgs, validate_curated_pgs_manifest
from app.core.pgx_rules import evaluate_pgx_rules, validate_pgx_rules_manifest
from app.core.benchmark_parser import parse_benchmark_report
from app.core.vendor_validation_parser import parse_vendor_validation_report
from app.core.vendor_comparator import compare_vendor_assemblies, compare_vendor_vcfs
from app.core.fastq_assembly import build_stub_assembly_from_fastq
from app.core.fastq_read_estimator import estimate_fastq_input_reads
from app.core.variant_parser import parse_variants_vcf
from app.core.traits_engine import evaluate_traits, validate_traits_manifest
from app.core.interpretation import (
    ACMG_SF_GENES,
    ACMG_SF_VERSION,
    annotation_summary,
    classify_monogenic_variants,
    interpretation_resource_registry,
    resources_by_module,
    validate_clinvar_tsv,
    tool_status as interpretation_tool_status,
    validate_build,
    install_pharmcat,
    run_pharmcat,
    install_haplogrep,
    run_haplogrep,
    install_clinvar_vcf,
    clinvar_resource_pipeline_status,
)
from app.core.clinvar_pipeline import build_clinvar_tsv_from_vcf
from app.core.report_writer import write_report_artifacts, write_report_bundle_manifest, write_report_bundle_index_html
from app.core.trust import compute_trust_score, trust_label, trust_score_100
from app.pipeline_contract import PipelineJob, encode_pipeline_job, pipeline_job_runner_args
from app.pipeline_process import communicate_stage_process
from app.version import APP_SERVICE, APP_VERSION
from app.db.database import get_schema_status
from app.db.database import SessionLocal
from app.db import sql_models as sm
from app.db.models import (
    AlignmentMetrics,
    BenchmarkRecord,
    CNVSegment,
    CoverageMetrics,
    InterpretationResult,
    MtDNAResult,
    PRSResult,
    Project,
    ReferenceGenome,
    ReportArtifact,
    Run,
    RunEvent,
    RunLogLine,
    RunStep,
    Sample,
    StructuralVariant,
    TaxonomyHit,
    VariantCall,
    VendorAssemblyValidation,
)
from app.store.memory_store import (
    add_benchmark_record,
    add_benchmark_records,
    add_cnv_segments,
    add_interpretation_results,
    add_mtdna_hit,
    add_mtdna_hits,
    add_prs_result,
    add_prs_results,
    add_project,
    add_reference,
    add_report,
    add_run,
    add_run_event,
    add_run_log_line,
    add_run_step,
    add_sample,
    add_structural_variants,
    add_taxonomy_hit,
    add_taxonomy_hits,
    add_variants,
    add_vendor_assembly_validation,
    add_vendor_assembly_validations,
    alignment_metrics,
    benchmark_records,
    coverage_metrics,
    cnv_segments,
    delete_alignment_metrics_by_sample_ids,
    delete_cnv_segments_by_run,
    delete_cnv_segments_by_sample_ids,
    delete_coverage_metrics_by_sample_ids,
    delete_interpretation_results_by_run,
    delete_interpretation_results_by_run_ids,
    delete_interpretation_results_by_sample_ids,
    delete_mtdna_hits_by_run,
    delete_mtdna_hits_by_sample_ids,
    delete_prs_results_by_run,
    delete_prs_results_by_sample_ids,
    remove_project,
    delete_run_events_by_run,
    delete_run_events_by_run_ids,
    delete_run_logs_by_run,
    delete_run_logs_by_run_ids,
    delete_run_steps_by_run,
    delete_run_steps_by_run_ids,
    delete_runs_by_project,
    delete_samples_by_project,
    delete_structural_variants_by_run,
    delete_structural_variants_by_sample_ids,
    delete_taxonomy_hits_by_run,
    delete_taxonomy_hits_by_sample_ids,
    delete_variants_by_run,
    delete_variants_by_sample_ids,
    delete_qc_summaries_by_run,
    delete_coverage_metrics_by_run,
    delete_alignment_metrics_by_run,
    delete_reports_by_run,
    delete_reports_by_run_ids,
    delete_qc_summaries_by_run_ids,
    delete_coverage_metrics_by_run_ids,
    delete_alignment_metrics_by_run_ids,
    mtdna_results,
    prs_results,
    projects,
    qc_summaries,
    references,
    interpretation_results,
    remove_reference,
    remove_run,
    refresh_from_db,
    save_reference,
    save_project,
    save_run,
    save_run_step,
    replace_alignment_metric_for_run,
    replace_coverage_metric_for_run,
    replace_qc_summary_for_run,
    reports,
    run_events,
    run_logs,
    run_steps,
    runs,
    samples,
    structural_variants,
    taxonomy_hits,
    variants,
    vendor_assembly_validations,
)

router = APIRouter()
BUILTIN_REFERENCE_IDS = {r.id for r in references}
REFERENCE_STORAGE_DIR = Path(os.getenv("WGS_REFERENCE_DIR", "/data/references"))

# Per-run cancel flags: checked by _run_pipeline_background between stages
_CANCEL_FLAGS: dict[str, bool] = {}
# Per-run pause flags: checked by _run_pipeline_background between stages
_PAUSE_FLAGS: dict[str, bool] = {}
# Per-run operator skip flags: checked by _run_pipeline_background before each stage
_STAGE_SKIP_FLAGS: dict[str, set[str]] = {}
# Per-run active subprocess: used by cancel to kill running stage
_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}
# Per-run active API-thread runner. This is separate from _ACTIVE_PROCESSES
# because a runner can be parked safely between stages with no child process.
_ACTIVE_RUNNERS: dict[str, bool] = {}

PAUSE_MODE_ACTIVE_PROCESS = "active_process"
PAUSE_MODE_STAGE_BOUNDARY = "stage_boundary"
PAUSE_STATE_KEYS = {
    "pause_previous_status",
    "pause_reason",
    "pause_mode",
    "pause_requested_at",
    "pause_requested_at_stage_boundary",
    "pause_requested_by",
    "pause_next_stage",
}
STAGE_BOUNDARY_PAUSE_REASONS = {"stage_boundary_pause", "disk_pressure_before_markdup"}

STAGE_TIMEOUTS = {
    "alignment": int(os.getenv("PIPELINE_ALIGNMENT_TIMEOUT_SECONDS", "604800")),
    "coverage": int(os.getenv("PIPELINE_COVERAGE_TIMEOUT_SECONDS", "7200")),
    "variants": int(os.getenv("PIPELINE_VARIANTS_TIMEOUT_SECONDS", "14400")),
    "sv": int(os.getenv("PIPELINE_SV_TIMEOUT_SECONDS", "14400")),
    "cnv": int(os.getenv("PIPELINE_CNV_TIMEOUT_SECONDS", "7200")),
    "mtdna": int(os.getenv("PIPELINE_MTDNA_TIMEOUT_SECONDS", "7200")),
    "taxonomy": int(os.getenv("PIPELINE_TAXONOMY_TIMEOUT_SECONDS", "86400")),
    "prs": int(os.getenv("PIPELINE_PRS_TIMEOUT_SECONDS", "7200")),
}


def _run_status_for_control(run_id: str | None) -> str | None:
    if not run_id:
        return None
    refresh_from_db(recover_stale_running=False)
    run = next((r for r in runs if r.id == run_id), None)
    return run.status if run else None


def _communicate_stage_process(
    proc: subprocess.Popen,
    *,
    run_id: str | None,
    stage_name: str,
    timeout_seconds: int,
) -> tuple[str, str]:
    return communicate_stage_process(
        proc,
        run_id=run_id,
        stage_name=stage_name,
        timeout_seconds=timeout_seconds,
        status_for_run=_run_status_for_control,
        pause_requested=lambda rid: bool(_PAUSE_FLAGS.get(rid)),
        cancel_requested=lambda rid: bool(_CANCEL_FLAGS.get(rid)),
        emit_event=_emit_run_event,
    )


def _normalize_pause_mode(mode: str | None) -> str:
    normalized = (mode or PAUSE_MODE_ACTIVE_PROCESS).strip().lower().replace("-", "_")
    aliases = {
        "checkpoint": PAUSE_MODE_STAGE_BOUNDARY,
        "between_stages": PAUSE_MODE_STAGE_BOUNDARY,
        "stage_end": PAUSE_MODE_STAGE_BOUNDARY,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {PAUSE_MODE_ACTIVE_PROCESS, PAUSE_MODE_STAGE_BOUNDARY}:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_pause_mode",
                "message": "Pause mode must be active_process or stage_boundary.",
                "supported_modes": [PAUSE_MODE_ACTIVE_PROCESS, PAUSE_MODE_STAGE_BOUNDARY],
            },
        )
    return normalized


def _clear_pause_state(params: dict | None) -> dict:
    return {k: v for k, v in (params or {}).items() if k not in PAUSE_STATE_KEYS}


def _stage_boundary_pause_requested(run: Run | None) -> bool:
    params = run.parameters if run and isinstance(run.parameters, dict) else {}
    return bool(params.get("pause_requested_at_stage_boundary"))


def _is_stage_boundary_pause(params: dict | None) -> bool:
    params = params or {}
    return (
        params.get("pause_mode") == PAUSE_MODE_STAGE_BOUNDARY
        or params.get("pause_reason") in STAGE_BOUNDARY_PAUSE_REASONS
    )


class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class SampleCreateRequest(BaseModel):
    sample_id: str
    reference_id: str
    r1_path: str | None = None
    r2_path: str | None = None


class RunCreateRequest(BaseModel):
    sample_id: str
    reference_id: str
    contig_style: str | None = None


class ReferenceActionRequest(BaseModel):
    reference_id: str


class PauseRunRequest(BaseModel):
    mode: str = Field(
        default=PAUSE_MODE_ACTIVE_PROCESS,
        description="active_process sends SIGSTOP immediately; stage_boundary waits for the current stage to finish before pausing.",
    )


class QcImportRequest(BaseModel):
    fastqc_data_txt: str | None = None
    multiqc_json: str | None = None


class AlignmentImportRequest(BaseModel):
    flagstat_txt: str | None = None
    idxstats_txt: str | None = None
    mapped_reads_pct: float | None = None
    properly_paired_pct: float | None = None
    duplicates_pct: float | None = None
    mapped_contigs: int | None = None
    unmapped_reads: int | None = None
    insert_size_median: float | None = None
    insert_size_mad: float | None = None
    source_files: list[str] = Field(default_factory=list)


class CoverageImportRequest(BaseModel):
    mosdepth_summary_txt: str | None = None
    mosdepth_regions_bed_gz: str | None = None
    mean_coverage: float | None = None
    median_coverage: float | None = None
    callable_fraction: float | None = None
    coverage_ge_10x: float | None = None
    coverage_ge_20x: float | None = None
    coverage_ge_30x: float | None = None
    source_files: list[str] = Field(default_factory=list)


class VariantImportItem(BaseModel):
    chrom: str
    pos: int
    ref: str
    alt: str
    variant_type: str = "SNV"
    caller_list: list[str] = Field(default_factory=list)
    caller_agreement_score: float = 0.0
    trust_score: float | None = None
    genotype: str | None = None
    zygosity: str | None = None
    explainability: dict[str, float] = Field(default_factory=dict)
    clinical_annotation: str | None = None
    gnomad_freq: float | None = None
    consequence: str | None = None


class VariantsImportRequest(BaseModel):
    variants: list[VariantImportItem] = Field(default_factory=list)
    variants_vcf_path: str | None = None
    replace_existing_for_run: bool = True


class SVImportItem(BaseModel):
    chrom: str
    start: int
    end: int
    sv_type: str
    size_bp: int
    evidence_types: list[str] = Field(default_factory=list)
    caller_list: list[str] = Field(default_factory=list)
    trust_score: float | None = None


class SVImportRequest(BaseModel):
    sv: list[SVImportItem] = Field(default_factory=list)
    sv_vcf_path: str | None = None
    replace_existing_for_run: bool = True


class CNVImportItem(BaseModel):
    chrom: str
    start: int
    end: int
    copy_number: float
    cnv_type: str
    method: str
    trust_score: float | None = None


class CNVImportRequest(BaseModel):
    segments: list[CNVImportItem] = Field(default_factory=list)
    cnv_segments_tsv_path: str | None = None
    cnv_vcf_path: str | None = None
    replace_existing_for_run: bool = True


class MtDNAImportRequest(BaseModel):
    haplogroup: str | None = None
    heteroplasmy_mean_vaf: float | None = None
    num_variants: int = 0
    numts_warning: bool = False
    trust_score: float | None = None
    mtdna_vcf_path: str | None = None
    mtdna_report_path: str | None = None
    replace_existing_for_run: bool = True


def _infer_numts_warning(
    *,
    explicit_warning: bool,
    heteroplasmy_mean_vaf: float | None,
    num_variants: int,
    trust_score: float,
) -> bool:
    if explicit_warning:
        return True
    if trust_score < 45.0 and num_variants >= 1:
        return True
    if heteroplasmy_mean_vaf is not None:
        if 0.0 < heteroplasmy_mean_vaf < 0.05 and num_variants >= 10:
            return True
        if 0.0 < heteroplasmy_mean_vaf < 0.15 and num_variants >= 30:
            return True
    return False


def _mtdna_warning_reasons(item: MtDNAResult) -> list[str]:
    reasons: list[str] = []
    if item.numts_warning:
        reasons.append("Potential NUMTs / nuclear mitochondrial insertion artifact signal.")
    if item.trust_score < 45.0:
        reasons.append("Low mtDNA technical trust score.")
    if item.heteroplasmy_mean_vaf is not None:
        if 0.0 < item.heteroplasmy_mean_vaf < 0.05 and item.num_variants >= 10:
            reasons.append("Many low-VAF mtDNA-like calls; check contamination/NUMTs before interpretation.")
        elif 0.0 < item.heteroplasmy_mean_vaf < 0.15 and item.num_variants >= 30:
            reasons.append("Broad low-to-moderate heteroplasmy pattern; review NUMTs/contamination evidence.")
    return reasons


class PRSImportRequest(BaseModel):
    trait: str | None = None
    score_value: float | None = None
    overlap_pct: float | None = None
    variant_count_total: int | None = None
    variant_count_matched: int | None = None
    quality_label: str = "unknown"
    warning: str | None = None
    non_diagnostic: bool = True
    prs_result_path: str | None = None
    replace_existing_for_run: bool = True


class PRSCatalogDownloadRequest(BaseModel):
    pgs_id: str


class PRSCatalogDownloadAllRequest(BaseModel):
    limit: int = 200  # development default; explicit 0 = all discoverable scores
    retry_count: int = 3
    force: bool = False


class PRSCalculateRequest(BaseModel):
    sample_id: str
    pgs_ids: list[str] = Field(default_factory=list)
    run_id: str | None = None


class PRSPanelRunRequest(BaseModel):
    sample_id: str
    limit: int = 300
    run_id: str | None = None
    min_mean_coverage: float = 20.0
    min_callable_fraction: float = 0.8
    min_match_rate: float = 0.0
    panel: str = "curated"


class TaxonomyImportHit(BaseModel):
    organism: str
    kingdom: str
    rank: str | None = None
    taxid: str | None = None
    lineage: list[dict] = Field(default_factory=list)
    top_clade: str | None = None
    read_count: int
    confidence: float
    evidence_score: float
    tools: list[str] = Field(default_factory=list)
    likely_contaminant: bool = False
    warning: str | None = None
    breadth_fraction: float | None = None
    coverage_depth: float | None = None
    genome_covered_bp: int | None = None
    genome_length_bp: int | None = None
    coverage_method: str | None = None


class TaxonomyImportRequest(BaseModel):
    hits: list[TaxonomyImportHit] = Field(default_factory=list)
    taxonomy_report_path: str | None = None
    replace_existing_for_run: bool = True
    taxonomy_mode: str | None = None
    taxonomy_input_mode: str | None = None
    taxonomy_input_r1: str | None = None
    taxonomy_input_r2: str | None = None
    host_bam: str | None = None
    host_unmapped_records: int | str | None = None
    taxonomy_database: str | None = None
    taxonomy_refinement: str | None = None
    taxonomy_refinement_status: str | None = None
    kraken_report_path: str | None = None
    bracken_report_path: str | None = None
    bracken_level: str | None = None
    bracken_read_length: int | str | None = None
    taxonomy_route: str | None = None
    taxonomy_analysis_id: str | None = None
    taxonomy_analysis_version: str | None = None
    taxonomy_extraction_params: dict = Field(default_factory=dict)
    taxonomy_database_version: str | None = None
    host_reference: str | None = None


class TaxonomyRecoverRequest(TaxonomyImportRequest):
    run_id: str | None = None
    parent_run_id: str | None = None


class UnknownReadsImportRequest(BaseModel):
    status: str = "imported"
    host_depletion: dict = Field(default_factory=dict)
    taxonomy_depletion: dict = Field(default_factory=dict)
    assembly: dict = Field(default_factory=dict)
    contig_search: dict = Field(default_factory=dict)
    kmer_profile: dict = Field(default_factory=dict)
    kmer_clusters: list[dict] = Field(default_factory=list)
    files: dict = Field(default_factory=dict)
    source_files: list[str] = Field(default_factory=list)
    collection_mode: str | None = None
    host_bam: str | None = None
    taxonomy_database: str | None = None
    notes: list[str] = Field(default_factory=list)
    non_diagnostic: bool = True


def _normalize_taxonomy_fraction(value: float | int | str | None) -> float | None:
    if value in (None, "", "."):
        return None
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return None
    if fraction > 1.0 and fraction <= 100.0:
        fraction = fraction / 100.0
    return round(max(0.0, min(1.0, fraction)), 6)


def _normalize_taxonomy_float(value: float | int | str | None) -> float | None:
    if value in (None, "", "."):
        return None
    try:
        return round(max(0.0, float(value)), 6)
    except (TypeError, ValueError):
        return None


def _normalize_taxonomy_int(value: int | float | str | None) -> int | None:
    if value in (None, "", "."):
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


INGEST_STAGE_STEPS = {
    "qc": {"fastqc_pre", "fastp_optional", "fastqc_post", "multiqc"},
    "alignment": {"alignment", "sorting", "mark_duplicates"},
    "coverage": {"coverage"},
    "variants": {"variants", "variant_calling"},
    "annotation": {"annotation", "variant_annotation"},
    "sv": {"sv", "sv_calling"},
    "cnv": {"cnv", "cnv_calling"},
    "mtdna": {"mtdna", "mtdna_calling"},
    "prs": {"prs", "prs_scoring"},
    "taxonomy": {"taxonomy", "taxonomy_classification"},
    "unknown_reads": {"unknown_reads", "unknown_reads_analysis"},
    "benchmark": {"benchmark"},
    "vendor_validation": {"vendor_validation"},
}


def _planned_pipeline_stages(run: Run) -> list[str]:
    params = run.parameters or {}
    stage_plan = params.get("stage_plan") if isinstance(params.get("stage_plan"), dict) else {}
    stages = stage_plan.get("final_stages") or params.get("stages") or []
    return [str(stage).strip().lower() for stage in stages if str(stage).strip()]


def _planned_run_terminal_status(run: Run) -> str | None:
    planned = _planned_pipeline_stages(run)
    if not planned:
        return None

    planned_statuses: list[str] = []
    for planned_stage in planned:
        step_names = INGEST_STAGE_STEPS.get(planned_stage, {planned_stage})
        statuses = [
            step.status
            for step in run_steps
            if step.run_id == run.id and step.step_name in step_names
        ]
        if not statuses:
            return None
        # Direct ingest/replay can coexist with older queued/running scaffold
        # steps from a previous full run. A successful imported step is the
        # authoritative terminal signal for this planned replay stage.
        if "done" in statuses:
            planned_statuses.append("done")
        elif any(status in {"failed", "blocked", "cancelled"} for status in statuses):
            planned_statuses.append(next(status for status in statuses if status in {"failed", "blocked", "cancelled"}))
        elif statuses and all(status == "skipped" for status in statuses):
            planned_statuses.append("skipped")
        else:
            return None

    failed = any(status in {"failed", "blocked", "cancelled"} for status in planned_statuses)
    return "failed" if failed else "done"


def _repair_planned_run_status(run: Run) -> Run:
    terminal_status = _planned_run_terminal_status(run)
    if terminal_status and run.status in {"queued", "running", "interrupted"} and run.status != terminal_status:
        run.status = terminal_status
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
    return run


def _mark_ingested_stage_done(run_id: str, stage: str, last_log: str | None = None) -> None:
    """Persist step completion for direct ingest and recover single-stage replays."""
    names = INGEST_STAGE_STEPS.get(stage, {stage})
    matched = False
    for step in run_steps:
        if step.run_id == run_id and step.step_name in names:
            matched = True
            step.status = "done"
            step.progress_pct = 100.0
            step.last_log = last_log or f"{stage} ingested"
            step.error = None
            step.updated_at = datetime.now(timezone.utc).isoformat()
            save_run_step(step)
    if not matched:
        _add_run_step(run_id, stage, "done", 100, last_log=last_log or f"{stage} ingested")

    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        return
    _repair_planned_run_status(run)


def _taxonomy_coverage_profile(hit: TaxonomyHit) -> dict:
    breadth = _normalize_taxonomy_fraction(getattr(hit, "breadth_fraction", None))
    depth = _normalize_taxonomy_float(getattr(hit, "coverage_depth", None))
    covered_bp = _normalize_taxonomy_int(getattr(hit, "genome_covered_bp", None))
    genome_bp = _normalize_taxonomy_int(getattr(hit, "genome_length_bp", None))
    if breadth is None and covered_bp is not None and genome_bp:
        breadth = _normalize_taxonomy_fraction(covered_bp / genome_bp)

    coverage_available = any(x is not None for x in (breadth, depth, covered_bp, genome_bp))
    warnings: list[str] = []
    if not coverage_available:
        support_level = "read_count_only"
        warnings.append("Coverage/breadth unavailable; classify from read count and taxonomy confidence only.")
    elif breadth is not None and breadth < 0.001:
        support_level = "trace_breadth"
        warnings.append("Very low genome breadth; contamination/index hopping/artifact remains plausible.")
    elif breadth is not None and breadth < 0.01:
        support_level = "low_breadth"
        warnings.append("Low genome breadth; do not infer robust organism presence without manual review.")
    elif depth is not None and depth < 1.0:
        support_level = "limited_depth"
        warnings.append("Coverage depth below 1x; evidence is limited.")
    elif (breadth is not None and breadth >= 0.2) and (depth is None or depth >= 3.0):
        support_level = "broad_support"
    else:
        support_level = "some_breadth_support"

    if hit.likely_contaminant:
        warnings.append("Marked as likely contaminant by taxonomy pipeline/import.")
    if hit.warning:
        warnings.append(hit.warning)

    return {
        "organism": hit.organism,
        "read_count": hit.read_count,
        "coverage_available": coverage_available,
        "support_level": support_level,
        "breadth_fraction": breadth,
        "breadth_pct": round(breadth * 100.0, 4) if breadth is not None else None,
        "coverage_depth": depth,
        "genome_covered_bp": covered_bp,
        "genome_length_bp": genome_bp,
        "coverage_method": getattr(hit, "coverage_method", None),
        "warnings": warnings,
    }


def _taxonomy_coverage_summary(items: list[TaxonomyHit]) -> dict:
    profiles = [_taxonomy_coverage_profile(item) for item in items]
    support_counts: dict[str, int] = {}
    for profile in profiles:
        key = str(profile.get("support_level") or "unknown")
        support_counts[key] = support_counts.get(key, 0) + 1
    return {
        "available_count": len([p for p in profiles if p["coverage_available"]]),
        "read_count_only_count": len([p for p in profiles if not p["coverage_available"]]),
        "support_counts": support_counts,
        "top_profiles": profiles[:10],
        "method": "imported_taxonomy_coverage_fields_or_derived_genome_covered_fraction",
        "guardrail": "Breadth/depth supports technical review only; it is not proof of infection, viability, or clinical relevance.",
    }


def _normalize_unknown_reads_int(value: int | float | str | None) -> int | None:
    if value in (None, "", ".", "unknown"):
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _clean_unknown_reads_files(files: dict | None) -> dict:
    if not isinstance(files, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in files.items()
        if value not in (None, "", ".")
    }


def _latest_unknown_reads_collection(run_ids: set[str]) -> dict:
    latest = next(
        (
            event for event in reversed(run_events)
            if event.run_id in run_ids and event.event_type == "dark_matter.unknown_reads_imported"
        ),
        None,
    )
    if not latest:
        return {
            "status": "not_collected",
            "message": "Unknown-read collection has not been imported for this run.",
            "non_diagnostic": True,
        }
    return {
        "event_id": latest.id,
        "created_at": latest.created_at,
        **(latest.payload or {}),
    }


class AutoIngestRequest(BaseModel):
    stage: str
    payload: dict = Field(default_factory=dict)


class RunProvenanceUpdateRequest(BaseModel):
    repo_commit: str | None = None
    docker_image_version: str | None = None
    nextflow_version: str | None = None
    pipeline_version: str | None = None
    command_line: str | None = None
    parameters: dict = Field(default_factory=dict)
    input_checksums: dict[str, str] = Field(default_factory=dict)
    output_checksums: dict[str, str] = Field(default_factory=dict)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    database_versions: dict[str, str] = Field(default_factory=dict)
    environment: dict = Field(default_factory=dict)


class ReportCreateRequest(BaseModel):
    report_type: str


class ReportGenerateRequest(BaseModel):
    report_type: str
    include_html: bool = True
    include_json: bool = True
    include_parquet: bool = True


class ReportBundleRepairRequest(BaseModel):
    report_types: list[str] = Field(default_factory=list)
    only_failed: bool = False


class BenchmarkImportRequest(BaseModel):
    benchmark_id: str | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    stratified_metrics: dict[str, float] = Field(default_factory=dict)
    benchmark_report_path: str | None = None


class VendorAssemblyValidationImportRequest(BaseModel):
    vendor_assembly_path: str | None = None
    pipeline_assembly_path: str | None = None
    vendor_validation_report_path: str | None = None
    similarity_score: float | None = None
    snv_concordance: float | None = None
    indel_concordance: float | None = None
    structural_concordance: float | None = None
    comparator_method: str = "proxy"
    kmer_size: int | None = None
    pass_threshold: float = 0.98
    summary: dict = Field(default_factory=dict)
    non_diagnostic: bool = True


class VendorAssemblyValidationFromFastqRequest(BaseModel):
    vendor_assembly_path: str
    comparator_method: str = "proxy"
    kmer_size: int | None = None
    pass_threshold: float = 0.98
    max_reads: int = 2000
    pipeline_assembly_output_path: str | None = None
    non_diagnostic: bool = True


class VendorAssemblyFastqE2ERequest(BaseModel):
    vendor_assembly_path: str
    comparator_method: str = "proxy"
    kmer_size: int | None = None
    pass_threshold: float = 0.98
    max_reads: int = 2000
    pipeline_assembly_output_path: str | None = None
    generate_reports: bool = True
    non_diagnostic: bool = True


class VendorAssemblyGlobalFastqE2ERequest(BaseModel):
    project_id: str | None = None
    project_name: str = "Vendor Validation API FastQ E2E"
    create_project_if_missing: bool = True
    reuse_existing_sample: bool = True
    sample_id: str
    reference_id: str = "GRCh38_standard"
    r1_path: str
    r2_path: str
    run_mode: str = "full"
    vendor_assembly_path: str
    comparator_method: str = "proxy"
    kmer_size: int | None = None
    pass_threshold: float = 0.98
    max_reads: int = 2000
    generate_reports: bool = True
    non_diagnostic: bool = True


class VendorAssemblyCompareRequest(BaseModel):
    vendor_assembly_path: str | None = None
    pipeline_assembly_path: str | None = None
    vendor_validation_report_path: str | None = None
    comparator_method: str = "proxy"
    kmer_size: int | None = None
    pass_threshold: float = 0.98


class VendorVcfCompareRequest(BaseModel):
    vendor_vcf_path: str
    pipeline_vcf_path: str
    pass_threshold: float = 0.98
    import_result: bool = True


class VendorAssemblyKmerSweepRequest(BaseModel):
    vendor_assembly_path: str | None = None
    pipeline_assembly_path: str | None = None
    vendor_validation_report_path: str | None = None
    kmer_sizes: list[int] = Field(default_factory=lambda: [11, 15, 21, 31])
    pass_threshold: float = 0.98


class VendorAssemblyRecommendationRequest(BaseModel):
    vendor_assembly_path: str | None = None
    pipeline_assembly_path: str | None = None
    vendor_validation_report_path: str | None = None
    kmer_sizes: list[int] = Field(default_factory=lambda: [11, 15, 21, 31])
    pass_threshold: float = 0.98


def _normalize_contig_style(value: str | None) -> str:
    raw = (value or "").strip().lower()
    mapping = {
        "chr": "chr",
        "chr_prefixed": "chr",
        "with_chr": "chr",
        "numeric": "numeric",
        "no_chr": "numeric",
        "bare": "numeric",
        "chrm": "chrm",
        "mt": "chrm",
    }
    return mapping.get(raw, raw)


def _reference_contig_style(reference_id: str) -> str | None:
    ref = next((r for r in references if r.id == reference_id), None)
    if not ref:
        return None
    return _normalize_contig_style(ref.contig_style)


def _normalize_chrom_for_reference(chrom: str, reference_id: str) -> str:
    raw = (chrom or "").strip()
    if not raw:
        return raw

    style = _reference_contig_style(reference_id) or "chr"
    token = raw
    if token.lower().startswith("chr"):
        token = token[3:]

    token = token.strip()
    token_up = token.upper()

    if token_up in {"M", "MT", "CHRM"}:
        return "MT" if style == "numeric" else "chrM"

    if token_up in {"X", "Y"}:
        core = token_up
    elif re.fullmatch(r"\d+", token):
        core = str(int(token))
    else:
        core = token

    if style == "numeric":
        return core
    if style == "chr":
        return f"chr{core}"
    return raw


def _append_step(run_id: str, step_name: str, status: str = "queued"):
    add_run_step(
        RunStep(
            id=f"step_{uuid4().hex[:10]}",
            run_id=run_id,
            step_name=step_name,
            status=status,
            progress_pct=0.0 if status != "done" else 100.0,
            last_log=f"{step_name} {status}",
        )
    )


def _seed_mtdna_prs_for_run(sample: Sample, run: Run):
    """Do not seed interpretation outputs.

    mtDNA haplogroups and PRS require real coverage/variant evidence plus
    versioned interpretation databases. Keep these modules empty until a stage
    imports genuine results; the UI should show not_configured/insufficient_data.
    """
    return


def _seed_taxonomy_for_run(sample: Sample, run: Run):
    """Do not seed taxonomy outputs.

    Taxonomy should reflect an explicit classification run/import. Demo hits
    make reruns look stale and can be mistaken for real biological signal.
    """
    return


def _seed_benchmark_for_run(sample: Sample, run: Run):
    if run.mode != "benchmark":
        return

    if any(b.run_id == run.id for b in benchmark_records):
        return

    benchmark_id = f"giab-{sample.sample_id.lower()}"
    previous = [
        b for b in benchmark_records if b.sample_id == sample.sample_id and b.reference_id == run.reference_id
    ]
    previous_sorted = sorted(previous, key=lambda x: x.created_at)
    prev_f1 = previous_sorted[-1].f1 if previous_sorted else None
    curr_f1 = 0.941

    regression_alert = None
    if prev_f1 is not None and curr_f1 < (prev_f1 - 0.01):
        regression_alert = "Benchmark regression detected: F1 dropped by > 0.01"

    add_benchmark_record(
        BenchmarkRecord(
            id=f"bm_{uuid4().hex[:10]}",
            benchmark_id=benchmark_id,
            sample_id=sample.sample_id,
            run_id=run.id,
            reference_id=run.reference_id,
            precision=0.946,
            recall=0.936,
            f1=curr_f1,
            stratified_metrics={
                "snv_f1": 0.972,
                "indel_f1": 0.901,
                "difficult_region_f1": 0.844,
            },
            regression_alert=regression_alert,
        )
    )


@router.get("/health")
def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/version")
def version():
    return {"service": APP_SERVICE, "version": APP_VERSION, "database_schema": get_schema_status()}


def _reference_dir(reference_id: str) -> Path:
    return REFERENCE_STORAGE_DIR / reference_id


def _normalize_checksum(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    for match in re.findall(r"\b[0-9a-fA-F]{64}\b|\b[0-9a-fA-F]{32}\b", raw):
        return match.lower()
    cleaned = re.sub(r"[^0-9a-fA-F]", "", raw).lower()
    return cleaned or None


def _reference_expected_checksum(urls: dict[str, str], source_key: str) -> dict | None:
    checksum_keys = [
        f"{source_key}_sha256",
        "download_sha256",
        "sha256",
        f"{source_key}_md5",
        "download_md5",
        "md5",
    ]
    for key in checksum_keys:
        expected = _normalize_checksum(urls.get(key))
        if not expected:
            continue
        algorithm = "sha256" if key.endswith("sha256") else "md5"
        return {"algorithm": algorithm, "expected": expected, "source": key}
    return None


def _file_checksum(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_reference_download_checksum(destination: Path, urls: dict[str, str], source_key: str) -> dict:
    expected = _reference_expected_checksum(urls, source_key)
    if not expected:
        return {"status": "not_configured"}
    algorithm = expected["algorithm"]
    actual = _file_checksum(destination, algorithm)
    result = {
        "status": "verified" if actual == expected["expected"] else "failed",
        "algorithm": algorithm,
        "expected": expected["expected"],
        "actual": actual,
        "source": expected["source"],
    }
    if result["status"] != "verified":
        raise ValueError(json.dumps(result, sort_keys=True))
    return result


def _reference_download_metadata(ref: ReferenceGenome) -> dict[str, str]:
    urls = dict(REFERENCE_DOWNLOAD_URLS.get(ref.id, {}))
    if ref.download_url and not (urls.get("fasta_gz") or urls.get("fasta")):
        urls["fasta_gz"] = ref.download_url
        urls.setdefault("source_page", ref.download_url)
    if ref.download_sha256 and not (urls.get("download_sha256") or urls.get("sha256")):
        urls["download_sha256"] = ref.download_sha256
    return urls


def _bwa_mem2_index_status(fasta: Path) -> dict:
    required_suffixes = [".0123", ".amb", ".ann", ".bwt.2bit.64", ".pac"]
    missing = [str(fasta) + suffix for suffix in required_suffixes if not Path(str(fasta) + suffix).exists()]
    return {
        "ready": len(missing) == 0,
        "missing": missing,
        "backend": "bwa-mem2",
    }


def _bwa_index_status(fasta: Path) -> dict:
    required_suffixes = [".amb", ".ann", ".bwt", ".pac", ".sa"]
    missing = [str(fasta) + suffix for suffix in required_suffixes if not Path(str(fasta) + suffix).exists()]
    return {
        "ready": len(missing) == 0,
        "missing": missing,
        "backend": "bwa",
    }


def _tools_for_backend(backend: str) -> list[str]:
    return {
        "minimap2": ["minimap2"],
        "bwa": ["bwa"],
        "bwa-mem2": ["bwa-mem2.avx512", "bwa-mem2.avx2", "bwa-mem2.sse42", "bwa-mem2.sse41", "bwa-mem2"],
        "mosdepth": ["mosdepth"],
        "bcftools": ["bcftools"],
        "deepvariant": ["run_deepvariant", "deepvariant"],
        "manta": ["configManta.py", "manta"],
        "delly": ["delly"],
        "cnvkit": ["cnvkit.py", "cnvkit"],
        "kraken2": ["kraken2"],
        "gatk": ["gatk"],
    }.get(backend, [])


def _backend_tool_available(backend: str) -> bool:
    tools = _tools_for_backend(backend)
    return not tools or any(shutil.which(tool) for tool in tools)


def _reference_alignment_backend_preflight(fasta: Path, alignment_backend: str | None = None) -> dict:
    backend = alignment_backend or _pipeline_settings()["backends"].get("alignment", "auto")
    bwa_mem2_index = _bwa_mem2_index_status(fasta)
    bwa_index = _bwa_index_status(fasta)

    if backend == "minimap2":
        return {
            "ready": _backend_tool_available("minimap2"),
            "backend": "minimap2",
            "selected_backend": "minimap2",
            "code": None if _backend_tool_available("minimap2") else "selected_backend_missing",
            "message": None if _backend_tool_available("minimap2") else "Selected alignment backend minimap2 is not installed.",
            "missing": [],
        }

    if backend == "bwa-mem2":
        if not _backend_tool_available("bwa-mem2"):
            return {
                "ready": False,
                "backend": "bwa-mem2",
                "selected_backend": "bwa-mem2",
                "code": "selected_backend_missing",
                "message": "Selected alignment backend bwa-mem2 is not installed in the active API/worker image.",
                "missing": [],
            }
        if not bwa_mem2_index["ready"]:
            return {
                "ready": False,
                "backend": "bwa-mem2",
                "selected_backend": "bwa-mem2",
                "code": "reference_bwa_mem2_index_missing",
                "message": "Selected alignment backend bwa-mem2 requires bwa-mem2 index files for this reference. Build the bwa-mem2 index or choose bwa/minimap2.",
                "missing": bwa_mem2_index["missing"],
            }
        return {"ready": True, "backend": "bwa-mem2", "selected_backend": "bwa-mem2", "missing": []}

    if backend == "bwa":
        if not _backend_tool_available("bwa"):
            return {
                "ready": False,
                "backend": "bwa",
                "selected_backend": "bwa",
                "code": "selected_backend_missing",
                "message": "Selected alignment backend bwa is not installed in the active API/worker image.",
                "missing": [],
            }
        if not bwa_index["ready"]:
            return {
                "ready": False,
                "backend": "bwa",
                "selected_backend": "bwa",
                "code": "reference_bwa_index_missing",
                "message": "Selected alignment backend bwa requires classic BWA index files for this reference.",
                "missing": bwa_index["missing"],
            }
        return {"ready": True, "backend": "bwa", "selected_backend": "bwa", "missing": []}

    # auto mirrors the stage script: minimap2 first, then indexed bwa-mem2, then indexed classic bwa.
    if _backend_tool_available("minimap2"):
        return {"ready": True, "backend": "auto", "selected_backend": "minimap2", "missing": []}
    if _backend_tool_available("bwa-mem2") and bwa_mem2_index["ready"]:
        return {"ready": True, "backend": "auto", "selected_backend": "bwa-mem2", "missing": []}
    if _backend_tool_available("bwa") and bwa_index["ready"]:
        return {"ready": True, "backend": "auto", "selected_backend": "bwa", "missing": []}
    missing = []
    if not bwa_mem2_index["ready"]:
        missing.extend(bwa_mem2_index["missing"])
    if not bwa_index["ready"]:
        missing.extend(bwa_index["missing"])
    return {
        "ready": False,
        "backend": "auto",
        "selected_backend": None,
        "code": "reference_index_missing",
        "message": "No usable auto alignment backend is ready. Install minimap2 or build a matching bwa/bwa-mem2 index for this reference.",
        "missing": missing,
    }


def _refresh_reference_status(ref: ReferenceGenome) -> ReferenceGenome:
    """Derive reference availability from files on disk, not optimistic flags."""
    urls = _reference_download_metadata(ref)
    ref.download_url = urls.get("fasta_gz") or urls.get("fasta") or ref.download_url
    candidates: list[Path] = []
    if ref.fasta_path:
        candidates.append(Path(ref.fasta_path))
    ref_dir = _reference_dir(ref.id)
    if ref_dir.exists():
        for pattern in ("*.fa", "*.fasta", "*.fna", "*.fa.gz", "*.fasta.gz", "*.fna.gz"):
            candidates.extend(sorted(ref_dir.glob(pattern)))
        # Fallback for providers saving FASTA under non-standard filenames
        # (e.g. NCBI viewer endpoints without .fa/.fasta extension).
        if not candidates:
            for p in sorted(ref_dir.iterdir()):
                if not p.is_file() or p.stat().st_size <= 0:
                    continue
                suffixes = p.suffixes
                index_suffixes = {".fai", ".amb", ".ann", ".pac", ".bwt", ".sa", ".0123", ".2bit", ".64"}
                if any(s in index_suffixes for s in suffixes):
                    continue
                candidates.append(p)

    fasta = next((p for p in candidates if p.exists() and p.is_file() and p.stat().st_size > 0), None)
    if fasta:
        ref.fasta_path = str(fasta)
        fai = Path(str(fasta) + ".fai")
        ref.fai_path = str(fai) if fai.exists() else ref.fai_path
        aligner_ready = _reference_alignment_backend_preflight(fasta).get("ready", False)
        ref.status = "indexed" if fai.exists() and aligner_ready else "available"
    elif ref.status != "downloading":
        ref.status = "missing"
    return ref


def _resolve_reference_fasta(reference_id: str) -> Path | None:
    ref = next((r for r in references if r.id == reference_id), None)
    if not ref:
        return None
    _refresh_reference_status(ref)
    if ref.fasta_path and Path(ref.fasta_path).exists():
        return Path(ref.fasta_path)
    return None


def _reference_local_files(ref: ReferenceGenome) -> list[Path]:
    paths: set[Path] = set()
    ref_dir = _reference_dir(ref.id)
    if ref_dir.exists():
        for path in ref_dir.rglob("*"):
            if path.is_file():
                paths.add(path)
    for raw in (ref.fasta_path, ref.fai_path, ref.dict_path):
        if raw:
            path = Path(raw)
            if path.exists() and path.is_file():
                paths.add(path)
            for sibling in path.parent.glob(path.name + "*"):
                if sibling.exists() and sibling.is_file():
                    paths.add(sibling)
    return sorted(paths)


def _reference_item(ref: ReferenceGenome) -> dict:
    _refresh_reference_status(ref)
    local_files = _reference_local_files(ref)
    urls = _reference_download_metadata(ref)
    source_key = "fasta_gz" if urls.get("fasta_gz") else "fasta"
    expected_checksum = _reference_expected_checksum(urls, source_key)
    data = ref.model_dump()
    data["builtin"] = ref.id in BUILTIN_REFERENCE_IDS
    data["local_files_present"] = bool(local_files)
    data["local_size_bytes"] = sum(path.stat().st_size for path in local_files if path.exists())
    data["download_checksum"] = expected_checksum or {"status": "not_configured"}
    data["download_source_page"] = urls.get("source_page")
    data["download_source_key"] = source_key if urls.get(source_key) else None
    return data


def _reference_pipeline_preflight(reference_id: str, stages: list[str]) -> dict:
    ref = next((r for r in references if r.id == reference_id), None)
    if not ref:
        return {"ready": False, "code": "reference_not_found", "message": f"Reference {reference_id} was not found."}

    _refresh_reference_status(ref)
    if not ref.fasta_path or not Path(ref.fasta_path).exists():
        return {
            "ready": False,
            "code": "reference_fasta_missing",
            "message": f"Reference {reference_id} FASTA is missing. Download it from References first.",
        }

    fasta = Path(ref.fasta_path)
    missing: list[str] = []
    fai = Path(str(fasta) + ".fai")
    if any(stage in stages for stage in ("alignment", "coverage", "variants", "sv", "cnv", "mtdna")) and not fai.exists():
        missing.append(str(fai))

    alignment_preflight = None
    if "alignment" in stages:
        alignment_backend = _pipeline_settings()["backends"].get("alignment", "auto")
        alignment_preflight = _reference_alignment_backend_preflight(fasta, alignment_backend)
        if not alignment_preflight.get("ready"):
            missing.extend(alignment_preflight.get("missing") or [])

    if missing or (alignment_preflight and not alignment_preflight.get("ready")):
        code = "reference_index_missing"
        message = f"Reference {reference_id} is present but missing required index files. Create indexes from References before starting the pipeline."
        if alignment_preflight and alignment_preflight.get("code"):
            code = alignment_preflight["code"]
            message = alignment_preflight.get("message") or message
        return {
            "ready": False,
            "code": code,
            "message": message,
            "reference_id": reference_id,
            "fasta_path": str(fasta),
            "missing": missing,
            "accepted_aligner_indexes": ["bwa", "bwa-mem2"],
            "selected_alignment_backend": _pipeline_settings()["backends"].get("alignment", "auto"),
            "alignment_preflight": alignment_preflight,
            "index_endpoint": f"/references/{reference_id}/index",
        }

    return {"ready": True, "reference_id": reference_id, "fasta_path": str(fasta), "alignment_preflight": alignment_preflight}


@router.get("/references")
def list_references():
    return {"items": [_reference_item(r) for r in references]}


class ReferenceCreateRequest(BaseModel):
    id: str
    version: str = "custom"
    source: str | None = None
    contig_style: str = "chr"
    mitochondrial_contig: str = "chrM"
    aliases: list[str] = Field(default_factory=list)
    fasta_path: str | None = None
    fai_path: str | None = None
    download_url: str | None = None
    download_sha256: str | None = None


@router.post("/references")
def create_reference(req: ReferenceCreateRequest):
    if any(r.id == req.id for r in references):
        raise HTTPException(status_code=409, detail="reference_already_exists")
    status = "missing"
    fasta_path = Path(req.fasta_path) if req.fasta_path else None
    if fasta_path and fasta_path.exists() and fasta_path.is_file():
        status = "available"

    ref = ReferenceGenome(
        id=req.id,
        version=req.version,
        source=req.source or "user-provided",
        contig_style=req.contig_style,
        mitochondrial_contig=req.mitochondrial_contig,
        aliases=req.aliases,
        status=status,
        fasta_path=str(fasta_path) if fasta_path else None,
        fai_path=req.fai_path,
        download_url=req.download_url,
        download_sha256=_normalize_checksum(req.download_sha256),
    )
    if req.download_url:
        REFERENCE_DOWNLOAD_URLS[ref.id] = {"fasta_gz": req.download_url, "source_page": req.download_url}
        if ref.download_sha256:
            REFERENCE_DOWNLOAD_URLS[ref.id]["download_sha256"] = ref.download_sha256
    add_reference(ref)
    return ref


@router.delete("/references/{reference_id}")
def delete_reference(reference_id: str):
    """Clear local reference files. Custom references are removed after files are cleared."""
    ref = next((r for r in references if r.id == reference_id), None)
    if not ref:
        raise HTTPException(status_code=404, detail="reference_not_found")

    deleted_files = []
    for path in _reference_local_files(ref):
        try:
            path.unlink(missing_ok=True)
            deleted_files.append(str(path))
        except IsADirectoryError:
            pass

    ref_dir = _reference_dir(reference_id)
    if ref_dir.exists() and ref_dir.is_dir():
        shutil.rmtree(ref_dir)
    if reference_id in BUILTIN_REFERENCE_IDS:
        ref.fasta_path = None
        ref.fai_path = None
        ref.dict_path = None
        ref.status = "missing"
        save_reference(ref)
        return {"reference_id": reference_id, "action": "cleared_local_files", "deleted_files": deleted_files}

    remove_reference(reference_id)
    REFERENCE_DOWNLOAD_URLS.pop(reference_id, None)
    return {"reference_id": reference_id, "action": "deleted_custom_reference", "deleted_files": deleted_files}


@router.post("/references/{reference_id}/download")
def download_reference(reference_id: str):
    """Download reference FASTA file into container. Returns job_id for progress tracking."""
    ref = next((r for r in references if r.id == reference_id), None)
    if not ref:
        raise HTTPException(status_code=404, detail="reference_not_found")

    urls = _reference_download_metadata(ref)
    source_key = "fasta_gz" if urls.get("fasta_gz") else "fasta"
    fasta_url = urls.get(source_key)
    if not fasta_url:
        raise HTTPException(status_code=400, detail="no_download_url_available")

    import gzip
    import shutil
    import time

    job_id = f"ref_{uuid4().hex[:10]}"
    dest_dir = _reference_dir(reference_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = fasta_url.split("/")[-1]
    destination = dest_dir / filename

    # Store job info. Reuse data-ingest progress endpoint.
    from app.routers.data_ingest import DOWNLOAD_JOBS, _update_job
    DOWNLOAD_JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "phase": "queued",
        "url": fasta_url,
        "destination": str(destination),
        "filename": destination.name,
        "downloaded_bytes": 0,
        "total_bytes": None,
        "speed_bps": 0,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "checksum": {"status": "pending" if _reference_expected_checksum(urls, source_key) else "not_configured"},
    }

    def _reference_download_worker():
        start = time.time()
        downloaded = 0
        total_bytes: int | None = None
        _update_job(job_id, status="downloading", phase="downloading", started_at=start)
        try:
            with urllib.request.urlopen(fasta_url, timeout=60) as response:  # nosec B310
                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    total_bytes = int(content_length)
                    _update_job(job_id, total_bytes=total_bytes)
                with destination.open("wb") as out:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        elapsed = max(time.time() - start, 1e-6)
                        _update_job(
                            job_id,
                            downloaded_bytes=downloaded,
                            total_bytes=total_bytes,
                            speed_bps=int(downloaded / elapsed),
                        )

            try:
                _update_job(job_id, status="verifying", phase="checksum")
                checksum = _validate_reference_download_checksum(destination, urls, source_key)
                _update_job(job_id, checksum=checksum)
            except ValueError as exc:
                try:
                    checksum = json.loads(str(exc))
                except json.JSONDecodeError:
                    checksum = {"status": "failed", "error": str(exc)}
                _update_job(job_id, checksum=checksum)
                raise RuntimeError("reference_checksum_mismatch")

            fasta_path = destination
            if destination.suffix == ".gz":
                fasta_path = destination.with_suffix("")
                _update_job(job_id, status="unpacking", phase="decompressing")
                with gzip.open(destination, "rb") as src, fasta_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

            # Build lightweight FASTA index when tools are present. Aligner
            # indexing is explicit from the References UI because full GRCh38
            # can exceed 32 GB RAM with bwa-mem2.
            if subprocess.run(["bash", "-lc", "command -v samtools"], capture_output=True).returncode == 0:
                _update_job(job_id, status="indexing", phase="faidx")
                subprocess.run(["samtools", "faidx", str(fasta_path)], capture_output=True, text=True, timeout=300)

            ref.fasta_path = str(fasta_path)
            fai = Path(str(fasta_path) + ".fai")
            ref.fai_path = str(fai) if fai.exists() else None
            ref.status = "available"
            elapsed = max(time.time() - start, 1e-6)
            _update_job(
                job_id,
                status="done",
                phase="done",
                downloaded_bytes=downloaded,
                total_bytes=total_bytes,
                speed_bps=int(downloaded / elapsed),
                reference_ready=True,
                fasta_path=str(fasta_path),
                finished_at=time.time(),
            )
        except Exception as exc:
            ref.status = "missing"
            destination.unlink(missing_ok=True)
            if destination.suffix == ".gz":
                destination.with_suffix("").unlink(missing_ok=True)
            _update_job(job_id, status="failed", phase="failed", error=str(exc), finished_at=time.time())

    # Update reference status
    ref.status = "downloading"

    thread = threading.Thread(target=_reference_download_worker, daemon=True)
    thread.start()

    return {"job_id": job_id, "reference_id": reference_id, "url": fasta_url, "destination": str(destination)}


REFERENCE_DOWNLOAD_URLS: dict[str, dict[str, str]] = {
    "GRCh38_chr20": {
        "fasta_gz": "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes/chr20.fa.gz",
        "source_page": "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes/",
    },
    "GRCh38_standard": {
        "fasta_gz": "ftp://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38/seqs_for_alignment_pipelines.ucsc_ids/GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz",
        "fai": "ftp://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38/seqs_for_alignment_pipelines.ucsc_ids/GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz.fai",
        "gzi": "ftp://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38/seqs_for_alignment_pipelines.ucsc_ids/GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz.gzi",
        "source_page": "https://www.ncbi.nlm.nih.gov/datasets/genome/GCF_000001405.40/",
    },
    "GRCh38_GIAB_masked_false_duplications": {
        "fasta_gz": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/references/GRCh38/GRCh38_GIABv3.fasta.gz",
        "source_page": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/references/GRCh38/",
    },
    "GRCh37_legacy": {
        "fasta_gz": "ftp://ftp.ncbi.nlm.nih.gov/1000genomes/ftp/technical/reference/human_g1k_v37.fasta.gz",
        "source_page": "https://www.ncbi.nlm.nih.gov/datasets/genome/GCF_000001405.13/",
    },
    "T2T_CHM13v2_hs1": {
        "fasta_gz": "https://s3-us-west-2.amazonaws.com/human-pangenomics/T2T/CHM13/assemblies/analysis_set/chm13v2.0.fa.gz",
        "source_page": "https://github.com/marbl/CHM13",
    },
    "mtDNA_rCRS": {
        "fasta": "https://www.ncbi.nlm.nih.gov/sviewer/viewer.fcgi?id=NC_012920.1&db=nuccore&report=fasta",
        "genbank": "https://www.ncbi.nlm.nih.gov/nuccore/NC_012920.1",
        "source_page": "https://www.ncbi.nlm.nih.gov/nuccore/NC_012920.1",
    },
    "mtDNA_RSRS": {
        "fasta": "https://www.ncbi.nlm.nih.gov/sviewer/viewer.fcgi?id=J01415.2&db=nuccore&report=fasta",
        "source_page": "https://www.ncbi.nlm.nih.gov/nuccore/J01415",
    },
    "hs38d1_decoy": {
        "fasta_gz": "ftp://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38/seqs_for_alignment_pipelines.ucsc_ids/GCA_000001405.15_GRCh38_full_plus_hs38d1_analysis_set.fna.gz",
        "source_page": "https://www.ncbi.nlm.nih.gov/grc/human/data",
    },
}

REFERENCE_INDEX_JOBS: dict[str, dict] = {}


def _reference_index_backend(fasta_path: Path) -> tuple[str, list[str]]:
    if _bwa_index_status(fasta_path)["ready"]:
        return "bwa", []
    if shutil.which("bwa"):
        return "bwa", ["bwa", "index", str(fasta_path)]
    if _bwa_mem2_index_status(fasta_path)["ready"]:
        return "bwa-mem2", []
    if shutil.which("bwa-mem2"):
        return "bwa-mem2", ["bwa-mem2", "index", str(fasta_path)]
    return "missing", []


def _run_reference_index_command(cmd: list[str], job: dict | None = None) -> None:
    if job is not None:
        job["command"] = " ".join(cmd)
        job["updated_at"] = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if job is not None:
        job["pid"] = proc.pid
    stdout, stderr = proc.communicate()
    if job is not None:
        job["updated_at"] = time.time()
        job.pop("pid", None)
    if proc.returncode != 0:
        stderr = (stderr or "").strip()
        stdout = (stdout or "").strip()
        detail = stderr or stdout or f"{cmd[0]} exited with {proc.returncode}"
        raise RuntimeError(detail[-1600:])


def _reference_index_job_status(job: dict) -> dict:
    data = dict(job)
    started_at = data.get("started_at")
    finished_at = data.get("finished_at")
    if started_at:
        data["elapsed_sec"] = round((finished_at or time.time()) - started_at, 1)
    pid = data.get("pid")
    if pid:
        try:
            os.kill(int(pid), 0)
            data["process_alive"] = True
        except OSError:
            data["process_alive"] = False
    return data


@router.post("/references/{reference_id}/index")
def index_reference(reference_id: str):
    ref = next((r for r in references if r.id == reference_id), None)
    if not ref:
        raise HTTPException(status_code=404, detail="reference_not_found")
    _refresh_reference_status(ref)
    if not ref.fasta_path:
        raise HTTPException(status_code=400, detail="reference_fasta_missing")

    fasta_path = Path(ref.fasta_path)
    if not fasta_path.exists():
        raise HTTPException(status_code=400, detail="reference_fasta_missing")

    active = [
        job for job in REFERENCE_INDEX_JOBS.values()
        if job.get("reference_id") == reference_id and job.get("status") in {"queued", "indexing", "running"}
    ]
    if active:
        active.sort(key=lambda x: x.get("started_at", 0), reverse=True)
        return _reference_index_job_status(active[0])

    backend, aligner_cmd = _reference_index_backend(fasta_path)
    if backend == "missing":
        raise HTTPException(status_code=400, detail={"code": "aligner_index_tool_missing", "message": "Neither bwa nor bwa-mem2 is installed in the API image."})

    job_id = f"refidx_{uuid4().hex[:10]}"
    REFERENCE_INDEX_JOBS[job_id] = {
        "job_id": job_id,
        "reference_id": reference_id,
        "status": "queued",
        "steps": [],
        "progress_pct": 0,
        "error": None,
        "backend": backend,
        "phase": "queued",
        "started_at": time.time(),
        "updated_at": time.time(),
        "finished_at": None,
    }

    def _run_index():
        job = REFERENCE_INDEX_JOBS[job_id]
        try:
            job["status"] = "indexing"
            job["phase"] = "faidx"
            job["updated_at"] = time.time()
            job["steps"].append("samtools faidx")
            _run_reference_index_command(["samtools", "faidx", str(fasta_path)], job)
            job["progress_pct"] = 20

            job["phase"] = "dict"
            job["updated_at"] = time.time()
            job["steps"].append("samtools dict")
            dict_path = fasta_path.with_suffix(".dict")
            _run_reference_index_command(["samtools", "dict", "-o", str(dict_path), str(fasta_path)], job)
            job["progress_pct"] = 35

            if aligner_cmd:
                job["phase"] = f"{backend}_index"
                job["steps"].append(" ".join(aligner_cmd[:2]))
                job["progress_pct"] = 40
                job["updated_at"] = time.time()
                _run_reference_index_command(aligner_cmd, job)
            job["progress_pct"] = 100
            job["status"] = "done"
            job["phase"] = "done"
            job["updated_at"] = time.time()
            job["finished_at"] = time.time()
            _refresh_reference_status(ref)
            fai = Path(str(fasta_path) + ".fai")
            ref.fai_path = str(fai) if fai.exists() else ref.fai_path
        except Exception as exc:
            job["status"] = "failed"
            job["phase"] = "failed"
            job["error"] = str(exc)
            job["updated_at"] = time.time()
            job["finished_at"] = time.time()

    threading.Thread(target=_run_index, daemon=False).start()
    return {"job_id": job_id, "reference_id": reference_id, "status": "queued"}


@router.get("/references/{reference_id}/index-status")
def get_reference_index_status(reference_id: str):
    jobs = [j for j in REFERENCE_INDEX_JOBS.values() if j.get("reference_id") == reference_id]
    if not jobs:
        ref = next((r for r in references if r.id == reference_id), None)
        if not ref:
            raise HTTPException(status_code=404, detail="reference_not_found")
        _refresh_reference_status(ref)
        preflight = _reference_pipeline_preflight(reference_id, ["alignment"])
        return {"status": "no_job", "reference_id": reference_id, "preflight": preflight}
    jobs.sort(key=lambda x: x.get("started_at", 0), reverse=True)
    return _reference_index_job_status(jobs[0])


@router.post("/references/download")
def reference_download(req: ReferenceActionRequest):
    ref = next((r for r in references if r.id == req.reference_id), None)
    if not ref:
        raise HTTPException(status_code=404, detail="reference_not_found")

    ref.status = "downloading"
    return {
        "reference_id": ref.id,
        "status": ref.status,
        "note": "Placeholder action. Real downloader wired in next iteration.",
    }


@router.get("/references/{reference_id}/download-urls")
def get_reference_download_urls(reference_id: str):
    ref = next((r for r in references if r.id == reference_id), None)
    if not ref:
        raise HTTPException(status_code=404, detail="reference_not_found")

    urls = _reference_download_metadata(ref)
    if not urls:
        raise HTTPException(status_code=404, detail="download_urls_not_available")

    return {
        "reference_id": ref.id,
        "version": ref.version,
        "source": ref.source,
        "contig_style": ref.contig_style,
        "current_status": ref.status,
        "local_fasta_path": ref.fasta_path,
        "local_fai_path": ref.fai_path,
        "local_dict_path": ref.dict_path,
        "download_urls": urls,
        "estimated_size": {
            "GRCh38_standard": "~3.0 GB (gzipped)",
            "GRCh38_GIAB_masked_false_duplications": "~3.0 GB (gzipped)",
            "GRCh37_legacy": "~3.0 GB (gzipped)",
            "T2T_CHM13v2_hs1": "~3.1 GB (gzipped)",
            "mtDNA_rCRS": "~16.6 KB",
        }.get(reference_id, "unknown"),
    }


@router.post("/references/index")
def reference_index(req: ReferenceActionRequest):
    ref = next((r for r in references if r.id == req.reference_id), None)
    if not ref:
        raise HTTPException(status_code=404, detail="reference_not_found")

    if ref.status in {"missing", "invalid"}:
        raise HTTPException(status_code=400, detail="reference_not_ready_for_indexing")

    ref.status = "indexed"
    return {
        "reference_id": ref.id,
        "status": ref.status,
        "note": "Placeholder action. Real index builders wired in next iteration.",
    }


@router.get("/references/{reference_id}/compatibility")
def reference_compatibility(reference_id: str, contig_style: str):
    ref = next((r for r in references if r.id == reference_id), None)
    if not ref:
        raise HTTPException(status_code=404, detail="reference_not_found")

    expected = _normalize_contig_style(ref.contig_style)
    observed = _normalize_contig_style(contig_style)
    compatible = observed == expected

    return {
        "reference_id": ref.id,
        "reference_contig_style": expected,
        "observed_contig_style": observed,
        "compatible": compatible,
        "note": (
            "Contig-style compatible with selected reference profile."
            if compatible
            else "Contig-style mismatch (chr1 vs 1 risk). Select matching reference/profile."
        ),
    }


@router.get("/projects")
def list_projects():
    refresh_from_db(recover_stale_running=False)
    return {"items": projects}


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    refresh_from_db(recover_stale_running=False)
    project = next((p for p in projects if p.id == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="project_not_found")
    return project


@router.get("/projects/{project_id}/samples")
def list_project_samples(project_id: str):
    refresh_from_db(recover_stale_running=False)
    if not any(p.id == project_id for p in projects):
        raise HTTPException(status_code=404, detail="project_not_found")
    return {"items": [sample for sample in samples if sample.project_id == project_id]}


@router.get("/projects/{project_id}/runs")
def list_project_runs(project_id: str):
    refresh_from_db(recover_stale_running=False)
    if not any(p.id == project_id for p in projects):
        raise HTTPException(status_code=404, detail="project_not_found")
    return {"items": [_repair_planned_run_status(run) for run in runs if run.project_id == project_id]}


@router.get("/runs")
def list_runs(limit: int = 50):
    refresh_from_db(recover_stale_running=False)
    sorted_runs = sorted(runs, key=lambda r: r.created_at or "", reverse=True)
    return {"items": [_repair_planned_run_status(run) for run in sorted_runs[: max(1, min(limit, 200))]]}


def _safe_result_dir_for_run_id(run_id: str) -> Path:
    if not run_id.startswith("run_"):
        raise HTTPException(status_code=400, detail={"code": "invalid_run_id_for_results_cleanup", "run_id": run_id})
    root = PIPELINE_RESULTS_ROOT.resolve(strict=False)
    path = (root / run_id).resolve(strict=False)
    if path.parent != root or path.name != run_id:
        raise HTTPException(status_code=400, detail={"code": "unsafe_results_path", "run_id": run_id, "path": str(path)})
    return path


def _delete_result_dirs_for_run_ids(run_ids: set[str]) -> list[dict]:
    deleted = []
    for run_id in sorted(run_ids):
        path = _safe_result_dir_for_run_id(run_id)
        if not path.exists():
            continue
        size_bytes = _path_size_bytes(path)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        deleted.append({"run_id": run_id, "path": str(path), "size_bytes": size_bytes})
    return deleted


@router.delete("/projects/{project_id}")
def delete_project(project_id: str):
    project = next((p for p in projects if p.id == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="project_not_found")
    # Delete associated runs, samples, variants, etc.
    run_ids = {r.id for r in runs if r.project_id == project_id}
    active_run_ids = {r.id for r in runs if r.project_id == project_id and r.status in ("running", "queued", "paused", "cancelling")}
    if active_run_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_has_active_runs",
                "message": "Cancel or wait for active runs before deleting the project.",
                "run_ids": sorted(active_run_ids),
            },
        )
    sample_ids = {s.id for s in samples if s.project_id == project_id}
    sample_id_strings = {s.sample_id for s in samples if s.project_id == project_id}
    deleted_result_dirs = _delete_result_dirs_for_run_ids(run_ids)
    delete_runs_by_project(project_id)
    delete_samples_by_project(project_id)
    delete_variants_by_sample_ids(sample_id_strings)
    delete_structural_variants_by_sample_ids(sample_id_strings)
    delete_cnv_segments_by_sample_ids(sample_id_strings)
    delete_mtdna_hits_by_sample_ids(sample_id_strings)
    delete_prs_results_by_sample_ids(sample_id_strings)
    delete_taxonomy_hits_by_sample_ids(sample_id_strings)
    delete_interpretation_results_by_sample_ids(sample_id_strings)
    delete_coverage_metrics_by_sample_ids(sample_id_strings)
    delete_alignment_metrics_by_sample_ids(sample_id_strings)
    delete_run_events_by_run_ids(run_ids)
    delete_run_logs_by_run_ids(run_ids)
    delete_run_steps_by_run_ids(run_ids)
    delete_qc_summaries_by_run_ids(run_ids)
    delete_coverage_metrics_by_run_ids(run_ids)
    delete_alignment_metrics_by_run_ids(run_ids)
    delete_reports_by_run_ids(run_ids)
    delete_interpretation_results_by_run_ids(run_ids)
    remove_project(project_id)
    return {"deleted": project_id, "deleted_result_dirs": deleted_result_dirs}


@router.delete("/runs/{run_id}")
def delete_run(run_id: str):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    if run.status in ("running", "queued", "paused", "cancelling"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "run_may_still_be_active",
                "message": "Cancel or wait for the run before deleting it.",
                "run_status": run.status,
            },
        )
    sample_id_strings = {s.sample_id for s in samples if s.id == run.sample_id}
    # Delete run-specific data
    deleted_result_dirs = _delete_result_dirs_for_run_ids({run_id})
    delete_variants_by_run(run_id)
    delete_structural_variants_by_run(run_id)
    delete_cnv_segments_by_run(run_id)
    delete_mtdna_hits_by_run(run_id)
    delete_prs_results_by_run(run_id)
    delete_taxonomy_hits_by_run(run_id)
    delete_interpretation_results_by_run(run_id)
    delete_run_events_by_run(run_id)
    delete_run_logs_by_run(run_id)
    delete_run_steps_by_run(run_id)
    delete_qc_summaries_by_run(run_id)
    delete_coverage_metrics_by_run(run_id)
    delete_alignment_metrics_by_run(run_id)
    delete_reports_by_run(run_id)
    remove_run(run_id)
    return {"deleted": run_id, "deleted_result_dirs": deleted_result_dirs}


@router.get("/samples/{sample_pk}/runs")
def list_sample_runs(sample_pk: str):
    refresh_from_db(recover_stale_running=False)
    if not any(sample.id == sample_pk for sample in samples):
        raise HTTPException(status_code=404, detail="sample_not_found")
    return {"items": [_repair_planned_run_status(run) for run in runs if run.sample_id == sample_pk]}


@router.post("/projects")
def create_project(req: ProjectCreateRequest):
    project = Project(id=f"prj_{uuid4().hex[:10]}", name=req.name.strip(), description=req.description)
    add_project(project)
    return project


@router.patch("/projects/{project_id}")
def update_project(project_id: str, req: ProjectUpdateRequest):
    project = next((p for p in projects if p.id == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="project_not_found")
    name = req.name.strip() if req.name is not None else project.name
    if not name:
        raise HTTPException(status_code=400, detail="project_name_required")
    updated = project.model_copy(update={
        "name": name,
        "description": req.description if req.description is not None else project.description,
    })
    save_project(updated)
    return updated


@router.post("/projects/{project_id}/samples")
def create_sample(project_id: str, req: SampleCreateRequest):
    project = next((p for p in projects if p.id == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="project_not_found")

    if req.reference_id not in {r.id for r in references}:
        raise HTTPException(status_code=400, detail="unknown_reference")

    sample = Sample(
        id=f"smp_{uuid4().hex[:10]}",
        project_id=project_id,
        sample_id=req.sample_id,
        reference_id=req.reference_id,
        r1_path=req.r1_path,
        r2_path=req.r2_path,
    )
    add_sample(sample)
    return sample


def _create_run_internal(project_id: str, mode: str, req: RunCreateRequest):
    project = next((p for p in projects if p.id == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="project_not_found")

    sample = next((s for s in samples if s.id == req.sample_id and s.project_id == project_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    if req.reference_id != sample.reference_id:
        raise HTTPException(status_code=400, detail="sample_reference_locked")

    expected_style = _reference_contig_style(req.reference_id)
    observed_style = _normalize_contig_style(req.contig_style)
    if req.contig_style and expected_style and observed_style != expected_style:
        raise HTTPException(status_code=400, detail="reference_contig_style_mismatch")

    run = Run(
        id=f"run_{uuid4().hex[:10]}",
        project_id=project_id,
        sample_id=sample.id,
        mode=mode,
        reference_id=req.reference_id,
        status="queued",
    )
    add_run(run)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="run.queued",
            payload={"mode": mode},
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=1, message="Run queued by API"))

    _append_step(run.id, "input_validation", status="done")
    if mode == "qc":
        _append_step(run.id, "fastqc_pre")
        _append_step(run.id, "fastp_optional")
        _append_step(run.id, "fastqc_post")
        _append_step(run.id, "multiqc")
        qc = build_qc_summary(sample_id=sample.sample_id, run_id=run.id)
        replace_qc_summary_for_run(run.id, qc)
    else:
        _append_step(run.id, "pipeline_dispatch")
        for stage_name in PIPELINE_STAGES:
            _append_step(run.id, stage_name)
        _append_step(run.id, "vendor_validation")
        if mode == "benchmark":
            _append_step(run.id, "benchmark")
        _seed_mtdna_prs_for_run(sample, run)
        _seed_taxonomy_for_run(sample, run)
        _seed_benchmark_for_run(sample, run)

    return run


@router.post("/projects/{project_id}/run/{mode}")
def create_run(project_id: str, mode: str, req: RunCreateRequest):
    return _create_run_internal(project_id=project_id, mode=mode, req=req)


@router.post("/projects/{project_id}/run/qc")
def create_run_qc(project_id: str, req: RunCreateRequest):
    return _create_run_internal(project_id=project_id, mode="qc", req=req)


@router.post("/projects/{project_id}/run/full")
def create_run_full(project_id: str, req: RunCreateRequest):
    return _create_run_internal(project_id=project_id, mode="full", req=req)


@router.post("/projects/{project_id}/run/benchmark")
def create_run_benchmark(project_id: str, req: RunCreateRequest):
    return _create_run_internal(project_id=project_id, mode="benchmark", req=req)


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    refresh_from_db(recover_stale_running=False)
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    return _repair_planned_run_status(run)


@router.get("/runs/{run_id}/pipeline/checkpoints")
def get_pipeline_checkpoints(run_id: str):
    refresh_from_db(recover_stale_running=False)
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    sample = next((s for s in samples if s.id == run.sample_id), None)
    return _alignment_checkpoint_status(run, sample)


@router.get("/runs/{run_id}/storage/temp")
def get_run_temp_storage(run_id: str):
    refresh_from_db(recover_stale_running=False)
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    sample = next((s for s in samples if s.id == run.sample_id), None)
    artifacts = _alignment_temp_artifacts(run, sample)
    return {
        "run_id": run.id,
        "status": run.status,
        "artifacts": artifacts,
        "count": len(artifacts),
        "total_size_bytes": sum(item["size_bytes"] for item in artifacts),
    }


@router.post("/runs/{run_id}/storage/temp/cleanup")
def cleanup_run_temp_storage(run_id: str, dry_run: bool = True):
    refresh_from_db(recover_stale_running=False)
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    if run.status in ("running", "queued", "paused", "cancelling"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "run_may_still_be_active",
                "message": "Refusing to delete temporary artifacts while the run may still be active.",
                "run_status": run.status,
            },
        )
    sample = next((s for s in samples if s.id == run.sample_id), None)
    artifacts = _alignment_temp_artifacts(run, sample)
    deleted = []
    for item in artifacts:
        path = Path(item["path"])
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.is_file():
                path.unlink()
            deleted.append(item)
    if not dry_run and artifacts:
        _emit_run_event(
            run_id,
            "run_temp_storage_cleaned",
            {"count": len(deleted), "total_size_bytes": sum(item["size_bytes"] for item in deleted)},
        )
    return {
        "run_id": run.id,
        "dry_run": dry_run,
        "artifacts": artifacts,
        "deleted_count": 0 if dry_run else len(deleted),
        "total_size_bytes": sum(item["size_bytes"] for item in artifacts),
    }


def _results_storage_items() -> list[dict]:
    known_run_ids = {run.id for run in runs}
    active_run_ids = {run.id for run in runs if run.status in ("running", "queued", "paused", "cancelling")}
    root = PIPELINE_RESULTS_ROOT
    if not root.exists():
        return []

    items = []
    for path in sorted(root.iterdir(), key=lambda p: p.name):
        if path.name.startswith("."):
            continue
        if path.name.startswith("run_"):
            if path.name in known_run_ids:
                classification = "known_run"
            else:
                classification = "orphan_run_dir"
        else:
            classification = "non_run_item"
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "kind": "directory" if path.is_dir() else "file",
                "classification": classification,
                "known_run": path.name in known_run_ids,
                "active_run": path.name in active_run_ids,
                "size_bytes": _path_size_bytes(path),
            }
        )
    return items


@router.get("/storage/results")
def get_results_storage():
    refresh_from_db(recover_stale_running=False)
    items = _results_storage_items()
    return {
        "root": str(PIPELINE_RESULTS_ROOT),
        "items": items,
        "count": len(items),
        "known_run_count": sum(1 for item in items if item["classification"] == "known_run"),
        "orphan_run_dir_count": sum(1 for item in items if item["classification"] == "orphan_run_dir"),
        "orphan_run_dir_size_bytes": sum(item["size_bytes"] for item in items if item["classification"] == "orphan_run_dir"),
        "total_size_bytes": sum(item["size_bytes"] for item in items),
    }


@router.post("/storage/results/cleanup-orphans")
def cleanup_orphan_results(dry_run: bool = True):
    refresh_from_db(recover_stale_running=False)
    items = [item for item in _results_storage_items() if item["classification"] == "orphan_run_dir"]
    deleted = []
    for item in items:
        path = Path(item["path"])
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.is_file():
                path.unlink()
            deleted.append(item)
    return {
        "root": str(PIPELINE_RESULTS_ROOT),
        "dry_run": dry_run,
        "items": items,
        "deleted_count": 0 if dry_run else len(deleted),
        "total_size_bytes": sum(item["size_bytes"] for item in items),
    }


class PipelineStartRequest(BaseModel):
    stages: list[str] | None = None  # None = all stages
    input_files: list[str] | None = None  # FASTQ paths
    allow_dev_fallback: bool = False
    stop_on_failure: bool = True
    profile: str | None = None  # pipeline profile name
    resume_existing: bool = False  # true = refuse to restart a failed stage without a durable checkpoint
    from_stage: str | None = None  # resume/retry from this stage in the canonical order
    only_stages: list[str] | None = None  # execute exactly these stages, in canonical order
    skip_stages: list[str] = Field(default_factory=list)  # operator-declared skips
    skip_reason: str | None = None
    taxonomy_database: str | None = None
    taxonomy_route: str | None = None
    taxonomy_low_mapq_threshold: int | None = None


class TaxonomySubrunRequest(BaseModel):
    taxonomy_database: str
    taxonomy_route: str | None = None
    taxonomy_low_mapq_threshold: int | None = None
    allow_dev_fallback: bool = False
    stop_on_failure: bool = False


class StageSkipRequest(BaseModel):
    reason: str | None = None
    force: bool = False


ALIGNMENT_CHECKPOINT_SUFFIXES = [
    (".sorted.markdup.bam", "complete_markdup_bam"),
    (".coord_sorted.bam", "coordinate_sorted_bam"),
    (".fixmate.bam", "fixmate_bam"),
    (".name_sorted.bam", "name_sorted_bam"),
]
ALIGNMENT_TEMP_FILE_GLOBS = [
    "*.bam.tmp.*.bam",
    "*.cram.tmp.*.cram",
]


PIPELINE_EXECUTOR_ENV = "WGS_PIPELINE_EXECUTOR"
PIPELINE_EXECUTOR_API_THREAD = "api_thread"
PIPELINE_EXECUTOR_WORKER_QUEUE = "worker_queue"
PIPELINE_JOB_QUEUE_ENV = "WGS_PIPELINE_JOB_QUEUE"
PIPELINE_JOB_QUEUE_DEFAULT = "wgs:pipeline:jobs"
PIPELINE_RESULTS_ROOT = Path(os.getenv("PIPELINE_RESULTS_ROOT", "/data/results"))
REDIS_URL_ENV = "REDIS_URL"
REDIS_URL_DEFAULT = "redis://redis:6379/0"
COMPUTE_PROFILE_ENV = "WGS_COMPUTE_PROFILE"
PIPELINE_THREADS_ENV = "WGS_PIPELINE_THREADS"
PIPELINE_SETTINGS_PATH = Path(os.getenv("WGS_PIPELINE_SETTINGS_PATH", "/data/config/pipeline_settings.json"))
COMPUTE_PROFILE_THREADS = {
    "lowmem": 2,
    "standard": 4,
    "highmem": 12,
}

DEFAULT_PIPELINE_SETTINGS = {
    "backends": {
        "alignment": "auto",
        "coverage": "mosdepth",
        "variants": "bcftools",
        "sv": "auto",
        "cnv": "auto",
        "taxonomy": "kraken2",
        "mtdna": "gatk",
        "prs": "auto",
    },
    "disk_pressure": {
        "alignment_peak_multiplier": 5.0,
        "min_free_gb_before_markdup": 120,
        "block_start_when_estimate_exceeds_free": False,
        "scratch_root": "",
    },
    "taxonomy": {
        "default_route": "human_wgs_host_depleted",
        "low_mapq_threshold": 10,
    },
}

TAXONOMY_ROUTES = {
    "human_wgs_host_depleted": {
        "label": "Human WGS host-depleted",
        "description": "Classify paired reads where both mates are unmapped in the final host BAM.",
        "input_mode": "host_depleted_bam_unmapped_pairs",
    },
    "human_wgs_sensitive_low_mapq": {
        "label": "Sensitive human WGS",
        "description": "Classify unmapped, mate-unmapped, and low-MAPQ paired reads from the host BAM.",
        "input_mode": "host_depleted_bam_sensitive_low_mapq",
    },
    "full_fastq_shotgun": {
        "label": "Full FASTQ shotgun/metagenomics",
        "description": "Classify the original FASTQ pair without host depletion.",
        "input_mode": "raw_fastq",
    },
    "custom_host_depletion": {
        "label": "Custom host depletion",
        "description": "Use the supplied host BAM as the depletion source before taxonomy.",
        "input_mode": "host_depleted_custom_host",
    },
}

BACKEND_OPTIONS = {
    "alignment": ["auto", "minimap2", "bwa", "bwa-mem2"],
    "coverage": ["mosdepth"],
    "variants": ["bcftools", "gatk", "deepvariant"],
    "sv": ["auto", "manta", "delly"],
    "cnv": ["auto", "cnvkit"],
    "taxonomy": ["kraken2"],
    "mtdna": ["gatk"],
    "prs": ["auto"],
}


def _pipeline_settings() -> dict:
    settings = json.loads(json.dumps(DEFAULT_PIPELINE_SETTINGS))
    try:
        if PIPELINE_SETTINGS_PATH.exists():
            stored = json.loads(PIPELINE_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(stored.get("backends"), dict):
                settings["backends"].update(stored["backends"])
            if isinstance(stored.get("disk_pressure"), dict):
                settings["disk_pressure"].update(stored["disk_pressure"])
            if isinstance(stored.get("taxonomy"), dict):
                settings["taxonomy"].update(stored["taxonomy"])
    except Exception:
        pass
    for stage, allowed in BACKEND_OPTIONS.items():
        if settings["backends"].get(stage) not in allowed:
            settings["backends"][stage] = DEFAULT_PIPELINE_SETTINGS["backends"].get(stage, "auto")
    disk = settings["disk_pressure"]
    try:
        disk["alignment_peak_multiplier"] = max(1.0, float(disk.get("alignment_peak_multiplier") or 5.0))
    except (TypeError, ValueError):
        disk["alignment_peak_multiplier"] = DEFAULT_PIPELINE_SETTINGS["disk_pressure"]["alignment_peak_multiplier"]
    try:
        disk["min_free_gb_before_markdup"] = max(0, int(disk.get("min_free_gb_before_markdup") or 0))
    except (TypeError, ValueError):
        disk["min_free_gb_before_markdup"] = DEFAULT_PIPELINE_SETTINGS["disk_pressure"]["min_free_gb_before_markdup"]
    disk["block_start_when_estimate_exceeds_free"] = bool(disk.get("block_start_when_estimate_exceeds_free"))
    disk["scratch_root"] = str(disk.get("scratch_root") or "").strip()
    taxonomy = settings["taxonomy"]
    if taxonomy.get("default_route") not in TAXONOMY_ROUTES:
        taxonomy["default_route"] = DEFAULT_PIPELINE_SETTINGS["taxonomy"]["default_route"]
    try:
        taxonomy["low_mapq_threshold"] = max(0, min(60, int(taxonomy.get("low_mapq_threshold") or 10)))
    except (TypeError, ValueError):
        taxonomy["low_mapq_threshold"] = DEFAULT_PIPELINE_SETTINGS["taxonomy"]["low_mapq_threshold"]
    return settings


def _save_pipeline_settings(settings: dict) -> dict:
    current = _pipeline_settings()
    backends = settings.get("backends") or {}
    if not isinstance(backends, dict):
        raise HTTPException(status_code=400, detail="backends_must_be_object")
    for stage, backend in backends.items():
        if stage not in BACKEND_OPTIONS:
            raise HTTPException(status_code=400, detail=f"unknown_stage:{stage}")
        if backend not in BACKEND_OPTIONS[stage]:
            raise HTTPException(status_code=400, detail=f"unsupported_backend:{stage}:{backend}")
        current["backends"][stage] = backend
    disk = settings.get("disk_pressure")
    if disk is not None:
        if not isinstance(disk, dict):
            raise HTTPException(status_code=400, detail="disk_pressure_must_be_object")
        if "alignment_peak_multiplier" in disk:
            current["disk_pressure"]["alignment_peak_multiplier"] = max(1.0, float(disk["alignment_peak_multiplier"]))
        if "min_free_gb_before_markdup" in disk:
            current["disk_pressure"]["min_free_gb_before_markdup"] = max(0, int(disk["min_free_gb_before_markdup"]))
        if "block_start_when_estimate_exceeds_free" in disk:
            current["disk_pressure"]["block_start_when_estimate_exceeds_free"] = bool(disk["block_start_when_estimate_exceeds_free"])
        if "scratch_root" in disk:
            current["disk_pressure"]["scratch_root"] = str(disk["scratch_root"] or "").strip()
    taxonomy = settings.get("taxonomy")
    if taxonomy is not None:
        if not isinstance(taxonomy, dict):
            raise HTTPException(status_code=400, detail="taxonomy_must_be_object")
        if "default_route" in taxonomy:
            route = str(taxonomy["default_route"] or "").strip()
            if route not in TAXONOMY_ROUTES:
                raise HTTPException(status_code=400, detail=f"unsupported_taxonomy_route:{route}")
            current["taxonomy"]["default_route"] = route
        if "low_mapq_threshold" in taxonomy:
            current["taxonomy"]["low_mapq_threshold"] = max(0, min(60, int(taxonomy["low_mapq_threshold"])))
    PIPELINE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIPELINE_SETTINGS_PATH.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    return current


def _pipeline_backend_status(settings: dict | None = None) -> dict:
    settings = settings or _pipeline_settings()
    status: dict[str, dict] = {}
    alignment_status: dict[str, dict] = {}
    for backend in BACKEND_OPTIONS.get("alignment", []):
        reference_status = {}
        for ref in references:
            fasta = Path(ref.fasta_path) if ref.fasta_path else None
            if fasta and fasta.exists():
                reference_status[ref.id] = _reference_alignment_backend_preflight(fasta, backend)
        installed = True if backend == "auto" else _backend_tool_available(backend)
        alignment_status[backend] = {
            "installed": installed,
            "tools": _tools_for_backend(backend),
            "requires_reference_index": backend in {"bwa", "bwa-mem2"},
            "reference_status": reference_status,
            "selected": settings.get("backends", {}).get("alignment", "auto") == backend,
        }
    status["alignment"] = alignment_status
    return status


def _pipeline_executor() -> str:
    raw = os.getenv(PIPELINE_EXECUTOR_ENV, PIPELINE_EXECUTOR_API_THREAD).strip().lower()
    if raw not in {PIPELINE_EXECUTOR_API_THREAD, PIPELINE_EXECUTOR_WORKER_QUEUE}:
        return PIPELINE_EXECUTOR_API_THREAD
    return raw


def _pipeline_executor_policy() -> dict:
    effective = _pipeline_executor()
    return {
        "effective_executor": effective,
        "configured_env": os.getenv(PIPELINE_EXECUTOR_ENV, PIPELINE_EXECUTOR_API_THREAD),
        "default_executor": PIPELINE_EXECUTOR_API_THREAD,
        "worker_queue_available": True,
        "worker_queue_default_blocked": True,
        "default_decision": "api_thread remains default until worker_queue is validated on a real long-running WGS alignment with pause/resume/cancel.",
        "promotion_requirements": [
            "Real full-WGS worker-owned alignment completes with shared DB/API status refresh.",
            "Pause, resume, cancel, and stage-boundary pause are verified while the worker owns the subprocess.",
            "Shared /data mounts, Redis, and DATABASE_URL are proven identical for API and worker containers.",
        ],
    }


def _host_ram_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None


def _gpu_available() -> bool:
    if os.getenv("WGS_GPU_AVAILABLE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if shutil.which("nvidia-smi"):
        try:
            return subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=3).returncode == 0
        except Exception:
            pass
    return any(Path("/dev").glob("nvidia*"))


def _auto_compute_profile(cpu_threads: int | None = None, ram_bytes: int | None = None) -> str:
    threads = cpu_threads or os.cpu_count() or 1
    ram_gb = (ram_bytes if ram_bytes is not None else _host_ram_bytes() or 0) / (1024 ** 3)
    if ram_gb and ram_gb < 48:
        return "lowmem"
    if ram_gb >= 128 and threads >= 16:
        return "highmem"
    return "standard"


def _compute_profile() -> str:
    raw = os.getenv(COMPUTE_PROFILE_ENV, "auto").strip().lower()
    if raw == "auto":
        return _auto_compute_profile()
    return raw if raw in COMPUTE_PROFILE_THREADS else _auto_compute_profile()


def _pipeline_threads() -> int:
    override = os.getenv(PIPELINE_THREADS_ENV, "").strip()
    if override.isdigit():
        return max(1, int(override))
    return COMPUTE_PROFILE_THREADS[_compute_profile()]


def _resource_plan() -> dict:
    ram_bytes = _host_ram_bytes()
    cpu_threads = os.cpu_count() or 1
    requested_profile = os.getenv(COMPUTE_PROFILE_ENV, "auto").strip().lower() or "auto"
    effective_profile = _compute_profile()
    explicit_threads = os.getenv(PIPELINE_THREADS_ENV, "").strip()
    settings = _pipeline_settings()
    backend_policy = dict(settings.get("backends") or {})
    return {
        "requested_profile": requested_profile,
        "effective_profile": effective_profile,
        "threads": _pipeline_threads(),
        "threads_source": "env" if explicit_threads.isdigit() else "profile",
        "cpu_threads": cpu_threads,
        "ram_bytes": ram_bytes,
        "ram_gb": round(ram_bytes / (1024 ** 3), 1) if ram_bytes else None,
        "gpu_available": _gpu_available(),
        "backend_policy": backend_policy,
        "executor_policy": _pipeline_executor_policy(),
        "reference_index_policy": "classic_bwa_low_memory",
        "silent_gpu_fallback": False,
        "disk_pressure": settings.get("disk_pressure", {}),
    }


@router.get("/pipeline/settings")
def get_pipeline_settings():
    settings = _pipeline_settings()
    return {
        "settings": settings,
        "backend_options": BACKEND_OPTIONS,
        "backend_status": _pipeline_backend_status(settings),
        "resource_plan": _resource_plan(),
        "executor_policy": _pipeline_executor_policy(),
        "taxonomy_routes": TAXONOMY_ROUTES,
    }


@router.put("/pipeline/settings")
def update_pipeline_settings(body: dict):
    settings = _save_pipeline_settings(body)
    return {
        "settings": settings,
        "backend_options": BACKEND_OPTIONS,
        "backend_status": _pipeline_backend_status(settings),
        "resource_plan": _resource_plan(),
        "executor_policy": _pipeline_executor_policy(),
        "taxonomy_routes": TAXONOMY_ROUTES,
    }


def _parse_redis_url(url: str) -> tuple[str, int]:
    raw = (url or REDIS_URL_DEFAULT).strip()
    if raw.startswith("redis://"):
        raw = raw[len("redis://") :]
    raw = raw.split("/", 1)[0]
    if "@" in raw:
        raw = raw.rsplit("@", 1)[1]
    host, _, port_s = raw.partition(":")
    return host or "redis", int(port_s or "6379")


def _redis_command(*parts: str, redis_url: str | None = None, timeout_seconds: float = 2.0) -> bytes:
    """Tiny RESP client for queue enqueue; avoids adding a runtime dependency before worker path is validated."""
    host, port = _parse_redis_url(redis_url or os.getenv(REDIS_URL_ENV, REDIS_URL_DEFAULT))
    payload = f"*{len(parts)}\r\n".encode("utf-8")
    for part in parts:
        b = str(part).encode("utf-8")
        payload += b"$" + str(len(b)).encode("ascii") + b"\r\n" + b + b"\r\n"
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        sock.sendall(payload)
        return sock.recv(4096)


def _enqueue_pipeline_job(job: PipelineJob) -> dict:
    queue_name = os.getenv(PIPELINE_JOB_QUEUE_ENV, PIPELINE_JOB_QUEUE_DEFAULT).strip() or PIPELINE_JOB_QUEUE_DEFAULT
    body = encode_pipeline_job(job)
    response = _redis_command("LPUSH", queue_name, body)
    if not response.startswith(b":"):
        raise RuntimeError(f"redis_enqueue_failed:{response[:80]!r}")
    return {"queue": queue_name, "redis_response": response.decode("utf-8", errors="replace").strip()}


def _run_pipeline_background_tracked(*args):
    run_id = args[0] if args else None
    if run_id:
        _ACTIVE_RUNNERS[str(run_id)] = True
    try:
        return _run_pipeline_background(*args)
    finally:
        if run_id:
            _ACTIVE_RUNNERS.pop(str(run_id), None)


def _dispatch_pipeline_job(job: PipelineJob) -> threading.Thread:
    thread = threading.Thread(
        target=_run_pipeline_background_tracked,
        args=pipeline_job_runner_args(job),
        daemon=True,
    )
    thread.start()
    return thread


# Stage execution order. `STANDARD_PIPELINE_STAGES` is the everyday full-WGS
# path; `PIPELINE_STAGES` also includes heavier advanced research modules.
STANDARD_PIPELINE_STAGES = [
    "alignment", "coverage", "variants", "annotation",
    "sv", "cnv", "taxonomy", "mtdna", "prs",
]
PIPELINE_STAGES = [*STANDARD_PIPELINE_STAGES, "unknown_reads", "benchmark"]

PIPELINE_STAGE_DEPENDENCIES = {
    "alignment": [],
    "coverage": ["alignment"],
    "variants": ["alignment"],
    "annotation": ["variants"],
    "sv": ["alignment"],
    "cnv": ["alignment"],
    "taxonomy": ["alignment"],
    "unknown_reads": ["alignment"],
    "mtdna": ["alignment"],
    "prs": ["variants"],
    "benchmark": ["variants"],
}

PIPELINE_BLOCKING_STATUSES = {"failed", "blocked", "cancelled", "interrupted"}


# Pipeline profiles
# required=True: fail if tool missing
# required=False: skip with warning if tool missing
PIPELINE_PROFILES = {
    "core_variants": {
        "name": "Core Variant Analysis",
        "description": "Alignment → Coverage → Variant calling (bcftools). Uses verified tools only.",
        "stages": ["alignment", "coverage", "variants"],
        "required_stages": {"alignment", "coverage", "variants"},
    },
    "full_strict": {
        "name": "Full Pipeline (Strict)",
        "description": "All stages. Fails immediately if any tool is missing.",
        "stages": PIPELINE_STAGES,
        "required_stages": set(PIPELINE_STAGES),
    },
    "full_optional": {
        "name": "Full Pipeline (Best Effort)",
        "description": "Core stages required, optional modules skipped if tools unavailable.",
        "stages": PIPELINE_STAGES,
        "required_stages": {"alignment", "coverage", "variants"},
    },
}


# Tool binaries required per optional stage
STAGE_REQUIRED_TOOLS = {
    "alignment": ["minimap2|bwa-mem2|bwa-mem2.avx512|bwa-mem2.avx2|bwa-mem2.sse42|bwa-mem2.sse41|bwa", "samtools"],
    "coverage": ["mosdepth", "samtools"],
    "variants": ["bcftools"],
    "annotation": ["vep|bcftools"],
    "sv": ["configManta.py|delly"],
    "cnv": ["cnvkit.py|cnvkit"],
    "taxonomy": ["kraken2"],
    "unknown_reads": ["samtools"],
    "mtdna": ["gatk"],
    "prs": [],
    "benchmark": ["hap.py|happy|truvari"],
}


def _check_stage_tools(stage_name: str) -> tuple[bool, list[str]]:
    """Check if required tools for a stage are installed. Each list entry can be a single tool or alternatives separated by |."""
    import shutil
    if stage_name == "variants":
        backend = _pipeline_settings().get("backends", {}).get("variants", "bcftools")
        tools = _tools_for_backend(backend)
        if tools:
            available = any(shutil.which(tool) for tool in tools)
            return available, [] if available else [tools[0]]

    tools = STAGE_REQUIRED_TOOLS.get(stage_name, [])
    missing = []
    for tool_entry in tools:
        alternatives = tool_entry.split("|")
        if not any(shutil.which(alt) for alt in alternatives):
            missing.append(alternatives[0])
    return len(missing) == 0, missing


def _tool_for_backend(backend: str) -> str | None:
    tools = _tools_for_backend(backend)
    return tools[0] if tools else None


def _validate_selected_backends(stages: list[str]) -> list[dict]:
    missing = []
    backends = _pipeline_settings()["backends"]
    for stage in stages:
        backend = backends.get(stage, "auto")
        tools = _tools_for_backend(backend)
        if tools and not any(shutil.which(tool) for tool in tools):
            missing.append({"stage": stage, "backend": backend, "tools": tools, "tool": tools[0]})
    return missing


def _taxonomy_db_available() -> bool:
    return any(Path("/data/databases/kraken2").glob("*/hash.k2d")) or Path("/data/databases/kraken2/hash.k2d").exists()


def _resolve_taxonomy_database_path(database: str | None) -> str | None:
    if not database:
        return None

    selected = database.strip()
    if not selected:
        return None

    direct = Path(selected)
    if direct.is_dir() and (direct / "hash.k2d").exists():
        return str(direct)

    try:
        from app.routers.data_ingest import TAXONOMY_DATABASES, TAXONOMY_DB_DIR
    except Exception:
        TAXONOMY_DATABASES = []
        TAXONOMY_DB_DIR = Path(os.getenv("WGS_KRAKEN_DB_DIR", "/data/databases/kraken2"))

    installed = TAXONOMY_DB_DIR / selected
    if installed.is_dir() and (installed / "hash.k2d").exists():
        return str(installed)

    db_info = next((d for d in TAXONOMY_DATABASES if d.get("id") == selected), None)
    if db_info and db_info.get("path"):
        custom = Path(str(db_info["path"]))
        if custom.is_dir() and (custom / "hash.k2d").exists():
            return str(custom)

    raise HTTPException(
        status_code=404,
        detail={
            "code": "taxonomy_database_not_installed",
            "message": f"Taxonomy database '{selected}' is not installed or is missing hash.k2d.",
            "database": selected,
        },
    )


def _reference_has_mtdna(reference_fasta: Path) -> bool:
    fai = Path(str(reference_fasta) + ".fai")
    try:
        if fai.exists():
            return any(line.split("\t", 1)[0] in {"chrM", "MT", "M"} for line in fai.read_text(encoding="utf-8", errors="ignore").splitlines())
        with reference_fasta.open("rt", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if line.startswith(">"):
                    name = line[1:].strip().split()[0]
                    if name in {"chrM", "MT", "M"}:
                        return True
    except Exception:
        return False
    return False


def _optional_stage_preflight_skip(stage_name: str, reference_fasta: Path) -> str | None:
    """Return a clean skip reason for optional stages that are not configured for this run."""
    if stage_name == "prs":
        return "PRS panel not configured — curated PGS Catalog manifest required"
    if stage_name == "taxonomy" and not _taxonomy_db_available():
        return "Kraken2 database not installed"
    if stage_name == "mtdna" and not _reference_has_mtdna(reference_fasta):
        return "Reference has no mitochondrial contig (chrM/MT); mtDNA stage not applicable"
    if stage_name == "benchmark" and not os.getenv("WGS_BENCHMARK_TRUTH_VCF"):
        return "Benchmark truth VCF not configured"
    return None


def _get_pipeline_profiles_info() -> list[dict]:
    """Return all profiles with tool availability status."""
    result = []
    for pid, prof in PIPELINE_PROFILES.items():
        stage_info = []
        for stage in prof["stages"]:
            tools_ok, missing = _check_stage_tools(stage)
            is_required = stage in prof["required_stages"]
            stage_info.append({
                "name": stage,
                "required": is_required,
                "tools_ok": tools_ok,
                "missing": missing,
            })
        all_required_ok = all(
            si["tools_ok"] for si in stage_info if si["required"]
        )
        result.append({
            "id": pid,
            "name": prof["name"],
            "description": prof["description"],
            "stages": stage_info,
            "ready": all_required_ok,
        })
    return result


INGEST_FILES = {
    "alignment": "{sample}.alignment.ingest.json",
    "coverage": "{sample}.coverage.ingest.json",
    "variants": "{sample}.variants.bcftools.ingest.json",
    "annotation": "{sample}.annotation.ingest.json",
    "sv": "{sample}.sv.ingest.json",
    "cnv": "{sample}.cnv.ingest.json",
    "taxonomy": "{sample}.taxonomy.ingest.json",
    "unknown_reads": "{sample}.unknown_reads.ingest.json",
    "mtdna": "{sample}.mtdna.ingest.json",
    "prs": "{sample}.prs.ingest.json",
    "benchmark": "{sample}.benchmark.ingest.json",
}


def _resolve_pipeline_input(path: str) -> str:
    """Resolve UI-selected input files from /data/input when stored as relative names."""
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str(Path("/data/input") / p)


def _mate_fastq_name(path: str) -> str | None:
    """Return expected mate filename for common paired-end FASTQ naming patterns."""
    name = Path(path).name
    replacements = [
        ("_R1.fastq.gz", "_R2.fastq.gz"), ("_R2.fastq.gz", "_R1.fastq.gz"),
        ("_R1.fq.gz", "_R2.fq.gz"), ("_R2.fq.gz", "_R1.fq.gz"),
        ("_1.fastq.gz", "_2.fastq.gz"), ("_2.fastq.gz", "_1.fastq.gz"),
        ("_1.fq.gz", "_2.fq.gz"), ("_2.fq.gz", "_1.fq.gz"),
    ]
    for old, new in replacements:
        if name.endswith(old):
            return str(Path(path).with_name(name[: -len(old)] + new))
    return None


def _normalize_fastq_pair(input_files: list[str]) -> tuple[list[str], list[str]]:
    """Order FASTQ pair as R1,R2 and auto-add mate from /data/input when obvious."""
    files = list(input_files)
    notes: list[str] = []
    if not files:
        return files, notes

    resolved = [_resolve_pipeline_input(f) for f in files]
    lower = [Path(f).name.lower() for f in resolved]
    fastqs = [f for f in resolved if f.lower().endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq"))]
    if not fastqs:
        return files, notes

    r1 = next((f for f in resolved if re.search(r"(_r?1)(?:\.f(?:ast)?q(?:\.gz)?)$", Path(f).name, re.I)), None)
    r2 = next((f for f in resolved if re.search(r"(_r?2)(?:\.f(?:ast)?q(?:\.gz)?)$", Path(f).name, re.I)), None)

    if not r1 and r2:
        mate = _mate_fastq_name(r2)
        if mate and Path(mate).exists():
            r1 = mate
            notes.append(f"auto-added mate R1: {Path(mate).name}")
    if r1 and not r2:
        mate = _mate_fastq_name(r1)
        if mate and Path(mate).exists():
            r2 = mate
            notes.append(f"auto-added mate R2: {Path(mate).name}")

    if r1 and r2:
        return [r1, r2], notes
    return resolved, notes


def _primary_bam_input(input_files: list[str]) -> str | None:
    for path in input_files:
        resolved = _resolve_pipeline_input(path)
        if resolved.lower().endswith(".bam"):
            return resolved
    return None


def _bam_index_ready(path: Path) -> bool:
    candidates = [Path(str(path) + ".bai"), path.with_suffix(".bai")]
    return any(candidate.exists() and candidate.stat().st_size > 0 for candidate in candidates)


def _bam_sort_order(path: Path) -> tuple[str | None, str | None]:
    if not shutil.which("samtools"):
        return None, "samtools_unavailable"
    try:
        completed = subprocess.run(
            ["samtools", "view", "-H", str(path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "bam_header_probe_timeout"
    except Exception as exc:
        return None, f"bam_header_probe_failed:{type(exc).__name__}"
    if completed.returncode != 0:
        return None, "bam_header_unreadable"
    for line in completed.stdout.splitlines():
        if not line.startswith("@HD"):
            continue
        for field in line.split("\t"):
            if field.startswith("SO:"):
                return field[3:] or None, None
    return None, "bam_sort_order_missing"


def _bam_pipeline_preflight(path: Path) -> dict:
    sort_order, sort_warning = _bam_sort_order(path)
    sorted_ready = sort_order == "coordinate"
    index_ready = _bam_index_ready(path)
    warnings: list[str] = []
    if not index_ready:
        warnings.append("bam_index_missing")
    if not sorted_ready:
        warnings.append("bam_not_coordinate_sorted" if sort_order else (sort_warning or "bam_sort_order_unknown"))
    return {
        "required": True,
        "ready": sorted_ready and index_ready,
        "index_ready": index_ready,
        "sorted": sorted_ready,
        "sort_order": sort_order,
        "warnings": warnings,
        "prepare_action": "sort_and_index" if not sorted_ready else ("index" if not index_ready else None),
        "can_prepare": bool(shutil.which("samtools")),
    }


def _valid_bam_checkpoint(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    if not shutil.which("samtools"):
        return False
    try:
        completed = subprocess.run(
            ["samtools", "quickcheck", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _alignment_checkpoint_status(run: Run, sample: Sample | None = None) -> dict:
    sample = sample or next((s for s in samples if s.id == run.sample_id), None)
    sample_name = sample.sample_id if sample else run.sample_id
    output_dir = PIPELINE_RESULTS_ROOT / run.id
    checkpoints = []
    restartable = False
    best = None
    for suffix, kind in ALIGNMENT_CHECKPOINT_SUFFIXES:
        path = output_dir / f"{sample_name}{suffix}"
        exists = path.exists()
        size_bytes = path.stat().st_size if exists and path.is_file() else 0
        valid = _valid_bam_checkpoint(path) if exists else False
        item = {
            "stage": "alignment",
            "kind": kind,
            "path": str(path),
            "exists": exists,
            "size_bytes": size_bytes,
            "valid": valid,
        }
        checkpoints.append(item)
        if valid and best is None:
            restartable = True
            best = item

    return {
        "run_id": run.id,
        "sample_id": sample_name,
        "output_dir": str(output_dir),
        "alignment": {
            "restartable": restartable,
            "best_checkpoint": best,
            "checkpoints": checkpoints,
            "message": (
                "Valid alignment checkpoint found; resume can reuse existing work."
                if restartable
                else "No valid alignment checkpoint found. Restarting alignment would remap from FASTQ."
            ),
        },
    }


def _run_step_status(run_id: str, stage_name: str) -> str | None:
    step = next((s for s in run_steps if s.run_id == run_id and s.step_name == stage_name), None)
    return step.status if step else None


def _known_stage_list() -> list[str]:
    return list(PIPELINE_STAGES)


def _validate_stage_list(stage_names: list[str] | None, field_name: str) -> list[str]:
    if not stage_names:
        return []
    known = set(_known_stage_list())
    invalid = [stage for stage in stage_names if stage not in known]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_pipeline_stage",
                "field": field_name,
                "invalid": invalid,
                "known_stages": _known_stage_list(),
            },
        )
    out: list[str] = []
    for stage in stage_names:
        if stage not in out:
            out.append(stage)
    return out


def _ordered_stage_subset(stage_names: list[str]) -> list[str]:
    requested = set(stage_names)
    return [stage for stage in PIPELINE_STAGES if stage in requested]


def _sample_output_prefix(run: Run, sample: Sample | None = None) -> tuple[Path, str]:
    sample = sample or next((s for s in samples if s.id == run.sample_id), None)
    sample_name = sample.sample_id if sample else run.sample_id
    return PIPELINE_RESULTS_ROOT / run.id, sample_name


def _final_alignment_ready(run: Run, sample: Sample | None = None) -> bool:
    output_dir, sample_name = _sample_output_prefix(run, sample)
    bam = output_dir / f"{sample_name}.sorted.markdup.bam"
    bai = output_dir / f"{sample_name}.sorted.markdup.bam.bai"
    return bam.exists() and bai.exists() and _valid_bam_checkpoint(bam)


def _final_alignment_bam_path(run: Run, sample: Sample | None = None) -> Path | None:
    output_dir, sample_name = _sample_output_prefix(run, sample)
    bam = output_dir / f"{sample_name}.sorted.markdup.bam"
    bai = output_dir / f"{sample_name}.sorted.markdup.bam.bai"
    if bam.exists() and bai.exists() and _valid_bam_checkpoint(bam):
        return bam
    return None


def _coverage_ready(run: Run, sample: Sample | None = None) -> bool:
    output_dir, sample_name = _sample_output_prefix(run, sample)
    return (
        (output_dir / f"{sample_name}.coverage.ingest.json").exists()
        or (output_dir / f"{sample_name}.mosdepth.summary.txt").exists()
    )


def _variants_ready(run: Run, sample: Sample | None = None) -> bool:
    output_dir, sample_name = _sample_output_prefix(run, sample)
    return (
        (output_dir / f"{sample_name}.variants.bcftools.ingest.json").exists()
        or _existing_variant_vcf_path(run, sample) is not None
    )


def _existing_variant_vcf_path(run: Run, sample: Sample | None = None) -> Path | None:
    output_dir, sample_name = _sample_output_prefix(run, sample)
    candidates = [
        output_dir / f"{sample_name}.variants.normalized.vcf",
        output_dir / f"{sample_name}.variants.annotated.vcf",
        output_dir / f"{sample_name}.bcftools.raw.vcf",
        output_dir / f"{sample_name}.bcftools.raw.vcf.gz",
        output_dir / f"{sample_name}.gatk.hc.raw.vcf",
        output_dir / f"{sample_name}.deepvariant.raw.vcf",
    ]
    return next((path for path in candidates if path.exists()), None)


def _variant_artifact_status(run: Run, sample: Sample | None = None) -> dict:
    sample_key = sample.sample_id if sample else run.sample_id
    imported_count = len([v for v in variants if v.run_id == run.id])
    vcf_path = _existing_variant_vcf_path(run, sample)
    output_dir, sample_name = _sample_output_prefix(run, sample)
    ingest_path = output_dir / f"{sample_name}.variants.bcftools.ingest.json"
    if imported_count:
        state = "imported"
        action = "ready"
    elif vcf_path:
        state = "vcf_exists_import_needed"
        action = "import_existing_vcf"
    else:
        state = "calling_needed"
        action = "run_variants_stage"
    return {
        "run_id": run.id,
        "sample_id": sample_key,
        "state": state,
        "action": action,
        "imported_variant_count": imported_count,
        "existing_vcf_path": str(vcf_path) if vcf_path else None,
        "ingest_contract_path": str(ingest_path) if ingest_path.exists() else None,
        "notes": {
            "vcf_import_is_fast_path": "Importing an existing VCF should be much faster than variant calling from BAM.",
            "variant_calling_is_expensive_path": "Calling variants from BAM may take hours on whole-genome data.",
        },
    }


def _stage_artifact_ready(stage_name: str, run: Run, sample: Sample | None = None) -> bool:
    if stage_name == "alignment":
        return _final_alignment_ready(run, sample)
    if stage_name == "coverage":
        return _coverage_ready(run, sample)
    if stage_name == "variants":
        return _variants_ready(run, sample)
    return False


def _input_bam_ready(input_files: list[str] | None = None) -> bool:
    input_bam = _primary_bam_input(input_files or [])
    if not input_bam:
        return False
    try:
        return bool(_bam_pipeline_preflight(Path(_resolve_pipeline_input(input_bam))).get("ready"))
    except Exception:
        return False


def _stage_dependency_closure(stage_name: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    def visit(stage: str):
        for dep in PIPELINE_STAGE_DEPENDENCIES.get(stage, []):
            if dep in seen:
                continue
            seen.add(dep)
            visit(dep)
            ordered.append(dep)

    visit(stage_name)
    return ordered


def _blocking_stage_dependency(
    stage_name: str,
    planned_stages: set[str],
    stage_outcomes: dict[str, str],
    run: Run,
    sample: Sample | None = None,
) -> tuple[str, str] | None:
    for dep in _stage_dependency_closure(stage_name):
        if dep not in planned_stages:
            continue
        status = stage_outcomes.get(dep) or _run_step_status(run.id, dep)
        if status in PIPELINE_BLOCKING_STATUSES:
            return dep, status
        if status == "skipped" and not _stage_artifact_ready(dep, run, sample):
            return dep, status
    return None


def _blocked_stage_result(stage_name: str, dependency: str, dependency_status: str) -> dict[str, str]:
    return {
        "stage": stage_name,
        "status": "blocked",
        "reason": f"dependency_unavailable:{dependency}",
        "dependency": dependency,
        "dependency_status": dependency_status,
    }


def _validate_stage_dependencies(run: Run, sample: Sample, stages: list[str], input_files: list[str] | None = None) -> None:
    needs_final_bam = {"coverage", "variants", "sv", "cnv", "taxonomy", "unknown_reads", "mtdna"}.intersection(stages)
    if (
        needs_final_bam
        and "alignment" not in stages
        and not _final_alignment_ready(run, sample)
        and not _input_bam_ready(input_files)
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stage_plan_missing_final_bam",
                "message": "Selected stages require an existing final sorted.markdup BAM and BAI because alignment is not in the plan.",
                "stages": sorted(needs_final_bam),
            },
        )
    if {"annotation", "prs", "benchmark"}.intersection(stages) and "variants" not in stages and not _variants_ready(run, sample):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stage_plan_missing_variant_vcf",
                "message": "Annotation/PRS/benchmark requires an existing variant VCF because variants is not in the plan.",
            },
        )


def _operator_skip_payload(run: Run) -> tuple[set[str], dict[str, str]]:
    params = run.parameters or {}
    skips = set(params.get("skip_stages") or [])
    skips.update(_STAGE_SKIP_FLAGS.get(run.id, set()))
    reasons = params.get("skip_reasons") if isinstance(params.get("skip_reasons"), dict) else {}
    return skips, reasons


def _path_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return 0


def _nearest_existing_path(path: Path) -> Path:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe if probe.exists() else Path("/")


def _read_json_if_exists(path: Path) -> dict | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _disk_usage(path: Path) -> dict:
    target = _nearest_existing_path(path)
    usage = shutil.disk_usage(target)
    return {
        "path": str(target),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_gb": round(usage.free / (1024 ** 3), 1),
    }


def _estimate_pipeline_peak_bytes(input_files: list[str], stages: list[str]) -> int:
    input_bytes = 0
    for raw in input_files:
        try:
            input_bytes += Path(_resolve_pipeline_input(raw)).stat().st_size
        except Exception:
            pass

    settings = _pipeline_settings().get("disk_pressure", {})
    multiplier = float(settings.get("alignment_peak_multiplier") or 5.0)
    estimate = 0
    if "alignment" in stages:
        # Human 30x FASTQ commonly peaks at several BAM-sized intermediates:
        # name-sorted, fixmate, coord-sorted, final markdup, plus transient temp.
        estimate += max(int(input_bytes * multiplier), 240 * 1024 ** 3)
    if {"coverage", "variants", "annotation"}.intersection(stages):
        estimate += 40 * 1024 ** 3
    if {"sv", "cnv", "mtdna", "prs", "taxonomy", "unknown_reads"}.intersection(stages):
        estimate += 20 * 1024 ** 3
    return estimate


def _pipeline_disk_preflight(input_files: list[str], stages: list[str], output_dir: Path) -> dict:
    settings = _pipeline_settings().get("disk_pressure", {})
    usage = _disk_usage(output_dir)
    estimated_peak = _estimate_pipeline_peak_bytes(input_files, stages)
    min_markdup_bytes = int(settings.get("min_free_gb_before_markdup", 0)) * 1024 ** 3
    required_bytes = max(estimated_peak, min_markdup_bytes)
    free_bytes = int(usage["free_bytes"])
    ok = free_bytes >= required_bytes if required_bytes else True
    status = "ok" if ok else ("blocked" if settings.get("block_start_when_estimate_exceeds_free") else "warning")
    return {
        "status": status,
        "output_root": str(output_dir),
        "usage": usage,
        "estimated_peak_bytes": estimated_peak,
        "estimated_peak_gb": round(estimated_peak / (1024 ** 3), 1) if estimated_peak else 0,
        "required_free_bytes": required_bytes,
        "required_free_gb": round(required_bytes / (1024 ** 3), 1) if required_bytes else 0,
        "free_bytes": free_bytes,
        "free_gb": usage["free_gb"],
        "block_start_when_estimate_exceeds_free": bool(settings.get("block_start_when_estimate_exceeds_free")),
        "alignment_peak_multiplier": settings.get("alignment_peak_multiplier"),
        "min_free_gb_before_markdup": settings.get("min_free_gb_before_markdup"),
        "scratch_root": settings.get("scratch_root") or "",
    }


def _resolve_taxonomy_route(route: str | None) -> str:
    selected = (route or _pipeline_settings().get("taxonomy", {}).get("default_route") or "").strip()
    if selected not in TAXONOMY_ROUTES:
        raise HTTPException(status_code=400, detail={"code": "unsupported_taxonomy_route", "route": selected})
    return selected


def _taxonomy_low_mapq_threshold(value: int | None) -> int:
    if value is None:
        value = _pipeline_settings().get("taxonomy", {}).get("low_mapq_threshold", 10)
    return max(0, min(60, int(value)))


def _stage_artifact_paths(result: dict) -> list[str]:
    output_dir = Path(result.get("output_dir") or "")
    if not output_dir.exists():
        return []
    stage = str(result.get("stage") or "").strip()
    sample_patterns = {
        "alignment": ["*.sorted.markdup.bam", "*.sorted.markdup.bam.bai", "*.flagstat.txt", "*.idxstats.txt", "*.alignment.ingest.json"],
        "coverage": ["*.mosdepth.summary.txt", "*.regions.bed.gz", "*.coverage.tiles.*.json", "*.coverage.ingest.json"],
        "variants": ["*.bcftools.raw.vcf", "*.bcftools.raw.vcf.gz", "*.gatk.hc.raw.vcf", "*.deepvariant.raw.vcf", "*.variants.*.ingest.json"],
        "annotation": ["*.variants.annotated.vcf", "*.variants.annotated.vcf.gz", "*.annotation.ingest.json"],
        "sv": ["*.sv.*", "*.sv.ingest.json"],
        "cnv": ["*.cnv.*", "*.cnv.ingest.json"],
        "taxonomy": ["*.kraken2.report", "*.kraken2.output", "*.bracken.tsv", "*.taxonomy.ingest.json", "*.host_unmapped_R*.fastq.gz"],
        "unknown_reads": ["*.unknown_reads.ingest.json", "*_unknown_reads/*"],
        "mtdna": ["*.mtdna.*", "*.mtdna.ingest.json"],
        "prs": ["*.prs.*", "*.prs.ingest.json"],
        "benchmark": ["*.benchmark.*", "*.benchmark.ingest.json"],
    }
    paths: list[str] = []
    for pattern in sample_patterns.get(stage, [f"*.{stage}.*"]):
        paths.extend(str(path) for path in output_dir.glob(pattern) if path.is_file())
    return sorted(set(paths))[:100]


def _record_stage_execution(run_id: str, result: dict) -> None:
    payload = {
        "stage": result.get("stage"),
        "status": result.get("status"),
        "returncode": result.get("returncode"),
        "reason": result.get("reason"),
        "command": result.get("command"),
        "script_path": result.get("script_path"),
        "output_dir": result.get("output_dir"),
        "stdout_tail": result.get("stdout", "")[-2000:] if result.get("stdout") else "",
        "stderr_tail": result.get("stderr", "")[-2000:] if result.get("stderr") else "",
        "artifact_paths": _stage_artifact_paths(result),
    }
    _emit_run_event(run_id, "stage_execution_recorded", {k: v for k, v in payload.items() if v not in (None, "", [])})


def _alignment_temp_artifacts(run: Run, sample: Sample | None = None) -> list[dict]:
    sample = sample or next((s for s in samples if s.id == run.sample_id), None)
    sample_name = sample.sample_id if sample else run.sample_id
    output_dir = PIPELINE_RESULTS_ROOT / run.id
    artifacts: list[Path] = []
    for pattern in ALIGNMENT_TEMP_FILE_GLOBS:
        artifacts.extend(path for path in output_dir.glob(f"{sample_name}{pattern}") if path.is_file())
    artifacts.extend(path for path in output_dir.glob(f"{sample_name}.alignment_tmp.*") if path.is_dir())

    items = []
    for path in sorted(set(artifacts)):
        items.append(
            {
                "path": str(path),
                "name": path.name,
                "kind": "directory" if path.is_dir() else "file",
                "size_bytes": _path_size_bytes(path),
            }
        )
    return items


def _absolutize_ingest_path(value, output_dir: Path):
    if isinstance(value, str) and value and not Path(value).is_absolute():
        return str(output_dir / value)
    return value


def _absolutize_ingest_payload(payload: dict, output_dir: Path) -> dict:
    """Stage scripts emit relative paths. API parsers need absolute paths."""
    out = dict(payload)
    path_keys = {
        "flagstat_txt", "idxstats_txt", "fastqc_data_txt", "multiqc_json",
        "mosdepth_summary_txt", "mosdepth_regions_bed_gz", "variants_vcf_path",
        "sv_vcf_path", "cnv_segments_tsv_path", "cnv_vcf_path", "mtdna_report_path",
        "mtdna_vcf_path", "prs_result_path", "taxonomy_report_path",
        "unknown_r1", "unknown_r2", "host_unmapped_r1", "host_unmapped_r2", "host_bam",
    }
    for key in path_keys:
        if key in out:
            out[key] = _absolutize_ingest_path(out.get(key), output_dir)
    if isinstance(out.get("source_files"), list):
        out["source_files"] = [_absolutize_ingest_path(f, output_dir) for f in out["source_files"]]
    if isinstance(out.get("files"), dict):
        out["files"] = {key: _absolutize_ingest_path(value, output_dir) for key, value in out["files"].items()}
    return out


def _variant_calling_backend(stage_options: dict | None = None) -> str:
    return core_variant_calling_backend(
        stage_options,
        default_backend=_pipeline_settings().get("backends", {}).get("variants", "bcftools"),
    )


def _stage_script_name(stage_name: str, stage_options: dict | None = None) -> str | None:
    return core_stage_script_name(
        stage_name,
        stage_options,
        default_variant_backend=_pipeline_settings().get("backends", {}).get("variants", "bcftools"),
    )


def _run_stage_script(stage_name: str, sample_id: str, input_files: list[str],
                      reference_fasta: Path, reference_id: str, threads: int,
                      output_dir: Path, allow_dev: bool = True, run_id: str | None = None,
                      stage_options: dict | None = None) -> dict:
    """Execute a pipeline stage script and return the result."""
    stage_options = stage_options or {}
    script_name = _stage_script_name(stage_name, stage_options)
    if not script_name:
        return {"stage": stage_name, "status": "skipped", "reason": "unknown_stage"}

    script_path = find_stage_script(script_name)
    if not script_path:
        return {"stage": stage_name, "status": "skipped", "reason": "script_not_found"}

    try:
        script_path = sanitize_stage_script(script_path, output_dir, stage_name)
    except Exception as e:
        return {"stage": stage_name, "status": "failed", "reason": f"script_sanitize_failed:{e}"}

    r1 = _resolve_pipeline_input(input_files[0]) if input_files else ""
    r2 = _resolve_pipeline_input(input_files[1]) if len(input_files) > 1 else ""
    input_bam = _primary_bam_input(input_files)
    bam = input_bam or str(output_dir / f"{sample_id}.sorted.markdup.bam")
    vcf = str(output_dir / f"{sample_id}.bcftools.raw.vcf")
    allow_fallback = "true" if allow_dev else "false"
    ref = str(reference_fasta)
    cmd = build_stage_command(
        stage_name=stage_name,
        script_path=script_path,
        sample_id=sample_id,
        reference_fasta=ref,
        r1=r1,
        r2=r2,
        bam=bam,
        vcf=vcf,
        reference_id=reference_id,
        threads=threads,
        allow_fallback=allow_fallback,
        stage_options=stage_options,
        taxonomy_route=stage_options.get("taxonomy_route") or _resolve_taxonomy_route(None),
        taxonomy_low_mapq_threshold=int(stage_options.get("taxonomy_low_mapq_threshold") or _taxonomy_low_mapq_threshold(None)),
        default_variant_backend=_pipeline_settings().get("backends", {}).get("variants", "bcftools"),
        deepvariant_model_default=os.getenv("WGS_DEEPVARIANT_MODEL", "WGS"),
    )
    if not cmd:
        return {"stage": stage_name, "status": "skipped", "reason": "unsupported_stage"}

    read_estimate = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        settings = _pipeline_settings()
        env["WGS_ALIGNMENT_BACKEND"] = settings["backends"].get("alignment", "auto")
        disk_settings = settings.get("disk_pressure", {})
        if stage_name == "alignment":
            env["WGS_MARKDUP_MIN_FREE_GB"] = str(disk_settings.get("min_free_gb_before_markdup", 0))
            scratch_root = str(disk_settings.get("scratch_root") or "").strip()
            if scratch_root:
                env["WGS_ALIGNMENT_SCRATCH_ROOT"] = scratch_root
        if stage_name == "alignment" and not input_bam:
            try:
                read_estimate = estimate_fastq_input_reads([f for f in [r1, r2] if f])
                estimated_total = read_estimate.get("estimated_total_reads") if read_estimate else None
                if estimated_total:
                    env["WGS_TOTAL_READS_ESTIMATE"] = str(int(estimated_total))
                    env["WGS_TOTAL_READS_ESTIMATE_SOURCE"] = str(read_estimate.get("method") or "fastq_read_estimate")
                    env["WGS_TOTAL_READS_ESTIMATE_EXACT"] = "true" if read_estimate.get("exact") else "false"
            except Exception as exc:
                read_estimate = {"error": str(exc)}
        proc = subprocess.Popen(
            cmd,
            cwd=output_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=env,
        )
        # Track by run id so cancelling one run cannot kill another run's stage.
        process_key = run_id or f"untracked:{id(proc)}"
        _ACTIVE_PROCESSES[process_key] = proc
        timeout_seconds = STAGE_TIMEOUTS.get(stage_name, int(os.getenv("PIPELINE_STAGE_TIMEOUT_SECONDS", "7200")))
        if run_id:
            _emit_run_event(
                run_id,
                f"{stage_name}_process_started",
                {
                    "pid": proc.pid,
                    "timeout_seconds": timeout_seconds,
                    "command": " ".join(cmd),
                    "output_dir": str(output_dir),
                    "alignment_backend_policy": env.get("WGS_ALIGNMENT_BACKEND") if stage_name == "alignment" else None,
                    "fastq_read_estimate": read_estimate if stage_name == "alignment" else None,
                },
            )
            # Write initial live metrics so frontend shows 'starting' state immediately
            if stage_name == "alignment":
                import json as _json
                _live_metrics_path = output_dir / "live_metrics.json"
                estimated_total = read_estimate.get("estimated_total_reads") if isinstance(read_estimate, dict) else None
                estimate_exact = bool(read_estimate.get("exact")) if isinstance(read_estimate, dict) else False
                try:
                    _live_metrics_path.parent.mkdir(parents=True, exist_ok=True)
                    _live_metrics_path.write_text(_json.dumps({
                        "run_id": run_id,
                        "sample_id": sample_id,
                        "alignment_backend_policy": env.get("WGS_ALIGNMENT_BACKEND"),
                        "alignment_backend": None,
                        "metric_source": "pending_sam_stdout",
                        "progress_basis": "estimated_primary_sam_records" if estimated_total and not estimate_exact else "primary_sam_records",
                        "status": "starting",
                        "timestamp": time.time(),
                        "primary_reads_processed": 0,
                        "primary_reads_mapped": 0,
                        "primary_reads_unmapped": 0,
                        "total_reads_available": bool(estimated_total),
                        "total_reads_known": bool(estimated_total and estimate_exact),
                        "total_reads_estimated": bool(estimated_total and not estimate_exact),
                        "total_reads_source": read_estimate.get("method") if isinstance(read_estimate, dict) else None,
                        "total_reads": int(estimated_total) if estimated_total else None,
                        "fastq_read_estimate": read_estimate,
                        "mapped_pct": 0,
                        "unmapped_pct": 0,
                        "reads_per_sec": 0,
                        "progress_pct": None,
                        "eta_sec": None,
                        "eta_confidence": "estimated" if estimated_total and not estimate_exact else "unknown",
                        "chromosomes": [],
                        "mapped_contigs_total": 0,
                        "mapq_histogram": {},
                    }))
                except Exception:
                    pass
        try:
            stdout, stderr = _communicate_stage_process(
                proc,
                run_id=run_id,
                stage_name=stage_name,
                timeout_seconds=timeout_seconds,
            )
        finally:
            _ACTIVE_PROCESSES.pop(process_key, None)
        return {
            "stage": stage_name,
            "status": "done" if proc.returncode == 0 else ("paused" if stage_name == "alignment" and proc.returncode == 75 else "failed"),
            "returncode": proc.returncode,
            "script_path": script_path,
            "output_dir": str(output_dir),
            "command": " ".join(cmd),
            "stdout": stdout[-2000:] if stdout else "",
            "stderr": stderr[-1000:] if stderr else "",
            **(
                {"reason": "disk_pressure_before_markdup", "disk_pressure": _read_json_if_exists(output_dir / f"{sample_id}.alignment.disk_pressure.json")}
                if stage_name == "alignment" and proc.returncode == 75 else {}
            ),
        }
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                stdout, stderr = proc.communicate()
        except Exception:
            proc.kill()
            stdout, stderr = proc.communicate()
        if run_id:
            _ACTIVE_PROCESSES.pop(run_id, None)
        timeout_seconds = STAGE_TIMEOUTS.get(stage_name, int(os.getenv("PIPELINE_STAGE_TIMEOUT_SECONDS", "7200")))
        return {
            "stage": stage_name,
            "status": "failed",
            "reason": f"timeout after {timeout_seconds}s",
            "script_path": script_path,
            "output_dir": str(output_dir),
            "command": " ".join(cmd),
            "stdout": stdout[-2000:] if stdout else "",
            "stderr": stderr[-2000:] if stderr else "",
        }
    except Exception as e:
        if run_id:
            _ACTIVE_PROCESSES.pop(run_id, None)
        return {"stage": stage_name, "status": "failed", "reason": str(e)}


def _mark_remaining_after_required_failure(
    run_id: str,
    remaining_stages: list[str],
    failed_stage: str,
    planned_stages: set[str],
    stage_outcomes: dict[str, str],
    run: Run,
    sample: Sample | None,
) -> list[dict]:
    results: list[dict] = []
    for skipped_stage in remaining_stages:
        blocking = _blocking_stage_dependency(skipped_stage, planned_stages, stage_outcomes, run, sample)
        if blocking:
            dependency, dependency_status = blocking
            blocked = _blocked_stage_result(skipped_stage, dependency, dependency_status)
            _add_run_step(
                run_id,
                skipped_stage,
                "blocked",
                0,
                last_log=f"Blocked because dependency {dependency} is {dependency_status}",
            )
            _emit_run_event(run_id, f"{skipped_stage}_blocked", blocked)
            stage_outcomes[skipped_stage] = "blocked"
            results.append(blocked)
            continue

        skipped = {
            "stage": skipped_stage,
            "status": "skipped",
            "reason": f"stop_on_failure:{failed_stage}",
            "failed_stage": failed_stage,
        }
        _add_run_step(
            run_id,
            skipped_stage,
            "skipped",
            0,
            last_log=f"Skipped by stop_on_failure policy after {failed_stage} failed",
        )
        _emit_run_event(run_id, f"{skipped_stage}_skipped", skipped)
        stage_outcomes[skipped_stage] = "skipped"
        results.append(skipped)
    return results


def _run_pipeline_background(run_id: str, sample_id: str, input_files: list[str],
                            reference_id: str, stages: list[str], allow_dev_fallback: bool,
                            stop_on_failure: bool, required_stages: set[str] | None = None,
                            profile_name: str | None = None, optional_tools_missing: list | None = None,
                            stage_options: dict | None = None):
    """Run pipeline stages in background thread."""
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        return

    required_stages = required_stages or set(stages)
    stage_options = stage_options or {}
    planned_stages = set(stages)
    stage_outcomes: dict[str, str] = {}
    sample = next((s for s in samples if s.id == run.sample_id), None)

    while run.status == "paused" or _PAUSE_FLAGS.get(run_id):
        time.sleep(1)
        refresh_from_db(recover_stale_running=False)
        run = next((r for r in runs if r.id == run_id), None)
        if not run:
            return
        if run.status == "cancelling" or _CANCEL_FLAGS.get(run_id):
            run.status = "cancelled"
            run.updated_at = datetime.now(timezone.utc).isoformat()
            save_run(run)
            _emit_run_event(run_id, "pipeline_cancelled", {"reason": "user_cancelled_while_paused"})
            _CANCEL_FLAGS.pop(run_id, None)
            _PAUSE_FLAGS.pop(run_id, None)
            _STAGE_SKIP_FLAGS.pop(run_id, None)
            return

    run.status = "running"
    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)
    _emit_run_event(
        run_id,
        "pipeline_started",
        {
            "stages": stages,
            "profile": profile_name,
            "allow_dev_fallback": allow_dev_fallback,
            "stop_on_failure": stop_on_failure,
            "required_stages": list(required_stages),
            "optional_tools_missing": optional_tools_missing or [],
            "resource_plan": _resource_plan(),
            "stage_options": stage_options,
        },
    )

    reference_preflight = _reference_pipeline_preflight(reference_id, stages)
    reference_fasta = _resolve_reference_fasta(reference_id)
    if not reference_fasta or not reference_preflight.get("ready"):
        run.status = "failed"
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        msg = reference_preflight.get("message") or f"Reference {reference_id} is not downloaded/indexed. Download it from References first."
        _emit_run_event(run_id, "pipeline_validation_failed", {"error": msg, "reference_id": reference_id, "preflight": reference_preflight})
        _add_run_step(run_id, "input_validation", "failed", 0, error=msg)
        return

    missing_inputs = [p for p in input_files if not Path(_resolve_pipeline_input(p)).exists()]
    if missing_inputs:
        run.status = "failed"
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        msg = f"Input files not found in /data/input: {missing_inputs}"
        _emit_run_event(run_id, "pipeline_validation_failed", {"error": msg, "missing_inputs": missing_inputs})
        _add_run_step(run_id, "input_validation", "failed", 0, error=msg)
        return

    _add_run_step(run_id, "input_validation", "done", 100, last_log="inputs and reference validated")

    resource_plan = _resource_plan()
    threads = int(resource_plan["threads"])
    _emit_run_event(run_id, "resource_plan", resource_plan)
    results = []
    output_dir = PIPELINE_RESULTS_ROOT / run_id

    for idx, stage_name in enumerate(stages):
        # Honor pause requests between stages. Active stage pause is handled by
        # SIGSTOP/SIGCONT in the pause/resume endpoints when the subprocess is
        # owned by this API process.
        while True:
            refresh_from_db(recover_stale_running=False)
            fresh_run = next((r for r in runs if r.id == run_id), None)
            if _CANCEL_FLAGS.get(run_id) or (fresh_run and fresh_run.status == "cancelling"):
                break
            boundary_pause_requested = _stage_boundary_pause_requested(fresh_run)
            if _PAUSE_FLAGS.get(run_id) or boundary_pause_requested or (fresh_run and fresh_run.status == "paused"):
                if fresh_run and fresh_run.status != "paused":
                    previous_status = fresh_run.status
                    params = dict(fresh_run.parameters or {})
                    if boundary_pause_requested:
                        params.update(
                            {
                                "pause_previous_status": previous_status,
                                "pause_reason": "stage_boundary_pause",
                                "pause_mode": PAUSE_MODE_STAGE_BOUNDARY,
                                "pause_next_stage": stage_name,
                            }
                        )
                        params.pop("pause_requested_at_stage_boundary", None)
                        params.pop("pause_requested_at", None)
                    elif "pause_previous_status" not in params:
                        params["pause_previous_status"] = previous_status
                    fresh_run.status = "paused"
                    fresh_run.parameters = params
                    fresh_run.updated_at = datetime.now(timezone.utc).isoformat()
                    save_run(fresh_run)
                    _emit_run_event(
                        run_id,
                        "pipeline_paused",
                        {
                            "at_stage": stage_name,
                            "mode": PAUSE_MODE_STAGE_BOUNDARY if boundary_pause_requested else "between_stages",
                            "previous_status": previous_status,
                        },
                    )
                time.sleep(1)
                continue
            break

        # Check cancel flag between stages.
        # _CANCEL_FLAGS works in-process (API thread); for cross-process cancel
        # (worker), also check run.status from DB.
        refresh_from_db(recover_stale_running=False)
        fresh_run = next((r for r in runs if r.id == run_id), None)
        if _CANCEL_FLAGS.get(run_id) or (fresh_run and fresh_run.status == "cancelling"):
            skipped = stages[idx:]
            for skipped_stage in skipped:
                _add_run_step(run_id, skipped_stage, "cancelled", 0, last_log="Cancelled by user")
                _emit_run_event(run_id, f"{skipped_stage}_cancelled", {"reason": "user_cancelled"})
            run.status = "cancelled"
            run.updated_at = datetime.now(timezone.utc).isoformat()
            save_run(run)
            _emit_run_event(run_id, "pipeline_cancelled", {"at_stage": stage_name, "skipped": skipped})
            _CANCEL_FLAGS.pop(run_id, None)
            _PAUSE_FLAGS.pop(run_id, None)
            _STAGE_SKIP_FLAGS.pop(run_id, None)
            return

        operator_skips, operator_skip_reasons = _operator_skip_payload(fresh_run or run)
        if stage_name in operator_skips:
            reason = operator_skip_reasons.get(stage_name) or "skipped_by_operator"
            if stage_name in required_stages and not _stage_artifact_ready(stage_name, run, sample):
                error = f"Cannot skip required stage {stage_name} without an existing reusable artifact."
                _add_run_step(run_id, stage_name, "failed", 0, error=error)
                _emit_run_event(run_id, f"{stage_name}_skip_rejected", {"reason": "required_artifact_missing"})
                results.append({"stage": stage_name, "status": "failed", "reason": error})
                break
            _add_run_step(run_id, stage_name, "skipped", 0, last_log=f"skipped_by_operator: {reason}")
            skipped_result = {"stage": stage_name, "status": "skipped", "reason": "skipped_by_operator", "operator_reason": reason}
            _emit_run_event(run_id, f"{stage_name}_skipped_by_operator", skipped_result)
            results.append(skipped_result)
            stage_outcomes[stage_name] = "skipped"
            continue

        blocking = _blocking_stage_dependency(stage_name, planned_stages, stage_outcomes, run, sample)
        if blocking:
            dependency, dependency_status = blocking
            blocked_result = _blocked_stage_result(stage_name, dependency, dependency_status)
            _add_run_step(
                run_id,
                stage_name,
                "blocked",
                0,
                last_log=f"Blocked because dependency {dependency} is {dependency_status}",
            )
            _emit_run_event(run_id, f"{stage_name}_blocked", blocked_result)
            results.append(blocked_result)
            stage_outcomes[stage_name] = "blocked"
            continue

        # Pre-check optional stages before emitting a misleading "started" event.
        # This keeps best-effort runs readable: not-configured modules are skipped,
        # while real runtime failures still surface with their logs.
        if stage_name not in required_stages:
            preflight_reason = _optional_stage_preflight_skip(stage_name, reference_fasta)
            if preflight_reason:
                _add_run_step(run_id, stage_name, "skipped", 0, last_log=preflight_reason)
                skipped_result = {"stage": stage_name, "status": "skipped", "optional": True, "reason": preflight_reason}
                _emit_run_event(run_id, f"{stage_name}_skipped", skipped_result)
                results.append(skipped_result)
                stage_outcomes[stage_name] = "skipped"
                continue

        # Pre-check tool availability for optional stages
        tools_ok, missing_tools = _check_stage_tools(stage_name)
        if not tools_ok and stage_name not in required_stages:
            # Optional stage with missing tools: skip cleanly
            reason = f"Skipped: tools not installed ({', '.join(missing_tools)})"
            _add_run_step(run_id, stage_name, "skipped", 0, last_log=reason)
            _emit_run_event(run_id, f"{stage_name}_skipped", {"reason": reason, "missing_tools": missing_tools, "optional": True})
            results.append({"stage": stage_name, "status": "skipped", "optional": True, "reason": reason})
            stage_outcomes[stage_name] = "skipped"
            continue

        _emit_run_event(run_id, f"{stage_name}_started", {})
        _add_run_step(run_id, stage_name, "running", 0)

        result = _run_stage_script(
            stage_name, sample_id, input_files, reference_fasta, reference_id, threads, output_dir,
            allow_dev_fallback, run_id, stage_options
        )
        results.append(result)
        _record_stage_execution(run_id, result)

        if result["status"] == "done":
            _add_run_step(run_id, stage_name, "done", 100, last_log=(result.get("stderr") or result.get("stdout") or "done")[-240:])
            _emit_run_event(run_id, f"{stage_name}_done", result)
            stage_outcomes[stage_name] = "done"
            # Auto-ingest results
            try:
                _auto_ingest(run_id, stage_name, result)
            except Exception as e:
                _emit_run_event(run_id, f"{stage_name}_ingest_error", {"error": str(e)})
        elif result["status"] == "paused":
            run.status = "paused"
            run.updated_at = datetime.now(timezone.utc).isoformat()
            run.parameters = {
                **(run.parameters or {}),
                "pause_previous_status": "running",
                "pause_reason": result.get("reason") or "stage_boundary_pause",
                "pause_mode": PAUSE_MODE_STAGE_BOUNDARY,
                "pause_next_stage": stages[idx + 1] if idx + 1 < len(stages) else None,
            }
            save_run(run)
            _add_run_step(
                run_id,
                stage_name,
                "paused",
                75,
                last_log=(result.get("stderr") or result.get("reason") or "paused at stage boundary")[-240:],
            )
            _emit_run_event(run_id, f"{stage_name}_paused", result)
            _emit_run_event(run_id, "pipeline_paused", {"at_stage": stage_name, "reason": result.get("reason"), "mode": "stage_boundary"})
            _PAUSE_FLAGS[run_id] = True
            stage_outcomes[stage_name] = "paused"
            return
        else:
            error = result.get("reason") or result.get("stderr") or result.get("stdout") or "stage failed"
            if stage_name not in required_stages:
                operator_skips, operator_skip_reasons = _operator_skip_payload(run)
                if stage_name in operator_skips:
                    reason = operator_skip_reasons.get(stage_name) or "skipped_by_operator"
                    optional_result = {
                        **result,
                        "status": "skipped",
                        "optional": True,
                        "reason": "skipped_by_operator",
                        "operator_reason": reason,
                    }
                    results[-1] = optional_result
                    _add_run_step(run_id, stage_name, "skipped", 0, last_log=f"skipped_by_operator: {reason}")
                    _emit_run_event(run_id, f"{stage_name}_skipped_by_operator", optional_result)
                    stage_outcomes[stage_name] = "skipped"
                    continue
                # Best-effort optional stages should be honest but non-alarming:
                # unavailable/not-configured optional interpretation modules do not
                # make the technical pipeline look broken when core stages passed.
                optional_result = {
                    **result,
                    "status": "skipped",
                    "optional": True,
                    "reason": str(error)[-500:],
                }
                results[-1] = optional_result
                _add_run_step(run_id, stage_name, "skipped", 0, last_log=f"Optional stage unavailable: {str(error)[-240:]}")
                _emit_run_event(run_id, f"{stage_name}_optional_unavailable", optional_result)
                stage_outcomes[stage_name] = "skipped"
                continue

            _add_run_step(run_id, stage_name, "failed", 0, error=str(error)[-500:])
            _emit_run_event(run_id, f"{stage_name}_failed", result)
            stage_outcomes[stage_name] = "failed"
            if stop_on_failure and stage_name in required_stages:
                skipped = stages[idx + 1 :]
                skipped_results = _mark_remaining_after_required_failure(
                    run_id,
                    skipped,
                    stage_name,
                    planned_stages,
                    stage_outcomes,
                    run,
                    sample,
                )
                results.extend(skipped_results)
                _emit_run_event(run_id, "pipeline_aborted", {"failed_stage": stage_name, "skipped": skipped_results})
                break

    has_required_failure = any(
        r.get("status") in {"failed", "blocked"} and r.get("stage") in required_stages
        for r in results
    )
    run.status = "failed" if has_required_failure else "done"
    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)
    _emit_run_event(run_id, "pipeline_finished", {"profile": profile_name, "results": results})
    _CANCEL_FLAGS.pop(run_id, None)
    _STAGE_SKIP_FLAGS.pop(run_id, None)


def _emit_run_event(run_id: str, event_type: str, data: dict):
    """Store a run event."""
    add_run_event(RunEvent(
        id=f"evt_{uuid4().hex[:10]}",
        run_id=run_id,
        event_type=event_type,
        payload=data,
    ))


def _clear_taxonomy_results_for_run(run_id: str, reason: str):
    """Clear stale run-scoped taxonomy hits before a fresh taxonomy execution."""
    before = len([t for t in taxonomy_hits if t.run_id == run_id])
    if before:
        delete_taxonomy_hits_by_run(run_id)
    _emit_run_event(run_id, "taxonomy.results_cleared", {"count": before, "reason": reason})
    add_run_log_line(
        RunLogLine(
            run_id=run_id,
            line_no=len(run_logs) + 1,
            message=f"Taxonomy results cleared count={before} reason={reason}",
        )
    )


def _add_run_step(run_id: str, step_name: str, status: str, progress: int, last_log: str | None = None, error: str | None = None):
    """Add or update a run step."""
    now = datetime.now(timezone.utc).isoformat()
    existing = next((s for s in run_steps if s.run_id == run_id and s.step_name == step_name), None)
    if existing:
        existing.status = status
        existing.progress_pct = progress
        if last_log is not None:
            existing.last_log = last_log
        if error is not None:
            existing.error = error
        existing.updated_at = now
        save_run_step(existing)
    else:
        add_run_step(RunStep(
            id=f"stp_{uuid4().hex[:10]}",
            run_id=run_id,
            step_name=step_name,
            status=status,
            progress_pct=progress,
            last_log=last_log,
            error=error,
        ))


def _auto_ingest(run_id: str, stage_name: str, result: dict):
    """Auto-ingest the JSON contract emitted by a stage script."""
    output_dir = Path(result.get("output_dir", ""))
    ingest_template = INGEST_FILES.get(stage_name)
    if not ingest_template or not output_dir.exists():
        raise RuntimeError("ingest_contract_unavailable")
    run = next((r for r in runs if r.id == run_id), None)
    sample = next((s for s in samples if run and s.id == run.sample_id), None)
    sample_name = sample.sample_id if sample else ""
    ingest_path = output_dir / ingest_template.format(sample=sample_name)
    if not ingest_path.exists():
        # Fallback: find any matching stage ingest file.
        matches = list(output_dir.glob(f"*.{stage_name}.ingest.json"))
        if not matches and stage_name == "variants":
            matches = list(output_dir.glob("*.variants.*.ingest.json"))
        if not matches:
            raise RuntimeError(f"ingest_file_not_found:{ingest_path}")
        ingest_path = matches[0]
    contract = json.loads(ingest_path.read_text(encoding="utf-8"))
    stage = contract.get("stage", stage_name)
    payload = _absolutize_ingest_payload(contract.get("payload", {}), output_dir)
    auto_ingest_run_stage(run_id, AutoIngestRequest(stage=stage, payload=payload))


@router.post("/runs/{run_id}/pipeline/start")
def start_pipeline(run_id: str, req: PipelineStartRequest | None = None):
    """Trigger pipeline execution for a run."""
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    if run.status == "running":
        raise HTTPException(status_code=409, detail="pipeline_already_running")
    if run.status == "paused":
        raise HTTPException(status_code=409, detail="pipeline_paused_use_resume")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    # Resolve profile stages. A bare Start button must not silently mean
    # "strict full WGS"; keep the run's selected profile, otherwise use the
    # safe core profile. Custom stage lists remain explicit/all-required.
    stored_profile = (run.parameters or {}).get("profile") if isinstance(run.parameters, dict) else None
    profile_name = req.profile if req and req.profile else stored_profile
    if not profile_name and not (req and req.stages):
        profile_name = "core_variants"

    if profile_name:
        prof = PIPELINE_PROFILES.get(profile_name)
        if not prof:
            raise HTTPException(400, detail={"code": "unknown_profile", "message": f"Unknown pipeline profile: {profile_name}. Available: {list(PIPELINE_PROFILES.keys())}"})
        stages = list(prof["stages"])
        required_stages = set(prof["required_stages"])
    else:
        stages = list(req.stages if req and req.stages else PIPELINE_STAGES)
        required_stages = set(stages)  # explicit custom stages are all required by default

    input_files = req.input_files if req and req.input_files else []
    if not input_files:
        # Auto-detect from sample
        if sample.r1_path:
            input_files.append(sample.r1_path)
        if sample.r2_path:
            input_files.append(sample.r2_path)

    input_files, pairing_notes = _normalize_fastq_pair(input_files)
    bam_inputs = [p for p in input_files if str(p).lower().endswith(".bam")]
    if bam_inputs:
        if len(bam_inputs) != len(input_files):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "mixed_input_types_unsupported",
                    "message": "Select either a FASTQ pair or one pre-aligned BAM. Mixed input types are not supported for one run.",
                    "input_files": input_files,
                },
            )
        if len(bam_inputs) > 1:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "multiple_bam_inputs_unsupported",
                    "message": "Select one pre-aligned BAM per run.",
                    "input_files": input_files,
                },
            )
        stages = [stage for stage in stages if stage != "alignment"]
        required_stages.discard("alignment")

    requested_from_stage = req.from_stage if req and req.from_stage else None
    requested_only_stages = _validate_stage_list(req.only_stages if req else None, "only_stages")
    requested_skip_stages = _validate_stage_list(req.skip_stages if req else None, "skip_stages")
    if requested_from_stage:
        _validate_stage_list([requested_from_stage], "from_stage")
        from_idx = PIPELINE_STAGES.index(requested_from_stage)
        stages = [stage for stage in stages if PIPELINE_STAGES.index(stage) >= from_idx]
        required_stages = {stage for stage in required_stages if stage in stages}
    if requested_only_stages:
        stages = _ordered_stage_subset(requested_only_stages)
        required_stages = {stage for stage in required_stages if stage in stages}
    if requested_skip_stages:
        for skipped_stage in requested_skip_stages:
            if skipped_stage in required_stages and not _stage_artifact_ready(skipped_stage, run, sample):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "cannot_skip_required_stage_without_artifact",
                        "stage": skipped_stage,
                        "message": f"Cannot skip required stage {skipped_stage} without an existing reusable artifact.",
                    },
                )
        stages = [stage for stage in stages if stage not in requested_skip_stages]
        required_stages = {stage for stage in required_stages if stage not in requested_skip_stages}
    if not stages:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "empty_stage_plan",
                "message": "Stage plan is empty after applying from_stage/only_stages/skip_stages.",
            },
        )
    _validate_stage_dependencies(run, sample, stages, input_files)

    skip_reasons = {
        **((run.parameters or {}).get("skip_reasons") if isinstance((run.parameters or {}).get("skip_reasons"), dict) else {}),
    }
    if requested_skip_stages:
        reason = (req.skip_reason if req else None) or "operator requested skip"
        for stage in requested_skip_stages:
            skip_reasons[stage] = reason

    requested_taxonomy_database = req.taxonomy_database if req and req.taxonomy_database else None
    taxonomy_database_path = _resolve_taxonomy_database_path(requested_taxonomy_database) if "taxonomy" in stages else None
    requested_taxonomy_route = _resolve_taxonomy_route(req.taxonomy_route if req else None) if "taxonomy" in stages else None
    requested_taxonomy_low_mapq = _taxonomy_low_mapq_threshold(req.taxonomy_low_mapq_threshold if req else None) if "taxonomy" in stages else None
    stage_options = {
        **((run.parameters or {}).get("stage_options") if isinstance((run.parameters or {}).get("stage_options"), dict) else {}),
    }
    if taxonomy_database_path:
        stage_options["taxonomy_database"] = requested_taxonomy_database
        stage_options["taxonomy_database_path"] = taxonomy_database_path
    if requested_taxonomy_route:
        stage_options["taxonomy_route"] = requested_taxonomy_route
        stage_options["taxonomy_low_mapq_threshold"] = requested_taxonomy_low_mapq

    disk_preflight = _pipeline_disk_preflight(input_files, stages, PIPELINE_RESULTS_ROOT / run_id)
    if disk_preflight["status"] == "blocked":
        _emit_run_event(run_id, "pipeline_disk_preflight_blocked", disk_preflight)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "pipeline_disk_preflight_blocked",
                "message": "Estimated pipeline peak disk use exceeds available result-volume free space.",
                "disk_preflight": disk_preflight,
            },
        )

    stage_plan = {
        "from_stage": requested_from_stage,
        "only_stages": requested_only_stages,
        "skip_stages": requested_skip_stages,
        "skip_reasons": {stage: skip_reasons.get(stage) for stage in requested_skip_stages},
        "final_stages": list(stages),
        "required_stages": sorted(required_stages),
        "dependency_validation": "passed",
        "stage_options": stage_options,
        "disk_preflight": disk_preflight,
    }

    run.parameters = {
        **(run.parameters or {}),
        "profile": profile_name or "custom",
        "stages": list(stages),
        "required_stages": sorted(required_stages),
        "input_files": list(input_files),
        "allow_dev_fallback": req.allow_dev_fallback if req else False,
        "stop_on_failure": req.stop_on_failure if req else True,
        "optional_tools_missing": (run.parameters or {}).get("optional_tools_missing", []),
        "input_mode": "prealigned_bam" if bam_inputs else "fastq",
        "resource_plan": _resource_plan(),
        "compute_profile": _compute_profile(),
        "threads": _pipeline_threads(),
        "stage_plan": stage_plan,
        "stage_options": stage_options,
        "skip_stages": sorted(set((run.parameters or {}).get("skip_stages") or []).union(requested_skip_stages)),
        "skip_reasons": skip_reasons,
    }
    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)
    if requested_from_stage or requested_only_stages or requested_skip_stages:
        _emit_run_event(run_id, "pipeline_stage_plan_requested", stage_plan)
        for skipped_stage in requested_skip_stages:
            _add_run_step(
                run_id,
                skipped_stage,
                "skipped",
                0,
                last_log=f"skipped_by_operator: {skip_reasons.get(skipped_stage) or 'operator requested skip'}",
            )
            _emit_run_event(
                run_id,
                f"{skipped_stage}_skipped_by_operator",
                {"stage": skipped_stage, "reason": skip_reasons.get(skipped_stage), "source": "pipeline_start"},
            )

    if disk_preflight["status"] != "ok":
        _emit_run_event(run_id, "pipeline_disk_preflight_warning", disk_preflight)

    # Pre-flight tool check: block if required tools missing, warn for optional
    missing_required = []
    missing_optional = []
    for stage in stages:
        tools_ok, missing = _check_stage_tools(stage)
        if not tools_ok:
            if stage in required_stages:
                missing_required.append({"stage": stage, "missing": missing})
            else:
                missing_optional.append({"stage": stage, "missing": missing})
    if missing_required:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "required_tools_missing",
                "message": f"Required tools not installed for: {[m['stage'] for m in missing_required]}. Install them or use 'Best Effort' profile.",
                "missing": missing_required,
                "available_profiles": [p["id"] for p in _get_pipeline_profiles_info() if p["ready"]],
            },
        )

    selected_backend_missing = _validate_selected_backends(stages)
    if selected_backend_missing:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "selected_backend_missing",
                "message": "Selected pipeline backend is not installed in the active API/worker image.",
                "missing": selected_backend_missing,
                "settings_endpoint": "/pipeline/settings",
            },
        )

    if not input_files:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "input_files_required",
                "message": "No input files are attached to this sample/run. Start from Data Import and select FASTQ files.",
            },
        )

    reference_preflight = _reference_pipeline_preflight(run.reference_id, stages)
    reference_fasta = _resolve_reference_fasta(run.reference_id)
    if not reference_fasta or not reference_preflight.get("ready"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": reference_preflight.get("code", "reference_not_ready"),
                "message": reference_preflight.get("message", f"Reference {run.reference_id} is not downloaded/indexed. Go to References and download/index it first."),
                "reference_id": run.reference_id,
                "preflight": reference_preflight,
            },
        )

    missing_inputs = [p for p in input_files if not Path(_resolve_pipeline_input(p)).exists()]
    if missing_inputs:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "input_files_missing",
                "message": "Selected input files are missing from /data/input.",
                "missing_inputs": missing_inputs,
            },
        )

    bam_preflight_failures = []
    for bam_input in bam_inputs:
        resolved = Path(_resolve_pipeline_input(bam_input))
        preflight = _bam_pipeline_preflight(resolved)
        if not preflight.get("ready"):
            bam_preflight_failures.append({"path": bam_input, "preflight": preflight})
    if bam_preflight_failures:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "input_preparation_required",
                "message": "Selected BAM must be coordinate-sorted and indexed before pipeline start. Use Data Import prepare action first.",
                "files": bam_preflight_failures,
                "prepare_endpoint": "/data/prepare",
            },
        )

    fastq_inputs = [p for p in input_files if str(p).lower().endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq"))]
    if not bam_inputs and not fastq_inputs:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_pipeline_input_type",
                "message": "Pipeline start accepts a FASTQ pair or one coordinate-sorted BAM. Prepare/index VCF files from Data Import, but import them through a VCF-specific flow.",
                "input_files": input_files,
            },
        )
    if len(fastq_inputs) == 1:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "fastq_pair_incomplete",
                "message": "Only one FASTQ mate was selected. Select both R1 and R2, or place the missing mate in /data/input.",
                "input_files": input_files,
            },
        )

    if req and req.resume_existing and run.status in ("failed", "cancelled", "interrupted") and "alignment" in stages:
        alignment_step_status = _run_step_status(run_id, "alignment")
        if alignment_step_status != "done":
            checkpoint_status = _alignment_checkpoint_status(run, sample)
            if not checkpoint_status["alignment"]["restartable"]:
                _emit_run_event(
                    run_id,
                    "pipeline_resume_blocked",
                    {
                        "stage": "alignment",
                        "reason": "no_restartable_alignment_checkpoint",
                        "checkpoint_status": checkpoint_status,
                    },
                )
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "no_restartable_alignment_checkpoint",
                        "message": "No valid alignment checkpoint exists for this run. Resume would restart mapping from FASTQ, so it was blocked.",
                        "checkpoint_status": checkpoint_status,
                    },
                )

    job = PipelineJob(
        run_id=run_id,
        sample_id=sample.sample_id,
        input_files=input_files,
        reference_id=run.reference_id,
        stages=list(stages),
        allow_dev_fallback=req.allow_dev_fallback if req else False,
        stop_on_failure=req.stop_on_failure if req else True,
        required_stages=list(required_stages),
        profile_name=profile_name,
        optional_tools_missing=missing_optional,
        stage_plan=stage_plan,
        stage_options=stage_options,
    )
    executor = _pipeline_executor()
    queue_info = None
    if "taxonomy" in stages:
        _clear_taxonomy_results_for_run(run_id, "pipeline_taxonomy_start")
    if executor == PIPELINE_EXECUTOR_WORKER_QUEUE:
        run.status = "queued"
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        try:
            queue_info = _enqueue_pipeline_job(job)
        except Exception as exc:
            run.status = "failed"
            run.updated_at = datetime.now(timezone.utc).isoformat()
            save_run(run)
            _emit_run_event(run_id, "pipeline_queue_failed", {"error": str(exc)})
            raise HTTPException(status_code=503, detail={"code": "pipeline_queue_unavailable", "message": str(exc)})
        _emit_run_event(run_id, "pipeline_queued", {"executor": executor, "queue": queue_info["queue"]})
    else:
        _dispatch_pipeline_job(job)

    return {
        "status": "queued" if executor == PIPELINE_EXECUTOR_WORKER_QUEUE else "started",
        "run_id": run_id,
        "profile": profile_name,
        "stages": stages,
        "input_files": input_files,
        "pairing_notes": pairing_notes,
        "optional_tools_missing": missing_optional,
        "stage_plan": stage_plan,
        "executor": executor,
        "queue": queue_info,
        "job": job.model_dump(),
    }


@router.post("/runs/{run_id}/taxonomy/subruns")
def start_taxonomy_subrun(run_id: str, req: TaxonomySubrunRequest):
    parent = next((r for r in runs if r.id == run_id), None)
    if not parent:
        raise HTTPException(status_code=404, detail="run_not_found")
    sample = next((s for s in samples if s.id == parent.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    route = _resolve_taxonomy_route(req.taxonomy_route)
    low_mapq = _taxonomy_low_mapq_threshold(req.taxonomy_low_mapq_threshold)
    taxonomy_database_path = _resolve_taxonomy_database_path(req.taxonomy_database)

    if route == "full_fastq_shotgun":
        input_files = [p for p in [sample.r1_path, sample.r2_path] if p]
        if len(input_files) != 2:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "fastq_pair_required_for_taxonomy_subrun",
                    "message": "Full FASTQ shotgun taxonomy subruns require both sample FASTQ mates.",
                    "sample_id": sample.id,
                },
            )
        inherited_input = "sample_fastq"
    else:
        parent_bam = _final_alignment_bam_path(parent, sample)
        if not parent_bam:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "parent_alignment_bam_required",
                    "message": "Host-depleted taxonomy subruns require a completed parent sorted.markdup BAM and BAI.",
                    "parent_run_id": parent.id,
                },
            )
        input_files = [str(parent_bam)]
        inherited_input = "parent_alignment_bam"

    subrun = Run(
        id=f"run_{uuid4().hex[:10]}",
        project_id=parent.project_id,
        sample_id=sample.id,
        mode="taxonomy",
        reference_id=parent.reference_id,
        status="queued",
        parameters={
            "parent_run_id": parent.id,
            "taxonomy_subrun": True,
            "taxonomy_database": req.taxonomy_database,
            "taxonomy_database_path": taxonomy_database_path,
            "taxonomy_route": route,
            "taxonomy_low_mapq_threshold": low_mapq,
            "inherited_input": inherited_input,
            "input_files": input_files,
            "stages": ["taxonomy"],
        },
    )
    add_run(subrun)
    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=subrun.id,
            event_type="run.queued",
            payload={"mode": "taxonomy", "parent_run_id": parent.id, "taxonomy_subrun": True},
        )
    )
    add_run_log_line(RunLogLine(run_id=subrun.id, line_no=1, message=f"Taxonomy subrun queued from {parent.id}"))
    _append_step(subrun.id, "input_validation", status="done")
    _append_step(subrun.id, "taxonomy")
    _emit_run_event(
        parent.id,
        "taxonomy_subrun_created",
        {
            "subrun_id": subrun.id,
            "taxonomy_database": req.taxonomy_database,
            "taxonomy_database_path": taxonomy_database_path,
            "taxonomy_route": route,
            "taxonomy_low_mapq_threshold": low_mapq,
            "inherited_input": inherited_input,
        },
    )
    _emit_run_event(
        subrun.id,
        "taxonomy_subrun_created",
        {
            "parent_run_id": parent.id,
            "taxonomy_database": req.taxonomy_database,
            "taxonomy_database_path": taxonomy_database_path,
            "taxonomy_route": route,
            "taxonomy_low_mapq_threshold": low_mapq,
            "inherited_input": inherited_input,
            "input_files": input_files,
        },
    )

    start_response = start_pipeline(
        subrun.id,
        PipelineStartRequest(
            resume_existing=True,
            only_stages=["taxonomy"],
            input_files=input_files,
            taxonomy_database=req.taxonomy_database,
            taxonomy_route=route,
            taxonomy_low_mapq_threshold=low_mapq,
            allow_dev_fallback=req.allow_dev_fallback,
            stop_on_failure=req.stop_on_failure,
        ),
    )
    return {
        "status": start_response["status"],
        "parent_run_id": parent.id,
        "subrun_id": subrun.id,
        "run": subrun,
        "start": start_response,
        "taxonomy_database": req.taxonomy_database,
        "taxonomy_database_path": taxonomy_database_path,
        "taxonomy_route": route,
        "taxonomy_low_mapq_threshold": low_mapq,
        "inherited_input": inherited_input,
    }


@router.get("/pipelines/profiles")
def list_pipeline_profiles():
    """Return available pipeline profiles with tool availability."""
    return {"items": _get_pipeline_profiles_info()}


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: str, req: PauseRunRequest | None = None):
    """Pause a pipeline with minimal progress loss when the active process is local."""
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    if run.status not in ("running", "queued"):
        raise HTTPException(status_code=409, detail=f"run_is_{run.status}_cannot_pause")

    mode = _normalize_pause_mode(req.mode if req else None)
    previous_status = run.status

    if mode == PAUSE_MODE_STAGE_BOUNDARY and previous_status == "running":
        requested_at = datetime.now(timezone.utc).isoformat()
        run.parameters = {
            **(run.parameters or {}),
            "pause_previous_status": previous_status,
            "pause_reason": "stage_boundary_pause",
            "pause_mode": PAUSE_MODE_STAGE_BOUNDARY,
            "pause_requested_at_stage_boundary": True,
            "pause_requested_at": requested_at,
        }
        run.updated_at = requested_at
        save_run(run)
        _emit_run_event(
            run_id,
            "pipeline_pause_requested",
            {
                "previous_status": previous_status,
                "mode": PAUSE_MODE_STAGE_BOUNDARY,
                "requested_at": requested_at,
                "active_process": run_id in _ACTIVE_PROCESSES,
            },
        )
        return {
            "status": "pause_requested",
            "run_id": run_id,
            "run_status": run.status,
            "mode": PAUSE_MODE_STAGE_BOUNDARY,
            "message": "Run will pause after the current stage exits; active process was not suspended.",
        }

    _PAUSE_FLAGS[run_id] = True
    run.parameters = {
        **(run.parameters or {}),
        "pause_previous_status": previous_status,
        "pause_mode": PAUSE_MODE_ACTIVE_PROCESS if previous_status == "running" else "queued",
    }
    run.status = "paused"
    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)

    proc = _ACTIVE_PROCESSES.get(run_id)
    if proc and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGSTOP)
            _emit_run_event(run_id, "pipeline_paused", {"previous_status": previous_status, "pid": proc.pid, "mode": "active_process"})
            return {"status": "paused", "run_id": run_id, "run_status": run.status, "mode": "active_process"}
        except Exception as exc:
            run.status = previous_status
            run.parameters = _clear_pause_state(run.parameters)
            run.updated_at = datetime.now(timezone.utc).isoformat()
            save_run(run)
            _PAUSE_FLAGS.pop(run_id, None)
            raise HTTPException(status_code=500, detail=f"pause_signal_failed:{exc}")

    if previous_status == "queued":
        _emit_run_event(run_id, "pipeline_paused", {"previous_status": previous_status, "mode": "queued"})
        return {"status": "paused", "run_id": run_id, "run_status": run.status, "mode": "queued"}

    _emit_run_event(run_id, "pipeline_paused", {"previous_status": previous_status, "mode": "between_stages_or_external_executor"})
    return {"status": "paused", "run_id": run_id, "run_status": run.status, "mode": "between_stages_or_external_executor"}


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str):
    """Resume a paused pipeline."""
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    params = run.parameters or {}
    if run.status == "running" and _stage_boundary_pause_requested(run):
        _PAUSE_FLAGS.pop(run_id, None)
        run.parameters = _clear_pause_state(params)
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        _emit_run_event(run_id, "pipeline_pause_request_cancelled", {"mode": PAUSE_MODE_STAGE_BOUNDARY})
        return {"status": "pause_request_cleared", "run_id": run_id, "run_status": run.status, "mode": PAUSE_MODE_STAGE_BOUNDARY}
    if run.status != "paused":
        raise HTTPException(status_code=409, detail=f"run_is_{run.status}_cannot_resume")

    proc = _ACTIVE_PROCESSES.get(run_id)
    previous_status = params.get("pause_previous_status")
    if proc and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGCONT)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"resume_signal_failed:{exc}")
        _PAUSE_FLAGS.pop(run_id, None)
        run.parameters = _clear_pause_state(params)
        run.status = "running"
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        _emit_run_event(run_id, "pipeline_resumed", {"pid": proc.pid, "mode": "active_process"})
        return {"status": "resumed", "run_id": run_id, "run_status": run.status}

    _PAUSE_FLAGS.pop(run_id, None)
    pause_reason = params.get("pause_reason")
    pause_mode = params.get("pause_mode")
    run.parameters = _clear_pause_state(params)
    if previous_status == "queued":
        run.status = "queued"
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        _emit_run_event(run_id, "pipeline_resumed", {"pid": None, "mode": "queued"})
        return {"status": "resumed", "run_id": run_id, "run_status": run.status}

    if previous_status == "running" and run_id in _ACTIVE_RUNNERS:
        run.status = "running"
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        _emit_run_event(run_id, "pipeline_resumed", {"pid": None, "mode": pause_mode or "between_stages"})
        return {"status": "resumed", "run_id": run_id, "run_status": run.status, "mode": pause_mode or "between_stages"}

    if previous_status == "running" and _pipeline_executor() == PIPELINE_EXECUTOR_WORKER_QUEUE and _is_stage_boundary_pause(params):
        run.status = "running"
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        _emit_run_event(run_id, "pipeline_resumed", {"pid": None, "mode": PAUSE_MODE_STAGE_BOUNDARY, "executor": PIPELINE_EXECUTOR_WORKER_QUEUE})
        return {"status": "resumed", "run_id": run_id, "run_status": run.status, "mode": PAUSE_MODE_STAGE_BOUNDARY}

    if previous_status == "running" and _is_stage_boundary_pause(params):
        sample = next((s for s in samples if s.id == run.sample_id), None)
        if not sample:
            raise HTTPException(status_code=404, detail="sample_not_found")
        resume_params = run.parameters or {}
        resume_params = {**params, **resume_params}
        input_files = list(resume_params.get("input_files") or [])
        if not input_files:
            if sample.r1_path:
                input_files.append(sample.r1_path)
            if sample.r2_path:
                input_files.append(sample.r2_path)
        stages = list(resume_params.get("stages") or ["alignment"])
        if pause_reason != "disk_pressure_before_markdup":
            pause_next_stage = resume_params.get("pause_next_stage")
            if pause_next_stage in stages:
                stages = stages[stages.index(pause_next_stage):]
        if pause_reason == "disk_pressure_before_markdup" and "alignment" not in stages:
            stages = ["alignment", *stages]
        required_stages = list(resume_params.get("required_stages") or ["alignment"])
        required_stages = [stage for stage in required_stages if stage in stages]
        stage_plan = dict(resume_params.get("stage_plan") or {})
        stage_plan.update(
            {
                "resume_after_pause": True,
                "pause_reason": pause_reason,
                "pause_mode": pause_mode,
                "final_stages": stages,
                "required_stages": required_stages,
            }
        )
        run.parameters = {
            **(run.parameters or {}),
            "stages": stages,
            "required_stages": required_stages,
            "input_files": input_files,
            "stage_plan": stage_plan,
        }
        job = PipelineJob(
            run_id=run_id,
            sample_id=sample.sample_id,
            input_files=input_files,
            reference_id=run.reference_id,
            stages=stages,
            allow_dev_fallback=bool(resume_params.get("allow_dev_fallback", False)),
            stop_on_failure=bool(resume_params.get("stop_on_failure", True)),
            required_stages=required_stages,
            profile_name=resume_params.get("profile"),
            optional_tools_missing=list(resume_params.get("optional_tools_missing") or []),
            stage_plan=stage_plan,
            stage_options=resume_params.get("stage_options") or {},
        )
        executor = _pipeline_executor()
        if executor == PIPELINE_EXECUTOR_WORKER_QUEUE:
            run.status = "queued"
            run.updated_at = datetime.now(timezone.utc).isoformat()
            save_run(run)
            queue_info = _enqueue_pipeline_job(job)
            _emit_run_event(run_id, "pipeline_resumed", {"pid": None, "mode": "stage_boundary_checkpoint", "executor": executor, "queue": queue_info})
            return {"status": "resumed", "run_id": run_id, "run_status": run.status, "mode": "stage_boundary_checkpoint", "queue": queue_info}
        run.status = "running"
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        _dispatch_pipeline_job(job)
        _emit_run_event(run_id, "pipeline_resumed", {"pid": None, "mode": "stage_boundary_checkpoint", "executor": executor})
        return {"status": "resumed", "run_id": run_id, "run_status": run.status, "mode": "stage_boundary_checkpoint"}

    run.status = "interrupted"
    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)
    _emit_run_event(run_id, "pipeline_resume_blocked", {"reason": "active_process_missing_after_restart", "previous_status": previous_status})
    raise HTTPException(
        status_code=409,
        detail={
            "code": "active_process_missing_after_restart",
            "message": "The paused process no longer exists, probably because the API/container was rebuilt or restarted. The run was marked interrupted instead of pretending to resume.",
        },
    )


@router.post("/runs/{run_id}/stages/{stage_name}/skip")
def skip_run_stage(run_id: str, stage_name: str, req: StageSkipRequest | None = None):
    """Mark a stage to be skipped by the operator.

    Active local optional stages are terminated so the runner can continue and
    record them as skipped_by_operator. Required stages can only be skipped when
    their reusable artifact already exists.
    """
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    _validate_stage_list([stage_name], "stage_name")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    params = run.parameters or {}
    required_stages = set(params.get("required_stages") or [])
    if not required_stages:
        profile = params.get("profile")
        if profile in PIPELINE_PROFILES:
            required_stages = set(PIPELINE_PROFILES[profile]["required_stages"])
    reusable_artifact_ready = _stage_artifact_ready(stage_name, run, sample)
    if stage_name in required_stages and not reusable_artifact_ready:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "cannot_skip_required_stage_without_artifact",
                "stage": stage_name,
                "message": f"Cannot skip required stage {stage_name} without an existing reusable artifact.",
            },
        )

    reason = (req.reason if req else None) or "operator requested skip"
    skip_stages = set(params.get("skip_stages") or [])
    skip_stages.add(stage_name)
    skip_reasons = params.get("skip_reasons") if isinstance(params.get("skip_reasons"), dict) else {}
    skip_reasons[stage_name] = reason
    run.parameters = {**params, "skip_stages": sorted(skip_stages), "skip_reasons": skip_reasons}
    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)
    _STAGE_SKIP_FLAGS.setdefault(run_id, set()).add(stage_name)

    current_step = next((s for s in run_steps if s.run_id == run_id and s.step_name == stage_name), None)
    killed_active_process = False
    can_stop_active_stage = stage_name not in required_stages or reusable_artifact_ready
    if current_step and current_step.status == "running" and can_stop_active_stage:
        proc = _ACTIVE_PROCESSES.get(run_id)
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                killed_active_process = True
            except Exception:
                try:
                    proc.kill()
                    killed_active_process = True
                except Exception:
                    pass
    elif not current_step or current_step.status in {"queued", "failed", "cancelled", "interrupted"}:
        _add_run_step(run_id, stage_name, "skipped", 0, last_log=f"skipped_by_operator: {reason}")

    payload = {
        "stage": stage_name,
        "reason": reason,
        "active_process_terminated": killed_active_process,
        "run_status": run.status,
    }
    _emit_run_event(run_id, f"{stage_name}_skip_requested", payload)
    return {"status": "skip_requested", "run_id": run_id, **payload}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    """Cancel a running pipeline. Kills active subprocess immediately."""
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    if run.status not in ("running", "queued", "paused", "cancelling"):
        raise HTTPException(status_code=409, detail=f"run_is_{run.status}_cannot_cancel")

    _CANCEL_FLAGS[run_id] = True
    _PAUSE_FLAGS.pop(run_id, None)
    previous_status = run.status
    pause_previous_status = (run.parameters or {}).get("pause_previous_status")
    if run.status in ("running", "paused"):
        run.parameters = _clear_pause_state(run.parameters)
        run.status = "cancelling"
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        _emit_run_event(run_id, "pipeline_cancel_requested", {"previous_status": previous_status})

    # Kill active subprocess immediately
    proc = _ACTIVE_PROCESSES.get(run_id)
    if proc and proc.poll() is None:
        try:
            if previous_status == "paused":
                os.killpg(proc.pid, signal.SIGCONT)
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # If queued but not yet started, transition immediately. This includes runs
    # that were queued, then paused before a worker picked them up.
    if previous_status == "queued" or (previous_status == "paused" and pause_previous_status == "queued"):
        run.status = "cancelled"
        run.parameters = _clear_pause_state(run.parameters)
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        _emit_run_event(run_id, "pipeline_cancelled", {"reason": "user_cancelled_while_queued"})
        _CANCEL_FLAGS.pop(run_id, None)
        _STAGE_SKIP_FLAGS.pop(run_id, None)
    elif not proc or proc.poll() is not None:
        run.status = "cancelled"
        run.parameters = _clear_pause_state(run.parameters)
        run.updated_at = datetime.now(timezone.utc).isoformat()
        save_run(run)
        _emit_run_event(run_id, "pipeline_cancelled", {"reason": "no_active_process"})
        _CANCEL_FLAGS.pop(run_id, None)
        _STAGE_SKIP_FLAGS.pop(run_id, None)

    return {"status": "cancel_requested", "run_id": run_id, "run_status": run.status}


@router.post("/runs/{run_id}/retry")
def retry_run(run_id: str):
    """Create a new run reusing the same project, sample, mode, and reference as a failed/cancelled run."""
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    if run.status not in ("failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"run_is_{run.status}_only_failed_or_cancelled_can_retry")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    new_run = Run(
        id=f"run_{uuid4().hex[:10]}",
        project_id=run.project_id,
        sample_id=run.sample_id,
        mode=run.mode,
        reference_id=run.reference_id,
        status="queued",
        parameters={**run.parameters, "retry_of": run.id},
    )
    add_run(new_run)

    add_run_event(RunEvent(
        id=f"ev_{uuid4().hex[:10]}",
        run_id=new_run.id,
        event_type="run.retried",
        payload={"original_run_id": run_id, "mode": run.mode},
    ))
    add_run_log_line(RunLogLine(run_id=new_run.id, line_no=1, message=f"Retried from {run_id}"))

    # Seed steps identical to original run creation
    _append_step(new_run.id, "input_validation", status="done")
    if run.mode == "qc":
        _append_step(new_run.id, "fastqc_pre")
        _append_step(new_run.id, "fastp_optional")
        _append_step(new_run.id, "fastqc_post")
        _append_step(new_run.id, "multiqc")
    else:
        _append_step(new_run.id, "pipeline_dispatch")
        for stage_name in PIPELINE_STAGES:
            _append_step(new_run.id, stage_name)
        _append_step(new_run.id, "vendor_validation")
        if run.mode == "benchmark":
            _append_step(new_run.id, "benchmark")

    return new_run


@router.post("/runs/{run_id}/provenance")
def update_run_provenance(run_id: str, req: RunProvenanceUpdateRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    if req.repo_commit is not None:
        run.repo_commit = req.repo_commit
    if req.docker_image_version is not None:
        run.docker_image_version = req.docker_image_version
    if req.nextflow_version is not None:
        run.nextflow_version = req.nextflow_version
    if req.pipeline_version is not None:
        run.pipeline_version = req.pipeline_version
    if req.command_line is not None:
        run.command_line = req.command_line

    run.parameters.update(req.parameters)
    run.input_checksums.update(req.input_checksums)
    run.output_checksums.update(req.output_checksums)
    run.tool_versions.update(req.tool_versions)
    run.database_versions.update(req.database_versions)
    run.environment.update(req.environment)
    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="run.provenance_updated",
            payload={
                "repo_commit": run.repo_commit,
                "pipeline_version": run.pipeline_version,
            },
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message="Run provenance updated"))

    return run


@router.post("/runs/{run_id}/reports")
def create_run_report(run_id: str, req: ReportCreateRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    report = _generate_report_artifact(run, ReportGenerateRequest(report_type=req.report_type))
    add_report(report)
    run.report_ids.append(report.id)
    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="report.generated",
            payload={"report_id": report.id, "report_type": report.report_type},
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message=f"Report generated: {report.id}"))

    return report


INTERPRETATION_REPORT_GUARDRAILS = [
    "Research/technical interpretation scaffold only; not a clinical diagnosis.",
    "Do not treat missing reportable findings as a negative clinical screen.",
    "Every interpretation section must carry source/resource provenance before user-facing conclusions.",
    "PGx, PRS, mtDNA, monogenic, and traits modules require dedicated validation before clinical use.",
]


def _compact_interpretation_payload(payload: dict, *, item_limit: int = 25, condition_limit: int = 20) -> dict:
    compact: dict = {}
    for key in [
        "status",
        "count",
        "condition_count",
        "summary",
        "top_genes",
        "impact_counts",
        "build_validation",
        "provenance",
        "non_diagnostic",
    ]:
        if key in payload:
            compact[key] = payload[key]

    if "items" in payload:
        items = payload.get("items") or []
        compact["items_preview"] = items[:item_limit]
        compact["items_preview_count"] = min(len(items), item_limit)
        compact["items_total_count"] = len(items)

    if "conditions" in payload:
        conditions = payload.get("conditions") or []
        compact["conditions_preview"] = conditions[:condition_limit]
        compact["conditions_preview_count"] = min(len(conditions), condition_limit)
        compact["conditions_total_count"] = len(conditions)

    for key in ["expected_paths", "version", "gene_count", "message"]:
        if key in payload:
            compact[key] = payload[key]
    return compact


def _blocked_interpretation_section(
    *,
    source_database: str,
    build: object,
    sample_id: str,
    run_id: str | None,
    genome_build: str | None,
    warning: str,
) -> dict:
    return {
        "status": "blocked_build_validation",
        "count": 0,
        "items_preview": [],
        "provenance": {
            "source_database": source_database,
            "genome_build": genome_build,
            "input_variant_count": getattr(build, "variant_count", 0),
            "matched_variant_count": 0,
            "confidence_level": "insufficient",
            "sample_id": sample_id,
            "last_run_id": run_id,
            "warnings": list(getattr(build, "warnings", []) or []) + [warning],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "non_diagnostic": True,
    }


def _interpretation_resource_summary(registry: list[dict]) -> dict:
    by_module: dict[str, dict] = {}
    required_missing: list[dict] = []
    for item in registry:
        module = str(item.get("module") or "unknown")
        entry = by_module.setdefault(
            module,
            {"available": 0, "missing": 0, "required_missing": [], "warnings": []},
        )
        if item.get("status") == "available":
            entry["available"] += 1
        else:
            entry["missing"] += 1
            if item.get("required"):
                missing = {
                    "id": item.get("id"),
                    "source_database": item.get("source_database"),
                    "path": item.get("path"),
                    "warnings": item.get("warnings") or [],
                }
                entry["required_missing"].append(missing)
                required_missing.append({"module": module, **missing})
        entry["warnings"].extend(item.get("warnings") or [])
    return {
        "available_count": len([x for x in registry if x.get("status") == "available"]),
        "missing_count": len([x for x in registry if x.get("status") != "available"]),
        "required_missing": required_missing,
        "modules": by_module,
    }


def _interpretation_report_summary_for_run(sample: Sample, run: Run) -> dict:
    ref = next((r for r in references if r.id == run.reference_id), None) or _reference_for_sample(sample)
    run_variants = [v for v in variants if v.run_id == run.id]
    build = validate_build(ref, run_variants)
    genome_build = build.expected_build
    tools = interpretation_tool_status()
    registry = [r.model_dump() for r in interpretation_resource_registry()]
    resource_summary = _interpretation_resource_summary(registry)

    if build.ready_for_interpretation:
        annotation = _compact_interpretation_payload(
            annotation_summary(
                run_variants,
                sample_id=sample.sample_id,
                run_id=run.id,
                genome_build=genome_build,
            )
        )
        monogenic = _compact_interpretation_payload(
            classify_monogenic_variants(
                variants=run_variants,
                sample_id=sample.sample_id,
                run_id=run.id,
                genome_build=genome_build,
                include_vus=True,
                min_review_rank=1,
            )
        )
        traits = _compact_interpretation_payload(
            evaluate_traits(
                run_variants,
                sample_id=sample.sample_id,
                run_id=run.id,
                genome_build=genome_build,
            )
        )
    else:
        annotation = _blocked_interpretation_section(
            source_database="VCF ANN/CSQ imported annotation",
            build=build,
            sample_id=sample.sample_id,
            run_id=run.id,
            genome_build=genome_build,
            warning="Annotation summary requires imported variants that match the run reference.",
        )
        monogenic = _blocked_interpretation_section(
            source_database="ClinVar",
            build=build,
            sample_id=sample.sample_id,
            run_id=run.id,
            genome_build=genome_build,
            warning="ClinVar exact-match interpretation requires build-validated variants.",
        )
        traits = _blocked_interpretation_section(
            source_database="operator_curated_traits_manifest",
            build=build,
            sample_id=sample.sample_id,
            run_id=run.id,
            genome_build=genome_build,
            warning="Trait rules require build-validated variants and curated source metadata.",
        )

    prs = [x for x in prs_results if x.run_id == run.id]
    prs_quality_warnings = sorted({x.warning for x in prs if x.warning})
    prs_section = {
        "status": "available" if prs else "not_run",
        "count": len(prs),
        "items_preview": [
            {
                "trait": x.trait,
                "score_value": x.score_value,
                "overlap_pct": x.overlap_pct,
                "variant_count_total": x.variant_count_total,
                "variant_count_matched": x.variant_count_matched,
                "quality_label": x.quality_label,
                "warning": x.warning,
            }
            for x in prs[:25]
        ],
        "provenance": {
            "source_database": "PGS Catalog/imported PRS results",
            "source_version": run.database_versions.get("prs") or run.database_versions.get("pgs_catalog"),
            "genome_build": genome_build,
            "input_variant_count": len(run_variants),
            "matched_variant_count": sum(x.variant_count_matched for x in prs),
            "confidence_level": "low" if prs else "insufficient",
            "sample_id": sample.sample_id,
            "last_run_id": run.id,
            "warnings": prs_quality_warnings or ["PRS stage has not imported results for this run."],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "non_diagnostic": True,
    }

    mtdna = [x for x in mtdna_results if x.run_id == run.id]
    mtdna_warning_reasons = [
        {"id": x.id, "reasons": _mtdna_warning_reasons(x)}
        for x in mtdna
        if _mtdna_warning_reasons(x)
    ]
    mtdna_section = {
        "status": "available" if mtdna else "not_run",
        "count": len(mtdna),
        "items_preview": [
            {
                "haplogroup": x.haplogroup,
                "heteroplasmy_mean_vaf": x.heteroplasmy_mean_vaf,
                "num_variants": x.num_variants,
                "numts_warning": x.numts_warning,
                "trust_score": x.trust_score,
                "trust_label": x.trust_label,
                "warning_reasons": _mtdna_warning_reasons(x),
            }
            for x in mtdna[:25]
        ],
        "provenance": {
            "source_database": "mtDNA caller/imported mtDNA results",
            "source_version": run.tool_versions.get("mtdna") or run.database_versions.get("mtdna"),
            "genome_build": genome_build,
            "input_variant_count": sum(x.num_variants for x in mtdna),
            "matched_variant_count": len(mtdna),
            "confidence_level": "low" if mtdna else "insufficient",
            "sample_id": sample.sample_id,
            "last_run_id": run.id,
            "warnings": [
                reason
                for warning in mtdna_warning_reasons
                for reason in warning["reasons"]
            ] or ["mtDNA stage has not imported results for this run."],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "warning_count": len(mtdna_warning_reasons),
        "warnings": mtdna_warning_reasons,
        "non_diagnostic": True,
    }

    if build.ready_for_interpretation:
        pgx_rule_layer = _compact_interpretation_payload(
            evaluate_pgx_rules(
                run_variants,
                sample_id=sample.sample_id,
                run_id=run.id,
                genome_build=genome_build,
            )
        )
    else:
        pgx_rule_layer = _blocked_interpretation_section(
            source_database="CPIC/PharmGKB curated rule manifest",
            build=build,
            sample_id=sample.sample_id,
            run_id=run.id,
            genome_build=genome_build,
            warning="PGx rule matching requires build-validated variants.",
        )

    if pgx_rule_layer.get("status") == "pgx_rules_matched":
        pgx_status = "curated_rules_matched"
    elif pgx_rule_layer.get("status") == "no_reportable_pgx_rule_matches":
        pgx_status = "curated_rules_no_matches"
    elif tools.get("pharmcat") and build.ready_for_interpretation:
        pgx_status = "ready_to_run"
    elif not tools.get("pharmcat") and pgx_rule_layer.get("status") == "not_configured":
        pgx_status = "not_configured"
    else:
        pgx_status = "blocked_build_validation"

    pgx_section = {
        "status": pgx_status,
        "count": pgx_rule_layer.get("count", 0),
        "rule_layer": pgx_rule_layer,
        "provenance": {
            "source_database": "PharmCAT/CPIC",
            "source_version": run.database_versions.get("cyp2d6") or run.database_versions.get("pharmcat"),
            "genome_build": genome_build,
            "input_variant_count": len(run_variants),
            "matched_variant_count": pgx_rule_layer.get("count", 0),
            "confidence_level": "low" if pgx_rule_layer.get("count", 0) else "insufficient",
            "sample_id": sample.sample_id,
            "last_run_id": run.id,
            "warnings": ([] if tools.get("pharmcat") else ["PharmCAT/CPIC executable output is not configured."])
            + (pgx_rule_layer.get("provenance", {}).get("warnings") or []),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "tools": {
            "pharmcat": tools.get("pharmcat"),
            "cyrius": tools.get("cyrius"),
            "stellarpgx": tools.get("stellarpgx"),
        },
        "non_diagnostic": True,
    }

    haplogroup_section = {
        "status": "ready_with_mtdna_input" if tools.get("haplogrep") and mtdna else "not_configured" if not tools.get("haplogrep") else "mtdna_variants_missing",
        "count": 0,
        "provenance": {
            "source_database": "HaploGrep/PhyloTree",
            "source_version": run.database_versions.get("haplogrep") or run.database_versions.get("phylotree"),
            "genome_build": genome_build,
            "input_variant_count": sum(x.num_variants for x in mtdna),
            "matched_variant_count": 0,
            "confidence_level": "insufficient",
            "sample_id": sample.sample_id,
            "last_run_id": run.id,
            "warnings": [] if tools.get("haplogrep") else ["HaploGrep/PhyloTree output is not configured."],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "non_diagnostic": True,
    }

    gaps: list[str] = []
    if not build.ready_for_interpretation:
        gaps.append("Import run-level variants that match the selected reference build.")
    if not tools.get("clinvar_tsv"):
        gaps.append("Install or configure ClinVar exact-match TSV before monogenic reporting.")
    traits_validation = validate_traits_manifest()
    if not traits_validation.get("valid"):
        gaps.append("Configure curated traits manifest before traits/wellness reporting.")
    pgx_validation = validate_pgx_rules_manifest()
    if not pgx_validation.get("valid"):
        gaps.append("Configure curated CPIC/PharmGKB PGx rule manifest before rule-layer PGx reporting.")
    if not prs:
        gaps.append("Run/import PRS results before PRS interpretation reporting.")
    if not mtdna:
        gaps.append("Run/import mtDNA results before mtDNA interpretation reporting.")
    if not tools.get("pharmcat"):
        gaps.append("Install/wire PharmCAT before PGx reporting.")
    if not tools.get("haplogrep"):
        gaps.append("Install/wire HaploGrep before mtDNA haplogroup reporting.")

    return {
        "sample_id": sample.sample_id,
        "run_id": run.id,
        "reference_id": run.reference_id,
        "status": "blocked_build_validation" if not build.ready_for_interpretation else "ready_with_gaps" if gaps else "ready",
        "build_validation": build.model_dump(),
        "sections": {
            "annotation": annotation,
            "monogenic": monogenic,
            "traits_wellness": traits,
            "prs": prs_section,
            "mtdna": mtdna_section,
            "pharmacogenomics": pgx_section,
            "haplogroups": haplogroup_section,
        },
        "resources": {
            "tools": tools,
            "registry": registry,
            "summary": resource_summary,
        },
        "actionable_gaps": gaps,
        "guardrails": INTERPRETATION_REPORT_GUARDRAILS,
        "provenance": {
            "run": {
                "id": run.id,
                "repo_commit": run.repo_commit,
                "pipeline_version": run.pipeline_version,
                "nextflow_version": run.nextflow_version,
                "tool_versions": run.tool_versions,
                "database_versions": run.database_versions,
            },
            "reference": _reference_provenance_for_run(run),
            "input_counts": {
                "run_variants": len(run_variants),
                "prs_results": len(prs),
                "mtdna_results": len(mtdna),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "non_diagnostic": True,
    }


def _build_report_summary(run: Run, report_type: str) -> dict:
    sample = next((s for s in samples if s.id == run.sample_id), None)
    sample_key = sample.sample_id if sample else "unknown"

    def _validation_report_item(item: VendorAssemblyValidation) -> dict:
        stats = item.summary or {}
        is_vcf = item.comparator_method == "vcf_exact"
        return {
            "validation_id": item.id,
            "asset_type": "vcf" if is_vcf else "assembly",
            "status": item.status,
            "similarity_score": item.similarity_score,
            "snv_concordance": item.snv_concordance,
            "indel_concordance": item.indel_concordance,
            "structural_concordance": item.structural_concordance,
            "comparator_method": item.comparator_method,
            "kmer_size": item.kmer_size,
            "pass_threshold": item.pass_threshold,
            "vendor_path": item.vendor_assembly_path,
            "pipeline_path": item.pipeline_assembly_path,
            "truth_total": stats.get("truth_total"),
            "query_total": stats.get("query_total"),
            "true_positive": stats.get("true_positive"),
            "false_positive": stats.get("false_positive"),
            "false_negative": stats.get("false_negative"),
            "created_at": item.created_at,
            "non_diagnostic": item.non_diagnostic,
        }

    def _acceptance_decision(items: list[VendorAssemblyValidation]) -> dict:
        if not items:
            return {
                "status": "no_data",
                "reason": "No supplied assembly or VCF validation has been imported for this run.",
                "pass_threshold": None,
                "latest_validation_id": None,
            }
        latest = sorted(items, key=lambda x: x.created_at)[-1]
        if latest.status == "passed":
            status = "accepted"
            reason = "Latest supplied assembly/VCF validation passed the configured threshold."
        elif latest.status == "failed":
            status = "rejected"
            reason = "Latest supplied assembly/VCF validation failed the configured threshold."
        else:
            status = "inconclusive"
            reason = "Latest supplied assembly/VCF validation did not produce a pass/fail decision."
        return {
            "status": status,
            "reason": reason,
            "pass_threshold": latest.pass_threshold,
            "latest_validation_id": latest.id,
            "latest_comparator_method": latest.comparator_method,
        }

    if report_type == "qc":
        q = next((x for x in reversed(qc_summaries) if x.run_id == run.id), None)
        return {
            "sample_id": sample_key,
            "status": q.status if q else "unknown",
            "total_reads": q.total_reads if q else None,
            "gc_content_pct": q.gc_content_pct if q else None,
            "duplication_rate_pct": q.duplication_rate_pct if q else None,
            "non_diagnostic": True,
        }

    if report_type == "alignment":
        a = next((x for x in reversed(alignment_metrics) if x.run_id == run.id), None)
        status = "imported" if a else "missing"
        return {
            "sample_id": sample_key,
            "status": status,
            "flagstat": {
                "mapped_reads_pct": a.mapped_reads_pct if a else None,
                "properly_paired_pct": a.properly_paired_pct if a else None,
                "duplicates_pct": a.duplicates_pct if a else None,
            },
            "idxstats": {
                "mapped_contigs": a.mapped_contigs if a else None,
                "unmapped_reads": a.unmapped_reads if a else None,
            },
            "insert_size": {
                "median": a.insert_size_median if a else None,
                "mad": a.insert_size_mad if a else None,
            },
            "source_files": a.source_files if a else [],
            "note": (
                "Alignment metrics imported from run artifacts."
                if a
                else "No alignment metrics have been imported for this run."
            ),
            "non_diagnostic": True,
        }

    if report_type == "coverage":
        c = next((x for x in reversed(coverage_metrics) if x.run_id == run.id), None)
        status = "imported" if c else "missing"
        return {
            "sample_id": sample_key,
            "status": status,
            "mosdepth": {
                "mean_coverage": c.mean_coverage if c else None,
                "median_coverage": c.median_coverage if c else None,
                "callable_fraction": c.callable_fraction if c else None,
                "coverage_ge_10x": c.coverage_ge_10x if c else None,
                "coverage_ge_20x": c.coverage_ge_20x if c else None,
                "coverage_ge_30x": c.coverage_ge_30x if c else None,
            },
            "tiles": {
                "levels": ["10mb", "1mb", "100kb", "10kb"] if c else [],
                "materialized": False,
                "status": "summary_only" if c else "not_imported",
            },
            "source_files": c.source_files if c else [],
            "note": (
                "Coverage metrics imported from run artifacts."
                if c
                else "No coverage metrics have been imported for this run."
            ),
            "non_diagnostic": True,
        }

    if report_type == "variant":
        v = [x for x in variants if x.run_id == run.id]
        return {
            "sample_id": sample_key,
            "variant_count": len(v),
            "consensus_count": len([x for x in v if _agreement_bucket(x) == "consensus"]),
            "disagreement_count": len([x for x in v if _agreement_bucket(x) == "disagreement"]),
            "non_diagnostic": True,
        }

    if report_type == "sv":
        sv = [x for x in structural_variants if x.run_id == run.id]
        return {
            "sample_id": sample_key,
            "sv_count": len(sv),
            "type_distribution": {
                "DEL": len([x for x in sv if x.sv_type == "DEL"]),
                "INS": len([x for x in sv if x.sv_type == "INS"]),
                "DUP": len([x for x in sv if x.sv_type == "DUP"]),
                "INV": len([x for x in sv if x.sv_type == "INV"]),
                "OTHER": len([x for x in sv if x.sv_type not in {"DEL", "INS", "DUP", "INV"}]),
            },
            "non_diagnostic": True,
        }

    if report_type == "cnv":
        cnv = [x for x in cnv_segments if x.run_id == run.id]
        return {
            "sample_id": sample_key,
            "segment_count": len(cnv),
            "gain_count": len([x for x in cnv if x.cnv_type.lower() == "gain"]),
            "loss_count": len([x for x in cnv if x.cnv_type.lower() == "loss"]),
            "non_diagnostic": True,
        }

    if report_type == "annotation":
        v = [x for x in variants if x.run_id == run.id]
        with_clinvar = len([x for x in v if x.clinical_annotation])
        consequence_counts: dict[str, int] = {}
        for item in v:
            key = item.consequence or "unknown"
            consequence_counts[key] = consequence_counts.get(key, 0) + 1
        return {
            "sample_id": sample_key,
            "variant_count": len(v),
            "clinvar_annotated_count": with_clinvar,
            "consequence_distribution": consequence_counts,
            "non_diagnostic": True,
        }

    if report_type == "prs":
        p = [x for x in prs_results if x.run_id == run.id]
        if not p:
            return {
                "sample_id": sample_key,
                "count": 0,
                "items": [],
                "non_diagnostic": True,
            }
        return {
            "sample_id": sample_key,
            "count": len(p),
            "items": [
                {
                    "trait": x.trait,
                    "score_value": x.score_value,
                    "overlap_pct": x.overlap_pct,
                    "quality_label": x.quality_label,
                    "warning": x.warning,
                }
                for x in p
            ],
            "non_diagnostic": True,
        }

    if report_type == "mtdna":
        m = [x for x in mtdna_results if x.run_id == run.id]
        if not m:
            return {
                "sample_id": sample_key,
                "count": 0,
                "items": [],
                "non_diagnostic": True,
            }
        return {
            "sample_id": sample_key,
            "count": len(m),
            "items": [
                {
                    "haplogroup": x.haplogroup,
                    "heteroplasmy_mean_vaf": x.heteroplasmy_mean_vaf,
                    "num_variants": x.num_variants,
                    "numts_warning": x.numts_warning,
                    "warning_reasons": _mtdna_warning_reasons(x),
                    "trust_score": x.trust_score,
                    "trust_label": x.trust_label,
                }
                for x in m
            ],
            "non_diagnostic": True,
        }

    if report_type == "taxonomy":
        t = [x for x in taxonomy_hits if x.run_id == run.id]
        top = sorted(t, key=lambda x: x.read_count, reverse=True)[:5]
        coverage_summary = _taxonomy_coverage_summary(sorted(t, key=lambda x: x.read_count, reverse=True))
        return {
            "sample_id": sample_key,
            "count": len(t),
            "top_hits": [
                {
                    "organism": x.organism,
                    "rank": x.rank or x.kingdom,
                    "taxid": x.taxid,
                    "top_clade": x.top_clade,
                    "read_count": x.read_count,
                    "confidence": x.confidence,
                    "evidence_score": x.evidence_score,
                    "likely_contaminant": x.likely_contaminant,
                    "breadth_fraction": x.breadth_fraction,
                    "coverage_depth": x.coverage_depth,
                    "coverage_method": x.coverage_method,
                    "support_level": _taxonomy_coverage_profile(x)["support_level"],
                }
                for x in top
            ],
            "coverage_breadth": coverage_summary,
            "non_diagnostic": True,
        }

    if report_type == "giab_benchmark":
        b = [x for x in benchmark_records if x.run_id == run.id]
        if not b:
            return {
                "sample_id": sample_key,
                "count": 0,
                "latest": None,
                "non_diagnostic": True,
            }
        latest = b[-1]
        return {
            "sample_id": sample_key,
            "count": len(b),
            "latest": {
                "benchmark_id": latest.benchmark_id,
                "precision": latest.precision,
                "recall": latest.recall,
                "f1": latest.f1,
                "stratified_metrics": latest.stratified_metrics,
                "regression_alert": latest.regression_alert,
            },
            "non_diagnostic": True,
        }

    if report_type == "trust":
        v = [x for x in variants if x.run_id == run.id]
        avg = round(sum([x.trust_score for x in v]) / len(v), 2) if v else None
        return {
            "sample_id": sample_key,
            "trust_score_avg": avg,
            "label_distribution": {
                "high": len([x for x in v if x.trust_label == "high"]),
                "medium": len([x for x in v if x.trust_label == "medium"]),
                "low": len([x for x in v if x.trust_label == "low"]),
                "unknown": len([x for x in v if x.trust_label == "unknown"]),
            },
            "non_diagnostic": True,
        }

    if report_type == "vendor_validation":
        vals = [x for x in vendor_assembly_validations if x.run_id == run.id]
        if not vals:
            return {
                "sample_id": sample_key,
                "count": 0,
                "status_counts": {"passed": 0, "failed": 0, "unknown": 0},
                "latest": None,
                "non_diagnostic": True,
            }
        latest = vals[-1]
        return {
            "sample_id": sample_key,
            "count": len(vals),
            "status_counts": {
                "passed": len([x for x in vals if x.status == "passed"]),
                "failed": len([x for x in vals if x.status == "failed"]),
                "unknown": len([x for x in vals if x.status == "unknown"]),
            },
            "latest": {
                "validation_id": latest.id,
                "status": latest.status,
                "similarity_score": latest.similarity_score,
                "snv_concordance": latest.snv_concordance,
                "indel_concordance": latest.indel_concordance,
                "structural_concordance": latest.structural_concordance,
                "comparator_method": latest.comparator_method,
                "kmer_size": latest.kmer_size,
                "pass_threshold": latest.pass_threshold,
            },
            "non_diagnostic": True,
        }

    if report_type == "acceptance":
        vals = sorted([x for x in vendor_assembly_validations if x.run_id == run.id], key=lambda x: x.created_at)
        assembly_vals = [x for x in vals if x.comparator_method != "vcf_exact"]
        vcf_vals = [x for x in vals if x.comparator_method == "vcf_exact"]
        decision = _acceptance_decision(vals)
        latest = vals[-1] if vals else None
        return {
            "sample_id": sample_key,
            "status": decision["status"],
            "decision": decision,
            "count": len(vals),
            "status_counts": {
                "passed": len([x for x in vals if x.status == "passed"]),
                "failed": len([x for x in vals if x.status == "failed"]),
                "unknown": len([x for x in vals if x.status == "unknown"]),
            },
            "asset_counts": {
                "assembly": len(assembly_vals),
                "vcf": len(vcf_vals),
            },
            "latest": _validation_report_item(latest) if latest else None,
            "assembly_validations": [_validation_report_item(x) for x in assembly_vals[-5:]],
            "vcf_validations": [_validation_report_item(x) for x in vcf_vals[-5:]],
            "requirements": [
                "Vendor-supplied assembly FASTA or VCF path must be recorded.",
                "Pipeline counterpart assembly FASTA or VCF path must be recorded.",
                "Comparator method and pass threshold must be captured in the validation record.",
                "Acceptance remains a technical gate and must not be interpreted as clinical validation.",
            ],
            "caveats": [
                "Assembly proxy/exact/k-mer scores are not equivalent to GIAB small-variant truth benchmarking.",
                "VCF exact comparison normalizes chromosome prefixes but still compares exact CHROM/POS/REF/ALT alleles.",
                "A pass only means the configured technical threshold was met for the supplied artifacts.",
            ],
            "non_diagnostic": True,
        }

    if report_type == "dark_matter":
        if not sample:
            return {"sample_id": sample_key, "status": "sample_not_found", "items": [], "non_diagnostic": True}
        return _dark_matter_summary_for_sample(sample, run)

    if report_type == "interpretation":
        if not sample:
            return {"sample_id": sample_key, "status": "sample_not_found", "sections": {}, "non_diagnostic": True}
        return _interpretation_report_summary_for_run(sample, run)

    if report_type == "full_technical":
        return {
            "sample_id": sample_key,
            "sections": [
                "qc",
                "alignment",
                "coverage",
                "variant",
                "sv",
                "cnv",
                "annotation",
                "prs",
                "mtdna",
                "taxonomy",
                "giab_benchmark",
                "trust",
                "vendor_validation",
                "acceptance",
                "dark_matter",
                "interpretation",
            ],
            "provenance": {
                "repo_commit": run.repo_commit,
                "nextflow_version": run.nextflow_version,
                "pipeline_version": run.pipeline_version,
            },
            "non_diagnostic": True,
        }

    return {
        "sample_id": sample_key,
        "status": "unsupported_report_type",
        "note": f"No report summary template yet for type={report_type}",
        "non_diagnostic": True,
    }


def _reference_provenance_for_run(run: Run) -> dict:
    ref = next((r for r in references if r.id == run.reference_id), None)
    if not ref:
        return {"id": run.reference_id, "status": "missing", "found": False}
    item = _reference_item(ref)
    keep = [
        "id",
        "version",
        "source",
        "contig_style",
        "mitochondrial_contig",
        "status",
        "builtin",
        "fasta_path",
        "fai_path",
        "dict_path",
        "download_url",
        "download_source_page",
        "download_source_key",
        "download_checksum",
        "local_files_present",
        "local_size_bytes",
    ]
    return {key: item.get(key) for key in keep if key in item}


def _report_context(run: Run) -> dict:
    return {
        "run": {
            "id": run.id,
            "reference_id": run.reference_id,
            "repo_commit": run.repo_commit,
            "pipeline_version": run.pipeline_version,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        },
        "reference": _reference_provenance_for_run(run),
    }


def _with_report_context(run: Run, summary: dict) -> dict:
    enriched = dict(summary)
    enriched.setdefault("run_id", run.id)
    enriched.setdefault("reference", _reference_provenance_for_run(run))
    return enriched


DARK_MATTER_GUARDRAILS = [
    "Unclassified reads are not evidence of a novel organism.",
    "Do not infer pathogen, ancestry, extraterrestrial, engineered, or unknown-life claims from this report.",
    "Counts depend on current reference, alignment settings, taxonomy database, thresholds, and contamination controls.",
    "Manual review requires read-level artifacts, database versions, negative controls, and independent replication.",
]


def _dark_matter_summary_for_sample(sample: Sample, run: Run | None = None) -> dict:
    sample_runs = [r for r in runs if r.sample_id == sample.id]
    selected_run = run or (sample_runs[-1] if sample_runs else None)
    run_ids = {selected_run.id} if selected_run else {r.id for r in sample_runs}
    alignments = [a for a in alignment_metrics if a.run_id in run_ids]
    alignment = alignments[-1] if alignments else None
    tax_hits = [x for x in taxonomy_hits if x.run_id in run_ids]
    unclassified_hits = [
        x for x in tax_hits
        if str(x.kingdom or "").lower() == "unclassified" or "unclassified" in str(x.organism or "").lower()
    ]
    taxonomy_total_reads = sum(max(0, int(x.read_count or 0)) for x in tax_hits)
    taxonomy_unclassified_reads = sum(max(0, int(x.read_count or 0)) for x in unclassified_hits)
    taxonomy_classified_reads = max(0, taxonomy_total_reads - taxonomy_unclassified_reads)
    alignment_unmapped_reads = alignment.unmapped_reads if alignment else None
    unknown_collection = _latest_unknown_reads_collection(run_ids)
    collected_host_unmapped = (unknown_collection.get("host_depletion") or {}).get("unmapped_reads")
    collected_tax_unclassified = (unknown_collection.get("taxonomy_depletion") or {}).get("unclassified")
    collected_contigs = (unknown_collection.get("assembly") or {}).get("contigs")
    collected_no_hit_contigs = (unknown_collection.get("contig_search") or {}).get("no_hits")
    collected_kmers = (unknown_collection.get("kmer_profile") or {}).get("distinct_kmers")
    collected_kmer_clusters = unknown_collection.get("kmer_clusters") or []

    if not alignment and not tax_hits and unknown_collection.get("status") == "not_collected":
        status = "no_data"
    elif (
        taxonomy_unclassified_reads > 0
        or (alignment_unmapped_reads or 0) > 0
        or (collected_host_unmapped or 0) > 0
        or (collected_tax_unclassified or 0) > 0
        or (collected_no_hit_contigs or 0) > 0
    ):
        status = "unclassified_reads_observed"
    elif unknown_collection.get("status") != "not_collected":
        status = "unknown_reads_collected"
    else:
        status = "no_unclassified_signal"

    return {
        "sample_id": sample.sample_id,
        "run_id": selected_run.id if selected_run else None,
        "reference_id": selected_run.reference_id if selected_run else sample.reference_id,
        "status": status,
        "metrics": {
            "alignment_unmapped_reads": alignment_unmapped_reads,
            "mapped_reads_pct": alignment.mapped_reads_pct if alignment else None,
            "taxonomy_total_reads": taxonomy_total_reads,
            "taxonomy_classified_reads": taxonomy_classified_reads,
            "taxonomy_unclassified_reads": taxonomy_unclassified_reads,
            "taxonomy_unclassified_fraction": round(taxonomy_unclassified_reads / taxonomy_total_reads, 6) if taxonomy_total_reads else None,
            "taxonomy_hit_count": len(tax_hits),
            "unclassified_hit_count": len(unclassified_hits),
            "unknown_read_collection_status": unknown_collection.get("status"),
            "unknown_host_unmapped_reads": collected_host_unmapped,
            "unknown_taxonomy_unclassified_reads": collected_tax_unclassified,
            "unknown_assembled_contigs": collected_contigs,
            "unknown_no_hit_contigs": collected_no_hit_contigs,
            "unknown_distinct_kmers": collected_kmers,
            "unknown_kmer_cluster_count": len(collected_kmer_clusters),
        },
        "unknown_read_collection": unknown_collection,
        "top_unclassified": [
            {
                "organism": x.organism,
                "read_count": x.read_count,
                "confidence": x.confidence,
                "evidence_score": x.evidence_score,
                "breadth_fraction": x.breadth_fraction,
                "coverage_depth": x.coverage_depth,
                "support_level": _taxonomy_coverage_profile(x)["support_level"],
                "tools": x.tools,
                "warning": x.warning,
            }
            for x in sorted(unclassified_hits, key=lambda hit: hit.read_count, reverse=True)[:10]
        ],
        "evidence_limits": [
            "Alignment unmapped counts and taxonomy read counts may use different denominators.",
            "Taxonomy may have been run on host-depleted, low-MAPQ, full FASTQ, or custom inputs.",
            "Unknown-read collection can include fallback paths when BAM, taxonomy DB, assembler, or search tools are unavailable.",
            "K-mer clusters are lightweight technical groupings, not organism IDs or novelty claims.",
        ],
        "guardrails": DARK_MATTER_GUARDRAILS,
        "non_diagnostic": True,
    }


def _generate_report_artifact(run: Run, req: ReportGenerateRequest) -> ReportArtifact:
    summary = _with_report_context(run, _build_report_summary(run, req.report_type))
    artifact = ReportArtifact(
        id=f"rpt_{uuid4().hex[:10]}",
        run_id=run.id,
        report_type=req.report_type,
        status="generated",
        html_path=f"results/reports/{run.id}/{req.report_type}.html" if req.include_html else None,
        json_path=f"results/reports/{run.id}/{req.report_type}.json" if req.include_json else None,
        parquet_path=f"results/reports/{run.id}/{req.report_type}.parquet" if req.include_parquet else None,
        summary=summary,
    )

    write_report_artifacts(
        report_type=artifact.report_type,
        summary=artifact.summary,
        html_path=artifact.html_path,
        json_path=artifact.json_path,
        parquet_path=artifact.parquet_path,
    )
    return artifact


@router.post("/runs/{run_id}/reports/generate")
def generate_run_report(run_id: str, req: ReportGenerateRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    report = _generate_report_artifact(run, req)
    add_report(report)
    run.report_ids.append(report.id)
    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="report.generated",
            payload={"report_id": report.id, "report_type": report.report_type},
        )
    )
    add_run_log_line(
        RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message=f"Report generated: {report.id}")
    )

    return report


@router.post("/runs/{run_id}/reports/generate-all")
def generate_all_reports(run_id: str):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    report_types = [
        "qc",
        "alignment",
        "coverage",
        "variant",
        "sv",
        "cnv",
        "annotation",
        "prs",
        "mtdna",
        "taxonomy",
        "giab_benchmark",
        "trust",
        "vendor_validation",
        "acceptance",
        "dark_matter",
        "interpretation",
        "full_technical",
    ]

    created: list[ReportArtifact] = []
    for report_type in report_types:
        artifact = _generate_report_artifact(
            run,
            ReportGenerateRequest(report_type=report_type, include_html=True, include_json=True, include_parquet=True),
        )
        add_report(artifact)
        run.report_ids.append(artifact.id)
        created.append(artifact)

    bundle_items = [
        {
            "report_id": a.id,
            "report_type": a.report_type,
            "status": a.status,
            "html_path": a.html_path,
            "json_path": a.json_path,
            "parquet_path": a.parquet_path,
        }
        for a in created
    ]

    manifest_path = write_report_bundle_manifest(
        run_id=run.id,
        items=bundle_items,
        context=_report_context(run),
    )
    bundle_index_path = write_report_bundle_index_html(
        run_id=run.id,
        items=bundle_items,
        manifest_path=manifest_path,
        context=_report_context(run),
    )

    run.updated_at = datetime.now(timezone.utc).isoformat()
    save_run(run)
    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="report.bundle_generated",
            payload={
                "count": len(created),
                "bundle_manifest_path": manifest_path,
                "bundle_index_path": bundle_index_path,
            },
        )
    )
    add_run_log_line(
        RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message=f"Report bundle generated: {len(created)}")
    )

    return {
        "run_id": run_id,
        "count": len(created),
        "bundle_manifest_path": manifest_path,
        "bundle_index_path": bundle_index_path,
        "items": created,
    }


@router.get("/runs/{run_id}/reports")
def list_run_reports(run_id: str):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    return {"items": [r for r in reports if r.run_id == run_id]}


@router.get("/runs/{run_id}/reports/bundle")
def get_run_report_bundle(run_id: str):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    manifest_path = Path(f"results/reports/{run_id}/bundle_manifest.json")
    index_path = Path(f"results/reports/{run_id}/index.html")

    if not manifest_path.exists():
        return {
            "run_id": run_id,
            "status": "missing",
            "bundle_manifest_path": str(manifest_path),
            "bundle_index_path": str(index_path),
            "count": 0,
            "items": [],
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "run_id": run_id,
            "status": "invalid",
            "bundle_manifest_path": str(manifest_path),
            "bundle_index_path": str(index_path),
            "count": 0,
            "items": [],
        }

    return {
        "run_id": run_id,
        "status": "ready",
        "bundle_manifest_path": str(manifest_path),
        "bundle_index_path": str(index_path),
        "count": int(manifest.get("count", 0) or 0),
        "context": manifest.get("context", {}),
        "items": manifest.get("items", []),
    }


@router.get("/runs/{run_id}/reports/bundle/files")
def get_run_report_bundle_files(run_id: str):
    bundle = get_run_report_bundle(run_id)
    if bundle.get("status") != "ready":
        return {
            "run_id": run_id,
            "status": bundle.get("status", "missing"),
            "count": 0,
            "existing_files": 0,
            "missing_files": 0,
            "items": [],
        }

    items: list[dict] = []
    existing_files = 0
    missing_files = 0

    for item in bundle.get("items", []):
        html_path = item.get("html_path")
        json_path = item.get("json_path")
        parquet_path = item.get("parquet_path")

        html_exists = bool(html_path and Path(str(html_path)).exists())
        json_exists = bool(json_path and Path(str(json_path)).exists())
        parquet_exists = bool(parquet_path and Path(str(parquet_path)).exists())

        existing_files += int(html_exists) + int(json_exists) + int(parquet_exists)
        missing_files += int(bool(html_path) and not html_exists)
        missing_files += int(bool(json_path) and not json_exists)
        missing_files += int(bool(parquet_path) and not parquet_exists)

        items.append(
            {
                **item,
                "html_exists": html_exists,
                "json_exists": json_exists,
                "parquet_exists": parquet_exists,
            }
        )

    return {
        "run_id": run_id,
        "status": "ready",
        "count": len(items),
        "existing_files": existing_files,
        "missing_files": missing_files,
        "items": items,
    }


@router.get("/runs/{run_id}/reports/bundle/verify")
def verify_run_report_bundle(run_id: str):
    bundle = get_run_report_bundle(run_id)
    if bundle.get("status") != "ready":
        return {
            "run_id": run_id,
            "status": bundle.get("status", "missing"),
            "count": 0,
            "checked_files": 0,
            "matched_files": 0,
            "mismatched_files": 0,
            "missing_files": 0,
            "items": [],
        }

    items: list[dict] = []
    checked_files = 0
    matched_files = 0
    mismatched_files = 0
    missing_files = 0

    for item in bundle.get("items", []):
        file_meta = item.get("file_meta") if isinstance(item.get("file_meta"), dict) else {}
        per_file: dict = {}
        problems: list[str] = []

        for key in ["html", "json", "parquet"]:
            expected = file_meta.get(key) if isinstance(file_meta.get(key), dict) else {}
            path = expected.get("path") or item.get(f"{key}_path")
            expected_sha = expected.get("sha256")

            if not path:
                per_file[f"{key}_requested"] = False
                per_file[f"{key}_exists"] = False
                per_file[f"{key}_sha_match"] = None
                per_file[f"{key}_integrity"] = "not_requested"
                continue

            p = Path(str(path))
            exists = p.exists() and p.is_file()
            checked_files += 1

            if not exists:
                missing_files += 1
                problems.append(f"{key}:missing")
                per_file[f"{key}_requested"] = True
                per_file[f"{key}_exists"] = False
                per_file[f"{key}_sha_match"] = False
                per_file[f"{key}_integrity"] = "missing"
                continue

            actual_sha = hashlib.sha256(p.read_bytes()).hexdigest()
            sha_match = bool(expected_sha) and str(expected_sha) == actual_sha
            if sha_match:
                matched_files += 1
            else:
                mismatched_files += 1
                problems.append(f"{key}:sha_mismatch")

            per_file[f"{key}_requested"] = True
            per_file[f"{key}_exists"] = True
            per_file[f"{key}_sha_match"] = sha_match
            per_file[f"{key}_integrity"] = "ok" if sha_match else "sha_mismatch"

        items.append(
            {
                **item,
                **per_file,
                "integrity_status": "ok" if not problems else "degraded",
                "problems": problems,
            }
        )

    status = "ready" if missing_files == 0 and mismatched_files == 0 else "degraded"

    return {
        "run_id": run_id,
        "status": status,
        "count": len(items),
        "checked_files": checked_files,
        "matched_files": matched_files,
        "mismatched_files": mismatched_files,
        "missing_files": missing_files,
        "problem_files": missing_files + mismatched_files,
        "problem_report_types": sorted({str(x.get("report_type")) for x in items if x.get("problems")}),
        "items": items,
    }


@router.post("/runs/{run_id}/reports/bundle/repair")
def repair_run_report_bundle(run_id: str, req: ReportBundleRepairRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    verify_before = verify_run_report_bundle(run.id)
    problem_report_types = {str(x.get("report_type")) for x in verify_before.get("items", []) if x.get("problems")}

    selected = [r for r in reports if r.run_id == run.id]
    wanted = {x.strip().lower() for x in req.report_types if str(x).strip()}
    if wanted:
        selected = [r for r in selected if r.report_type.lower() in wanted]
    if req.only_failed:
        selected = [r for r in selected if r.report_type in problem_report_types]

    available_types = {r.report_type.lower() for r in reports if r.run_id == run.id}
    skipped_report_types = sorted(wanted - available_types)

    repaired: list[dict] = []
    for rep in selected:
        write_report_artifacts(
            report_type=rep.report_type,
            summary=rep.summary,
            html_path=rep.html_path,
            json_path=rep.json_path,
            parquet_path=rep.parquet_path,
        )
        repaired.append(
            {
                "report_id": rep.id,
                "report_type": rep.report_type,
                "status": rep.status,
                "html_path": rep.html_path,
                "json_path": rep.json_path,
                "parquet_path": rep.parquet_path,
            }
        )

    all_bundle_items = [
        {
            "report_id": rep.id,
            "report_type": rep.report_type,
            "status": rep.status,
            "html_path": rep.html_path,
            "json_path": rep.json_path,
            "parquet_path": rep.parquet_path,
        }
        for rep in reports
        if rep.run_id == run.id
    ]
    manifest_path = write_report_bundle_manifest(run_id=run.id, items=all_bundle_items, context=_report_context(run))
    index_path = write_report_bundle_index_html(
        run_id=run.id,
        items=all_bundle_items,
        manifest_path=manifest_path,
        context=_report_context(run),
    )
    verify_after = verify_run_report_bundle(run.id)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="report.bundle_repaired",
            payload={
                "repaired_count": len(repaired),
                "repaired_report_types": [x["report_type"] for x in repaired],
                "skipped_report_types": skipped_report_types,
                "before_problem_files": verify_before.get("problem_files", 0),
                "after_problem_files": verify_after.get("problem_files", 0),
                "bundle_manifest_path": manifest_path,
                "bundle_index_path": index_path,
            },
        )
    )
    add_run_log_line(
        RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message=f"Report bundle repaired: {len(repaired)}")
    )

    return {
        "run_id": run.id,
        "repaired_count": len(repaired),
        "repaired_report_types": [x["report_type"] for x in repaired],
        "skipped_report_types": skipped_report_types,
        "bundle_manifest_path": manifest_path,
        "bundle_index_path": index_path,
        "before": {
            "status": verify_before.get("status"),
            "problem_files": verify_before.get("problem_files", 0),
            "problem_report_types": verify_before.get("problem_report_types", []),
        },
        "after": {
            "status": verify_after.get("status"),
            "problem_files": verify_after.get("problem_files", 0),
            "problem_report_types": verify_after.get("problem_report_types", []),
        },
        "items": repaired,
    }


@router.get("/reports/{report_id}")
def get_report(report_id: str):
    report = next((r for r in reports if r.id == report_id), None)
    if not report:
        raise HTTPException(status_code=404, detail="report_not_found")
    return report


@router.get("/runs/{run_id}/steps")
def get_run_steps(run_id: str):
    return {"items": [s for s in run_steps if s.run_id == run_id]}


@router.get("/runs/{run_id}/events")
def get_run_events(run_id: str):
    events = [e for e in run_events if e.run_id == run_id]
    return {"items": events}


@router.get("/runs/{run_id}/logs")
def get_run_logs(run_id: str):
    lines = [l for l in run_logs if l.run_id == run_id]
    return {"items": lines}


@router.get("/runs/{run_id}/files")
def get_run_files(run_id: str):
    """List result files for a run, with IGV.js-compatible URLs."""
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    result_dir = Path("/data/results") / run_id
    if not result_dir.is_dir():
        return {"run_id": run_id, "files": []}
    sample = next((s for s in samples if s.id == run.sample_id), None)
    sid = sample.sample_id if sample else ""
    files = []
    for f in sorted(result_dir.iterdir()):
        if f.name.startswith("."):
            continue
        rel = f.name
        url = f"/files/data/results/{run_id}/{rel}"
        kind = "other"
        lower = f.name.lower()
        if lower.endswith(".bam"):
            kind = "bam"
        elif lower.endswith(".bai"):
            kind = "bai"
        elif lower.endswith(".vcf.gz"):
            kind = "vcf"
        elif lower.endswith(".vcf.gz.tbi"):
            kind = "tbi"
        elif lower.endswith(".vcf"):
            kind = "vcf"
        elif ".per-base.bed.gz" in lower:
            kind = "coverage"
        elif lower.endswith(".bed.gz"):
            kind = "bed"
        elif lower.endswith(".bed"):
            kind = "bed"
        files.append({"name": rel, "path": str(f), "url": url, "kind": kind, "size": f.stat().st_size})
    return {"run_id": run_id, "sample_id": sid, "files": files}


def _count_data_lines(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    count = 0
    with path.open("rt", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return max(0, count - 1)


def _read_tsv_records(path: Path, limit: int = 200) -> list[dict]:
    if not path.exists() or not path.is_file():
        return []
    records: list[dict] = []
    with path.open("rt", encoding="utf-8", errors="ignore") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        for line in handle:
            if not line.strip():
                continue
            values = line.rstrip("\n").split("\t")
            records.append({key: values[idx] if idx < len(values) else "" for idx, key in enumerate(header)})
            if len(records) >= limit:
                break
    return records


def _read_variant_call_records(path: Path, limit: int = 200) -> list[dict]:
    if not path.exists() or not path.is_file():
        return []
    records: list[dict] = []
    vcf_columns = ["chrom", "pos", "id", "ref", "alt", "qual", "filter", "info", "format", "sample"]
    with path.open("rt", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.strip() or line.startswith("##"):
                continue
            values = line.rstrip("\n").split("\t")
            lowered = [item.lstrip("#").lower() for item in values]
            has_plain_header = {"chrom", "pos", "ref", "alt"}.issubset(set(lowered))
            if values[0].startswith("#") or has_plain_header:
                header = lowered
                for data_line in handle:
                    if not data_line.strip():
                        continue
                    data_values = data_line.rstrip("\n").split("\t")
                    records.append({key: data_values[idx] if idx < len(data_values) else "" for idx, key in enumerate(header)})
                    if len(records) >= limit:
                        return records
                return records
            records.append({key: values[idx] if idx < len(values) else "" for idx, key in enumerate(vcf_columns)})
            if len(records) >= limit:
                break
    return records


def _count_variant_call_records(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    count = 0
    with path.open("rt", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            values = line.rstrip("\n").split("\t")
            lowered = {item.lstrip("#").lower() for item in values}
            if {"chrom", "pos", "ref", "alt"}.issubset(lowered):
                continue
            count += 1
    return count


def _fast_clinvar_artifact_path(run_id: str, filename: str) -> Path:
    return PIPELINE_RESULTS_ROOT / run_id / "clinvar_fast_screen" / filename


@router.get("/runs/{run_id}/clinvar/fast-screen")
def get_run_fast_clinvar_screen(run_id: str):
    """Return ad hoc Fast ClinVar Screening artifacts for a run.

    This is intentionally run-scoped: it reads targeted BAM-screening artifacts
    that can exist before the full variants stage has completed.
    """
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    artifact_dir = PIPELINE_RESULTS_ROOT / run_id / "clinvar_fast_screen"
    report_path = _fast_clinvar_artifact_path(run_id, "fast_screen.highconf.report.tsv")
    calls_path = _fast_clinvar_artifact_path(run_id, "fast_screen.highconf.calls.tsv")
    targets_path = _fast_clinvar_artifact_path(run_id, "clinvar.plp.highconf.targets.tsv")
    log_path = _fast_clinvar_artifact_path(run_id, "fast_screen.highconf.log")

    target_count = _count_data_lines(targets_path)
    raw_call_count = _count_variant_call_records(calls_path)
    exact_match_count = _count_data_lines(report_path)
    matches = _read_tsv_records(report_path)
    raw_calls = _read_variant_call_records(calls_path, limit=50)
    log_tail = ""
    if log_path.exists():
        log_tail = "\n".join(log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-20:])

    status = "missing"
    if report_path.exists():
        status = "no_exact_matches" if exact_match_count == 0 else "matches_found"
    elif artifact_dir.exists():
        status = "partial"

    return {
        "run_id": run_id,
        "sample_id": run.sample_id,
        "status": status,
        "profile": "high_confidence_plp",
        "description": "Pathogenic/Likely pathogenic ClinVar loci reviewed by expert panel or practice guideline, screened directly from the aligned BAM.",
        "target_count": target_count,
        "raw_call_count": raw_call_count,
        "exact_match_count": exact_match_count,
        "matches": matches,
        "raw_calls": raw_calls,
        "artifacts": {
            "directory": str(artifact_dir) if artifact_dir.exists() else None,
            "targets_tsv": str(targets_path) if targets_path.exists() else None,
            "calls_tsv": str(calls_path) if calls_path.exists() else None,
            "report_tsv": str(report_path) if report_path.exists() else None,
            "log": str(log_path) if log_path.exists() else None,
        },
        "log_tail": log_tail,
        "screening_note": "Fast ClinVar Screening is a targeted BAM screen. It is not a clinical negative result and does not replace full variant calling plus full ClinVar annotation.",
    }


@router.get("/runs/{run_id}/variants/status")
def get_run_variant_status(run_id: str):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    sample = next((s for s in samples if s.id == run.sample_id), None)
    return _variant_artifact_status(run, sample)


@router.get("/runs/{run_id}/multiqc")
def get_run_multiqc(run_id: str):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    candidates = [
        Path("/data/results") / "multiqc" / run_id / "multiqc_report.html",
        Path("/data/results") / run_id / "multiqc" / "multiqc_report.html",
        Path("/data/results") / run_id / "multiqc_report.html",
    ]
    report = next((p for p in candidates if p.exists()), None)
    json_candidates = [
        report.with_name("multiqc_data.json") if report else None,
        report.parent / "multiqc_data" / "multiqc_data.json" if report else None,
    ]
    json_path = next((p for p in json_candidates if p and p.exists()), None)
    return {
        "run_id": run_id,
        "report_path": str(report) if report else None,
        "json_path": str(json_path) if json_path else None,
        "status": "available" if report else "missing",
        "note": (
            "MultiQC report artifact found on disk."
            if report
            else "No MultiQC report artifact found for this run."
        ),
    }


@router.post("/runs/{run_id}/qc/import")
def import_qc_artifacts(run_id: str, req: QcImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    fastqc_path = Path(req.fastqc_data_txt) if req.fastqc_data_txt else None
    multiqc_path = Path(req.multiqc_json) if req.multiqc_json else None

    qc = build_qc_summary(
        sample_id=sample.sample_id,
        run_id=run_id,
        fastqc_data_txt=fastqc_path,
        multiqc_json=multiqc_path,
    )

    replace_qc_summary_for_run(run_id, qc)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="qc.imported",
            payload={"status": qc.status, "sources": qc.source_files},
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message="QC artifacts imported"))

    for step in run_steps:
        if step.run_id == run_id and step.step_name == "multiqc":
            step.status = "done"
            step.progress_pct = 100.0
            step.last_log = "multiqc imported"
            step.updated_at = datetime.now(timezone.utc).isoformat()

    return qc


@router.post("/runs/{run_id}/alignment/import")
def import_alignment_metrics(run_id: str, req: AlignmentImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    parsed_flagstat = {}
    parsed_idxstats = {}
    source_files = list(req.source_files)

    if req.flagstat_txt:
        flagstat_path = Path(req.flagstat_txt)
        if not flagstat_path.exists():
            raise HTTPException(status_code=400, detail="flagstat_not_found")
        parsed_flagstat = parse_flagstat_text(flagstat_path)
        if not parsed_flagstat:
            raise HTTPException(status_code=400, detail="flagstat_parse_failed")
        source_files.append(str(flagstat_path))

    if req.idxstats_txt:
        idxstats_path = Path(req.idxstats_txt)
        if not idxstats_path.exists():
            raise HTTPException(status_code=400, detail="idxstats_not_found")
        parsed_idxstats = parse_idxstats_text(idxstats_path)
        if not parsed_idxstats:
            raise HTTPException(status_code=400, detail="idxstats_parse_failed")
        source_files.append(str(idxstats_path))

    mapped_reads_pct = req.mapped_reads_pct if req.mapped_reads_pct is not None else parsed_flagstat.get("mapped_reads_pct")
    properly_paired_pct = (
        req.properly_paired_pct if req.properly_paired_pct is not None else parsed_flagstat.get("properly_paired_pct")
    )
    duplicates_pct = req.duplicates_pct if req.duplicates_pct is not None else parsed_flagstat.get("duplicates_pct")
    mapped_contigs = req.mapped_contigs if req.mapped_contigs is not None else parsed_idxstats.get("mapped_contigs")
    unmapped_reads = req.unmapped_reads if req.unmapped_reads is not None else parsed_flagstat.get("unmapped_reads")

    record = AlignmentMetrics(
        sample_id=sample.sample_id,
        run_id=run.id,
        mapped_reads_pct=mapped_reads_pct,
        properly_paired_pct=properly_paired_pct,
        duplicates_pct=duplicates_pct,
        mapped_contigs=mapped_contigs,
        unmapped_reads=unmapped_reads,
        insert_size_median=req.insert_size_median,
        insert_size_mad=req.insert_size_mad,
        source_files=source_files,
    )

    replace_alignment_metric_for_run(run.id, record)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="alignment.imported",
            payload={
                "mapped_reads_pct": mapped_reads_pct,
                "properly_paired_pct": properly_paired_pct,
                "flagstat_txt": req.flagstat_txt,
                "idxstats_txt": req.idxstats_txt,
            },
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message="Alignment metrics imported"))

    return record


@router.post("/runs/{run_id}/coverage/import")
def import_coverage_metrics(run_id: str, req: CoverageImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    parsed = {}
    summary_path = Path(req.mosdepth_summary_txt) if req.mosdepth_summary_txt else None
    if summary_path:
        if not summary_path.exists():
            raise HTTPException(status_code=400, detail="mosdepth_summary_not_found")
        parsed = parse_mosdepth_summary_txt(summary_path)

    mean_coverage = req.mean_coverage if req.mean_coverage is not None else parsed.get("mean_coverage")
    median_coverage = req.median_coverage if req.median_coverage is not None else parsed.get("median_coverage")
    callable_fraction = req.callable_fraction if req.callable_fraction is not None else parsed.get("callable_fraction")
    coverage_ge_10x = req.coverage_ge_10x if req.coverage_ge_10x is not None else parsed.get("coverage_ge_10x")
    coverage_ge_20x = req.coverage_ge_20x if req.coverage_ge_20x is not None else parsed.get("coverage_ge_20x")
    coverage_ge_30x = req.coverage_ge_30x if req.coverage_ge_30x is not None else parsed.get("coverage_ge_30x")

    if summary_path and mean_coverage is None:
        raise HTTPException(status_code=400, detail="mosdepth_summary_parse_failed")

    source_files = list(req.source_files)
    if summary_path:
        source_files.append(str(summary_path))
    if req.mosdepth_regions_bed_gz:
        regions_path = Path(req.mosdepth_regions_bed_gz)
        if not regions_path.exists():
            raise HTTPException(status_code=400, detail="mosdepth_regions_not_found")
        region_metrics = summarize_mosdepth_regions_thresholds(regions_path)
        if callable_fraction is None:
            callable_fraction = region_metrics.get("callable_fraction")
        if coverage_ge_10x is None:
            coverage_ge_10x = region_metrics.get("coverage_ge_10x")
        if coverage_ge_20x is None:
            coverage_ge_20x = region_metrics.get("coverage_ge_20x")
        if coverage_ge_30x is None:
            coverage_ge_30x = region_metrics.get("coverage_ge_30x")
        source_files.append(str(regions_path))

    record = CoverageMetrics(
        sample_id=sample.sample_id,
        run_id=run.id,
        mean_coverage=mean_coverage,
        median_coverage=median_coverage,
        callable_fraction=callable_fraction,
        coverage_ge_10x=coverage_ge_10x,
        coverage_ge_20x=coverage_ge_20x,
        coverage_ge_30x=coverage_ge_30x,
        source_files=source_files,
    )

    replace_coverage_metric_for_run(run.id, record)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="coverage.imported",
            payload={
                "mean_coverage": mean_coverage,
                "callable_fraction": callable_fraction,
            },
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message="Coverage metrics imported"))

    return record


@router.post("/runs/{run_id}/variants/import")
def import_variant_calls(run_id: str, req: VariantsImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    variant_items = list(req.variants)
    if req.variants_vcf_path:
        vcf_path = Path(req.variants_vcf_path)
        if not vcf_path.exists():
            raise HTTPException(status_code=400, detail="variants_vcf_not_found")
        parsed = parse_variants_vcf(vcf_path)
        if parsed is None:
            raise HTTPException(status_code=400, detail="variants_vcf_parse_failed")
        variant_items.extend([VariantImportItem(**x) for x in parsed])

    if req.replace_existing_for_run:
        delete_variants_by_run(run.id)

    imported_items: list[VariantCall] = []
    for item in variant_items:
        chrom = _normalize_chrom_for_reference(item.chrom, run.reference_id)
        if not chrom:
            raise HTTPException(status_code=400, detail="invalid_variant_chrom")

        ref = item.ref.strip().upper()
        alt = item.alt.strip().upper()
        if not ref or not alt:
            raise HTTPException(status_code=400, detail="invalid_variant_allele")

        caller_score = max(0.0, min(1.0, item.caller_agreement_score))
        score = item.trust_score
        if score is None:
            score = trust_score_100(
                compute_trust_score(
                    caller_agreement_score=caller_score,
                    region_confidence=0.75,
                    mapping_quality_score=0.80,
                    giab_stratified_f1=0.90,
                )
            )
        else:
            score = max(0.0, min(100.0, float(score)))

        vc = VariantCall(
            id=f"var_{uuid4().hex[:10]}",
            sample_id=sample.sample_id,
            run_id=run.id,
            reference_id=run.reference_id,
            chrom=chrom,
            pos=item.pos,
            ref=ref,
            alt=alt,
            variant_type=item.variant_type,
            caller_list=item.caller_list,
            caller_agreement_score=caller_score,
            trust_score=score,
            trust_label=trust_label(score),
            genotype=item.genotype,
            zygosity=item.zygosity,
            explainability=item.explainability,
            clinical_annotation=item.clinical_annotation,
            gnomad_freq=item.gnomad_freq,
            consequence=item.consequence,
        )
        imported_items.append(vc)

    add_variants(imported_items)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="variants.imported",
            payload={
                "count": len(imported_items),
                "replace_existing_for_run": req.replace_existing_for_run,
                "variants_vcf_path": req.variants_vcf_path,
            },
        )
    )
    add_run_log_line(
        RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message=f"Variant calls imported count={len(imported_items)}")
    )

    return {
        "run_id": run.id,
        "sample_id": sample.sample_id,
        "count": len(imported_items),
        "replace_existing_for_run": req.replace_existing_for_run,
        "items": imported_items[:100],
        "items_truncated": len(imported_items) > 100,
    }


@router.post("/runs/{run_id}/variants/import-existing")
def import_existing_variant_vcf(run_id: str, replace_existing_for_run: bool = True):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    sample = next((s for s in samples if s.id == run.sample_id), None)
    vcf_path = _existing_variant_vcf_path(run, sample)
    if not vcf_path:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "existing_variant_vcf_not_found",
                "message": "No reusable VCF artifact was found for this run. Run the variants stage to call variants from BAM, or provide variants_vcf_path to /variants/import.",
            },
        )
    result = import_variant_calls(
        run_id,
        VariantsImportRequest(
            variants_vcf_path=str(vcf_path),
            replace_existing_for_run=replace_existing_for_run,
        ),
    )
    return {
        **result,
        "mode": "existing_vcf_import",
        "variants_vcf_path": str(vcf_path),
        "status_after_import": _variant_artifact_status(run, sample),
    }


@router.post("/runs/{run_id}/sv/import")
def import_structural_variants(run_id: str, req: SVImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    sv_items = list(req.sv)
    if req.sv_vcf_path:
        vcf_path = Path(req.sv_vcf_path)
        if not vcf_path.exists():
            raise HTTPException(status_code=400, detail="sv_vcf_not_found")
        parsed = parse_sv_vcf(vcf_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="sv_vcf_parse_failed")
        sv_items.extend([SVImportItem(**item) for item in parsed])

    if req.replace_existing_for_run:
        delete_structural_variants_by_run(run.id)

    imported: list[StructuralVariant] = []
    for item in sv_items:
        if item.end <= item.start:
            raise HTTPException(status_code=400, detail="invalid_sv_coordinates")

        chrom = _normalize_chrom_for_reference(item.chrom, run.reference_id)
        score = 60.0 if item.trust_score is None else max(0.0, min(100.0, float(item.trust_score)))
        rec = StructuralVariant(
            id=f"sv_{uuid4().hex[:10]}",
            sample_id=sample.sample_id,
            run_id=run.id,
            reference_id=run.reference_id,
            chrom=chrom,
            start=item.start,
            end=item.end,
            sv_type=item.sv_type,
            size_bp=item.size_bp,
            evidence_types=item.evidence_types,
            caller_list=item.caller_list,
            trust_score=score,
            trust_label=trust_label(score),
        )
        imported.append(rec)

    add_structural_variants(imported)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="sv.imported",
            payload={
                "count": len(imported),
                "replace_existing_for_run": req.replace_existing_for_run,
                "sv_vcf_path": req.sv_vcf_path,
            },
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message=f"SV imported count={len(imported)}"))

    return {
        "run_id": run.id,
        "sample_id": sample.sample_id,
        "count": len(imported),
        "replace_existing_for_run": req.replace_existing_for_run,
        "items": imported,
    }


@router.post("/runs/{run_id}/cnv/import")
def import_cnv_segments(run_id: str, req: CNVImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    cnv_items = list(req.segments)
    if req.cnv_segments_tsv_path:
        tsv_path = Path(req.cnv_segments_tsv_path)
        if not tsv_path.exists():
            raise HTTPException(status_code=400, detail="cnv_segments_tsv_not_found")
        parsed = parse_cnv_segments_tsv(tsv_path)
        if not parsed:
            # A real caller may complete successfully yet emit no reportable CNV
            # segments for tiny/synthetic inputs. Treat a header-only/empty file
            # as a valid zero-call result; malformed non-empty files still fail.
            content_lines = [
                ln.strip()
                for ln in tsv_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")
            ]
            if len(content_lines) > 1:
                raise HTTPException(status_code=400, detail="cnv_segments_tsv_parse_failed")
        cnv_items.extend([CNVImportItem(**item) for item in parsed])

    if req.cnv_vcf_path:
        vcf_path = Path(req.cnv_vcf_path)
        if not vcf_path.exists():
            raise HTTPException(status_code=400, detail="cnv_vcf_not_found")
        parsed = parse_cnv_vcf(vcf_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="cnv_vcf_parse_failed")
        cnv_items.extend([CNVImportItem(**item) for item in parsed])

    if req.replace_existing_for_run:
        delete_cnv_segments_by_run(run.id)

    imported: list[CNVSegment] = []
    for item in cnv_items:
        if item.end <= item.start:
            raise HTTPException(status_code=400, detail="invalid_cnv_coordinates")

        chrom = _normalize_chrom_for_reference(item.chrom, run.reference_id)
        score = 58.0 if item.trust_score is None else max(0.0, min(100.0, float(item.trust_score)))
        rec = CNVSegment(
            id=f"cnv_{uuid4().hex[:10]}",
            sample_id=sample.sample_id,
            run_id=run.id,
            reference_id=run.reference_id,
            chrom=chrom,
            start=item.start,
            end=item.end,
            copy_number=item.copy_number,
            cnv_type=item.cnv_type,
            method=item.method,
            trust_score=score,
            trust_label=trust_label(score),
        )
        imported.append(rec)

    add_cnv_segments(imported)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="cnv.imported",
            payload={
                "count": len(imported),
                "replace_existing_for_run": req.replace_existing_for_run,
                "cnv_segments_tsv_path": req.cnv_segments_tsv_path,
                "cnv_vcf_path": req.cnv_vcf_path,
            },
        )
    )
    add_run_log_line(
        RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message=f"CNV segments imported count={len(imported)}")
    )

    return {
        "run_id": run.id,
        "sample_id": sample.sample_id,
        "count": len(imported),
        "replace_existing_for_run": req.replace_existing_for_run,
        "items": imported,
    }


@router.post("/runs/{run_id}/mtdna/import")
def import_mtdna_result(run_id: str, req: MtDNAImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    parsed = {}
    if req.mtdna_report_path:
        report_path = Path(req.mtdna_report_path)
        if not report_path.exists():
            raise HTTPException(status_code=400, detail="mtdna_report_not_found")
        parsed = parse_mtdna_report(report_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="mtdna_report_parse_failed")

    if req.replace_existing_for_run:
        delete_mtdna_hits_by_run(run.id)

    haplogroup = req.haplogroup if req.haplogroup is not None else parsed.get("haplogroup")
    heteroplasmy_mean_vaf = (
        req.heteroplasmy_mean_vaf if req.heteroplasmy_mean_vaf is not None else parsed.get("heteroplasmy_mean_vaf")
    )
    num_variants = req.num_variants if req.num_variants != 0 else parsed.get("num_variants", 0)
    explicit_numts_warning = bool(req.numts_warning or parsed.get("numts_warning", False))
    trust_score_raw = req.trust_score if req.trust_score is not None else parsed.get("trust_score")

    score = 59.0 if trust_score_raw is None else max(0.0, min(100.0, float(trust_score_raw)))
    numts_warning = _infer_numts_warning(
        explicit_warning=explicit_numts_warning,
        heteroplasmy_mean_vaf=heteroplasmy_mean_vaf,
        num_variants=int(num_variants or 0),
        trust_score=score,
    )
    rec = MtDNAResult(
        id=f"mtdna_{uuid4().hex[:10]}",
        sample_id=sample.sample_id,
        run_id=run.id,
        reference_id=run.reference_id,
        haplogroup=haplogroup,
        heteroplasmy_mean_vaf=heteroplasmy_mean_vaf,
        num_variants=num_variants,
        numts_warning=numts_warning,
        trust_score=score,
        trust_label=trust_label(score),
    )
    add_mtdna_hit(rec)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="mtdna.imported",
            payload={
                "haplogroup": haplogroup,
                "num_variants": num_variants,
                "numts_warning": numts_warning,
                "numts_warning_reasons": _mtdna_warning_reasons(rec),
                "mtdna_vcf_path": req.mtdna_vcf_path,
                "mtdna_report_path": req.mtdna_report_path,
            },
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message="mtDNA result imported"))

    return rec


@router.post("/runs/{run_id}/prs/import")
def import_prs_result(run_id: str, req: PRSImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    parsed = {}
    if req.prs_result_path:
        prs_path = Path(req.prs_result_path)
        if not prs_path.exists():
            raise HTTPException(status_code=400, detail="prs_result_not_found")
        parsed = parse_prs_result(prs_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="prs_result_parse_failed")

    if req.replace_existing_for_run:
        delete_prs_results_by_run(run.id)

    trait = req.trait if req.trait is not None else parsed.get("trait")
    score_value = req.score_value if req.score_value is not None else parsed.get("score_value")
    overlap_pct = req.overlap_pct if req.overlap_pct is not None else parsed.get("overlap_pct")
    variant_count_total = req.variant_count_total if req.variant_count_total is not None else parsed.get("variant_count_total")
    variant_count_matched = (
        req.variant_count_matched if req.variant_count_matched is not None else parsed.get("variant_count_matched")
    )
    quality_label = req.quality_label if req.quality_label != "unknown" else parsed.get("quality_label", "unknown")
    warning = req.warning if req.warning is not None else parsed.get("warning")
    non_diagnostic = req.non_diagnostic if req.non_diagnostic is not True else parsed.get("non_diagnostic", True)

    if not trait:
        raise HTTPException(status_code=400, detail="prs_trait_required")
    if score_value is None or overlap_pct is None or variant_count_total is None or variant_count_matched is None:
        raise HTTPException(status_code=400, detail="prs_required_fields_missing")

    rec = PRSResult(
        id=f"prs_{uuid4().hex[:10]}",
        sample_id=sample.sample_id,
        run_id=run.id,
        reference_id=run.reference_id,
        trait=trait,
        score_value=score_value,
        overlap_pct=overlap_pct,
        variant_count_total=variant_count_total,
        variant_count_matched=variant_count_matched,
        quality_label=quality_label,
        warning=warning,
        non_diagnostic=non_diagnostic,
    )
    add_prs_result(rec)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="prs.imported",
            payload={"trait": trait, "score_value": score_value, "prs_result_path": req.prs_result_path},
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message="PRS result imported"))

    return rec


@router.post("/runs/{run_id}/taxonomy/import")
def import_taxonomy_hits(run_id: str, req: TaxonomyImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    hit_items = list(req.hits)
    if req.taxonomy_report_path:
        report_path = Path(req.taxonomy_report_path)
        if not report_path.exists():
            raise HTTPException(status_code=400, detail="taxonomy_report_not_found")
        parsed = parse_taxonomy_report(report_path)
        kraken_report_path = Path(req.kraken_report_path) if req.kraken_report_path else None
        if kraken_report_path and kraken_report_path != report_path:
            parsed = enrich_taxonomy_hits_with_lineage(parsed, kraken_report_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="taxonomy_report_parse_failed")
        hit_items.extend([TaxonomyImportHit(**x) for x in parsed])

    if req.replace_existing_for_run:
        delete_taxonomy_hits_by_run(run.id)

    imported: list[TaxonomyHit] = []
    for hit in hit_items:
        genome_covered_bp = _normalize_taxonomy_int(hit.genome_covered_bp)
        genome_length_bp = _normalize_taxonomy_int(hit.genome_length_bp)
        breadth_fraction = _normalize_taxonomy_fraction(hit.breadth_fraction)
        if breadth_fraction is None and genome_covered_bp is not None and genome_length_bp:
            breadth_fraction = _normalize_taxonomy_fraction(genome_covered_bp / genome_length_bp)
        rec = TaxonomyHit(
            id=f"tax_{uuid4().hex[:10]}",
            sample_id=sample.sample_id,
            run_id=run.id,
            reference_id=run.reference_id,
            organism=hit.organism,
            kingdom=hit.kingdom,
            rank=hit.rank or hit.kingdom,
            taxid=hit.taxid,
            lineage=hit.lineage,
            top_clade=hit.top_clade,
            read_count=hit.read_count,
            confidence=hit.confidence,
            evidence_score=hit.evidence_score,
            tools=hit.tools,
            likely_contaminant=hit.likely_contaminant,
            warning=hit.warning,
            breadth_fraction=breadth_fraction,
            coverage_depth=_normalize_taxonomy_float(hit.coverage_depth),
            genome_covered_bp=genome_covered_bp,
            genome_length_bp=genome_length_bp,
            coverage_method=hit.coverage_method,
            non_diagnostic=True,
        )
        imported.append(rec)

    add_taxonomy_hits(imported)
    coverage_summary = _taxonomy_coverage_summary(imported)
    provenance = {
        "taxonomy_report_path": req.taxonomy_report_path,
        "taxonomy_mode": req.taxonomy_mode,
        "taxonomy_input_mode": req.taxonomy_input_mode,
        "taxonomy_input_r1": req.taxonomy_input_r1,
        "taxonomy_input_r2": req.taxonomy_input_r2,
        "host_bam": req.host_bam,
        "host_unmapped_records": req.host_unmapped_records,
        "taxonomy_database": req.taxonomy_database,
        "taxonomy_refinement": req.taxonomy_refinement,
        "taxonomy_refinement_status": req.taxonomy_refinement_status,
        "kraken_report_path": req.kraken_report_path,
        "bracken_report_path": req.bracken_report_path,
        "bracken_level": req.bracken_level,
        "bracken_read_length": req.bracken_read_length,
        "taxonomy_route": req.taxonomy_route,
        "taxonomy_analysis_id": req.taxonomy_analysis_id,
        "taxonomy_analysis_version": req.taxonomy_analysis_version,
        "taxonomy_extraction_params": req.taxonomy_extraction_params,
        "taxonomy_database_version": req.taxonomy_database_version,
        "host_reference": req.host_reference,
        "taxonomy_coverage_available_count": coverage_summary["available_count"],
        "taxonomy_read_count_only_count": coverage_summary["read_count_only_count"],
    }
    provenance = {k: v for k, v in provenance.items() if v not in (None, {}, "")}

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="taxonomy.imported",
            payload={"count": len(imported), **provenance},
        )
    )
    add_run_log_line(
        RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message=f"Taxonomy hits imported count={len(imported)}")
    )
    _mark_ingested_stage_done(run.id, "taxonomy", last_log=f"taxonomy ingested count={len(imported)}")

    return {
        "run_id": run.id,
        "sample_id": sample.sample_id,
        "count": len(imported),
        "replace_existing_for_run": req.replace_existing_for_run,
        "provenance": provenance,
        "coverage_breadth": coverage_summary,
        "items": imported,
    }


@router.post("/samples/{sample_pk}/taxonomy/recover")
def recover_taxonomy_from_report(sample_pk: str, req: TaxonomyRecoverRequest):
    sample = next((s for s in samples if s.id == sample_pk), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")
    if not req.taxonomy_report_path:
        raise HTTPException(status_code=400, detail="taxonomy_report_path_required")

    report_path = Path(req.taxonomy_report_path)
    if not report_path.exists():
        raise HTTPException(status_code=400, detail="taxonomy_report_not_found")

    target_run_id = (req.run_id or "").strip() or f"run_{uuid4().hex[:10]}"
    if not target_run_id.startswith("run_") or not re.fullmatch(r"run_[A-Za-z0-9_-]{4,64}", target_run_id):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_recovery_run_id", "message": "Recovery run id must look like run_..."},
        )

    existing = next((r for r in runs if r.id == target_run_id), None)
    created = False
    if existing:
        if existing.sample_id != sample.id:
            raise HTTPException(
                status_code=409,
                detail={"code": "recovery_run_belongs_to_different_sample", "run_id": target_run_id},
            )
        run = existing
    else:
        parent = next((r for r in runs if r.id == req.parent_run_id), None) if req.parent_run_id else None
        if req.parent_run_id and (not parent or parent.sample_id != sample.id):
            raise HTTPException(
                status_code=404,
                detail={"code": "parent_run_not_found_for_sample", "parent_run_id": req.parent_run_id},
            )
        run = Run(
            id=target_run_id,
            project_id=sample.project_id,
            sample_id=sample.id,
            mode="taxonomy",
            status="done",
            reference_id=sample.reference_id,
            parameters={
                "taxonomy_subrun": True,
                "parent_run_id": req.parent_run_id,
                "recovered_from_backup": True,
                "taxonomy_report_path": req.taxonomy_report_path,
                "taxonomy_database": req.taxonomy_database,
                "taxonomy_route": req.taxonomy_route,
                "taxonomy_input_mode": req.taxonomy_input_mode,
                "stages": ["taxonomy"],
            },
        )
        add_run(run)
        _append_step(run.id, "input_validation", status="done")
        _append_step(run.id, "taxonomy", status="done")
        add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message="Taxonomy run recovered from report backup"))
        created = True

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="taxonomy.recovery_requested",
            payload={
                "taxonomy_report_path": req.taxonomy_report_path,
                "parent_run_id": req.parent_run_id,
                "created_run": created,
            },
        )
    )

    result = import_taxonomy_hits(run.id, TaxonomyImportRequest(**req.model_dump(exclude={"run_id", "parent_run_id"})))
    run.status = "done"
    run.updated_at = datetime.now(timezone.utc).isoformat()
    run.parameters = {
        **(run.parameters or {}),
        "taxonomy_subrun": run.mode == "taxonomy",
        "parent_run_id": req.parent_run_id or (run.parameters or {}).get("parent_run_id"),
        "recovered_from_backup": True,
        "taxonomy_report_path": req.taxonomy_report_path,
        "taxonomy_database": req.taxonomy_database or (run.parameters or {}).get("taxonomy_database"),
        "taxonomy_route": req.taxonomy_route or (run.parameters or {}).get("taxonomy_route"),
        "taxonomy_input_mode": req.taxonomy_input_mode or (run.parameters or {}).get("taxonomy_input_mode"),
    }
    save_run(run)
    return {**result, "created_run": created, "recovered_run_id": run.id}


@router.post("/runs/{run_id}/dark-matter/unknown-reads/import")
def import_unknown_reads_collection(run_id: str, req: UnknownReadsImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    host = dict(req.host_depletion or {})
    taxonomy = dict(req.taxonomy_depletion or {})
    assembly = dict(req.assembly or {})
    contig_search = dict(req.contig_search or {})
    kmer_profile = dict(req.kmer_profile or {})
    files = _clean_unknown_reads_files(req.files)

    payload = {
        "sample_id": sample.sample_id,
        "run_id": run.id,
        "status": req.status or "imported",
        "collection_mode": req.collection_mode or ("host_bam_unmapped_pairs" if req.host_bam else "fastq_fallback_or_external"),
        "host_bam": req.host_bam,
        "taxonomy_database": req.taxonomy_database,
        "host_depletion": {
            "total_reads": _normalize_unknown_reads_int(host.get("total_reads") or host.get("total")),
            "unmapped_reads": _normalize_unknown_reads_int(host.get("unmapped_reads") or host.get("unmapped")),
            "tool": host.get("tool") or ("samtools" if req.host_bam else "none"),
        },
        "taxonomy_depletion": {
            "tool": taxonomy.get("tool") or "none",
            "classified": _normalize_unknown_reads_int(taxonomy.get("classified")),
            "unclassified": _normalize_unknown_reads_int(taxonomy.get("unclassified")),
        },
        "assembly": {
            "tool": assembly.get("tool") or "none",
            "contigs": _normalize_unknown_reads_int(assembly.get("contigs")) or 0,
            "total_bp": _normalize_unknown_reads_int(assembly.get("total_bp")) or 0,
            "n50": _normalize_unknown_reads_int(assembly.get("n50")) or 0,
        },
        "contig_search": {
            "tool": contig_search.get("tool") or contig_search.get("search_tool") or "none",
            "total_contigs": _normalize_unknown_reads_int(contig_search.get("total_contigs")) or 0,
            "with_hits": _normalize_unknown_reads_int(contig_search.get("with_hits")) or 0,
            "no_hits": _normalize_unknown_reads_int(contig_search.get("no_hits")) or 0,
        },
        "kmer_profile": {
            "tool": kmer_profile.get("tool") or "internal_kmer_counter",
            "status": kmer_profile.get("status") or "not_run",
            "kmer_size": _normalize_unknown_reads_int(kmer_profile.get("kmer_size")),
            "reads_scanned": _normalize_unknown_reads_int(kmer_profile.get("reads_scanned")),
            "distinct_kmers": _normalize_unknown_reads_int(kmer_profile.get("distinct_kmers")) or 0,
            "top_kmers": kmer_profile.get("top_kmers", []),
        },
        "kmer_clusters": [item for item in req.kmer_clusters if isinstance(item, dict)],
        "files": files,
        "source_files": [str(path) for path in req.source_files if path],
        "notes": [str(note) for note in req.notes if note],
        "non_diagnostic": True,
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "", [], {})}

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="dark_matter.unknown_reads_imported",
            payload=payload,
        )
    )
    add_run_log_line(
        RunLogLine(
            run_id=run.id,
            line_no=len(run_logs) + 1,
            message=(
                "Unknown-read collection imported "
                f"unclassified={payload.get('taxonomy_depletion', {}).get('unclassified')} "
                f"contigs={payload.get('assembly', {}).get('contigs')}"
            ),
        )
    )
    return payload


@router.post("/runs/{run_id}/ingest")
def auto_ingest_run_stage(run_id: str, req: AutoIngestRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    stage = req.stage.strip().lower()
    payload = req.payload or {}

    if stage == "qc":
        result = import_qc_artifacts(
            run_id,
            QcImportRequest(
                fastqc_data_txt=payload.get("fastqc_data_txt"),
                multiqc_json=payload.get("multiqc_json"),
            ),
        )
    elif stage == "alignment":
        result = import_alignment_metrics(
            run_id,
            AlignmentImportRequest(
                flagstat_txt=payload.get("flagstat_txt") or payload.get("alignment_flagstat_path"),
                idxstats_txt=payload.get("idxstats_txt") or payload.get("alignment_idxstats_path"),
                mapped_reads_pct=payload.get("mapped_reads_pct"),
                properly_paired_pct=payload.get("properly_paired_pct"),
                duplicates_pct=payload.get("duplicates_pct"),
                mapped_contigs=payload.get("mapped_contigs"),
                unmapped_reads=payload.get("unmapped_reads"),
                insert_size_median=payload.get("insert_size_median"),
                insert_size_mad=payload.get("insert_size_mad"),
                source_files=payload.get("source_files", []),
            ),
        )
    elif stage == "coverage":
        result = import_coverage_metrics(
            run_id,
            CoverageImportRequest(
                mean_coverage=payload.get("mean_coverage"),
                median_coverage=payload.get("median_coverage"),
                callable_fraction=payload.get("callable_fraction"),
                coverage_ge_10x=payload.get("coverage_ge_10x"),
                coverage_ge_20x=payload.get("coverage_ge_20x"),
                coverage_ge_30x=payload.get("coverage_ge_30x"),
                mosdepth_summary_txt=payload.get("mosdepth_summary_txt"),
                mosdepth_regions_bed_gz=payload.get("mosdepth_regions_bed_gz"),
                source_files=payload.get("source_files", []),
            ),
        )
    elif stage == "benchmark":
        result = import_benchmark_metrics(
            run_id,
            BenchmarkImportRequest(
                benchmark_id=payload.get("benchmark_id"),
                precision=payload.get("precision"),
                recall=payload.get("recall"),
                f1=payload.get("f1"),
                stratified_metrics=payload.get("stratified_metrics", {}),
                benchmark_report_path=payload.get("benchmark_report_path") or payload.get("benchmark_report"),
            ),
        )
    elif stage == "variants":
        result = import_variant_calls(
            run_id,
            VariantsImportRequest(
                variants=[VariantImportItem(**v) for v in payload.get("variants", []) if isinstance(v, dict)],
                variants_vcf_path=payload.get("variants_vcf_path") or payload.get("variants_vcf"),
                replace_existing_for_run=payload.get("replace_existing_for_run", True),
            ),
        )
    elif stage == "annotation":
        result = import_variant_calls(
            run_id,
            VariantsImportRequest(
                variants=[],
                variants_vcf_path=payload.get("annotated_vcf_path")
                or payload.get("annotated_vcf_gz_path")
                or payload.get("variants_vcf_path"),
                replace_existing_for_run=payload.get("replace_existing_for_run", True),
            ),
        )
    elif stage == "sv":
        result = import_structural_variants(
            run_id,
            SVImportRequest(
                sv=[SVImportItem(**v) for v in payload.get("sv", []) if isinstance(v, dict)],
                sv_vcf_path=payload.get("sv_vcf_path") or payload.get("sv_vcf"),
                replace_existing_for_run=payload.get("replace_existing_for_run", True),
            ),
        )
    elif stage == "cnv":
        result = import_cnv_segments(
            run_id,
            CNVImportRequest(
                segments=[CNVImportItem(**v) for v in payload.get("segments", []) if isinstance(v, dict)],
                cnv_segments_tsv_path=payload.get("cnv_segments_tsv_path") or payload.get("cnv_tsv"),
                cnv_vcf_path=payload.get("cnv_vcf_path") or payload.get("cnv_vcf"),
                replace_existing_for_run=payload.get("replace_existing_for_run", True),
            ),
        )
    elif stage == "mtdna":
        result = import_mtdna_result(
            run_id,
            MtDNAImportRequest(
                haplogroup=payload.get("haplogroup"),
                heteroplasmy_mean_vaf=payload.get("heteroplasmy_mean_vaf"),
                num_variants=payload.get("num_variants", 0),
                numts_warning=payload.get("numts_warning", False),
                trust_score=payload.get("trust_score"),
                mtdna_vcf_path=payload.get("mtdna_vcf_path") or payload.get("mtdna_vcf"),
                mtdna_report_path=payload.get("mtdna_report_path") or payload.get("mtdna_report"),
                replace_existing_for_run=payload.get("replace_existing_for_run", True),
            ),
        )
    elif stage == "prs":
        result = import_prs_result(
            run_id,
            PRSImportRequest(
                trait=payload.get("trait"),
                score_value=payload.get("score_value"),
                overlap_pct=payload.get("overlap_pct"),
                variant_count_total=payload.get("variant_count_total"),
                variant_count_matched=payload.get("variant_count_matched"),
                quality_label=payload.get("quality_label", "unknown"),
                warning=payload.get("warning"),
                non_diagnostic=payload.get("non_diagnostic", True),
                prs_result_path=payload.get("prs_result_path") or payload.get("prs_result"),
                replace_existing_for_run=payload.get("replace_existing_for_run", True),
            ),
        )
    elif stage == "taxonomy":
        result = import_taxonomy_hits(
            run_id,
            TaxonomyImportRequest(
                hits=[TaxonomyImportHit(**v) for v in payload.get("hits", []) if isinstance(v, dict)],
                taxonomy_report_path=payload.get("taxonomy_report_path") or payload.get("taxonomy_report"),
                replace_existing_for_run=payload.get("replace_existing_for_run", True),
                taxonomy_mode=payload.get("taxonomy_mode"),
                taxonomy_input_mode=payload.get("taxonomy_input_mode"),
                taxonomy_input_r1=payload.get("taxonomy_input_r1"),
                taxonomy_input_r2=payload.get("taxonomy_input_r2"),
                host_bam=payload.get("host_bam"),
                host_unmapped_records=payload.get("host_unmapped_records"),
                taxonomy_database=payload.get("taxonomy_database") or payload.get("taxonomy_database_path"),
                taxonomy_refinement=payload.get("taxonomy_refinement"),
                taxonomy_refinement_status=payload.get("taxonomy_refinement_status"),
                kraken_report_path=payload.get("kraken_report_path"),
                bracken_report_path=payload.get("bracken_report_path"),
                bracken_level=payload.get("bracken_level"),
                bracken_read_length=payload.get("bracken_read_length"),
                taxonomy_route=payload.get("taxonomy_route"),
                taxonomy_analysis_id=payload.get("taxonomy_analysis_id"),
                taxonomy_analysis_version=payload.get("taxonomy_analysis_version"),
                taxonomy_extraction_params=payload.get("taxonomy_extraction_params", {}),
                taxonomy_database_version=payload.get("taxonomy_database_version"),
                host_reference=payload.get("host_reference"),
            ),
        )
    elif stage == "unknown_reads":
        result = import_unknown_reads_collection(
            run_id,
            UnknownReadsImportRequest(
                status=payload.get("status", "imported"),
                host_depletion=payload.get("host_depletion", {}),
                taxonomy_depletion=payload.get("taxonomy_depletion", {}),
                assembly=payload.get("assembly", {}),
                contig_search=payload.get("contig_search", {}),
                kmer_profile=payload.get("kmer_profile", {}),
                kmer_clusters=payload.get("kmer_clusters", []),
                files=payload.get("files", {}),
                source_files=payload.get("source_files", []),
                collection_mode=payload.get("collection_mode"),
                host_bam=payload.get("host_bam"),
                taxonomy_database=payload.get("taxonomy_database"),
                notes=payload.get("notes", []),
                non_diagnostic=payload.get("non_diagnostic", True),
            ),
        )
    elif stage == "vendor_validation":
        result = import_vendor_assembly_validation(
            run_id,
            VendorAssemblyValidationImportRequest(
                vendor_assembly_path=payload.get("vendor_assembly_path") or payload.get("vendor_assembly"),
                pipeline_assembly_path=payload.get("pipeline_assembly_path") or payload.get("pipeline_assembly"),
                vendor_validation_report_path=payload.get("vendor_validation_report_path")
                or payload.get("vendor_validation_report"),
                similarity_score=payload.get("similarity_score"),
                snv_concordance=payload.get("snv_concordance"),
                indel_concordance=payload.get("indel_concordance"),
                structural_concordance=payload.get("structural_concordance"),
                comparator_method=payload.get("comparator_method", "proxy"),
                kmer_size=payload.get("kmer_size"),
                pass_threshold=payload.get("pass_threshold", 0.98),
                summary=payload.get("summary", {}),
                non_diagnostic=payload.get("non_diagnostic", True),
            ),
        )
    else:
        raise HTTPException(status_code=400, detail="unsupported_stage")

    _mark_ingested_stage_done(run_id, stage)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="run.ingest.auto",
            payload={"stage": stage},
        )
    )

    return {"run_id": run_id, "stage": stage, "result": result}


@router.get("/events/stream")
def events_stream():
    def gen():
        yield "event: info\ndata: {\"message\": \"SSE scaffold active\"}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/samples/{sample_id}/qc-summary")
def get_qc_summary(sample_id: str):
    items = [q for q in qc_summaries if q.sample_id == sample_id]
    if not items:
        raise HTTPException(status_code=404, detail="qc_summary_not_found")
    return items[-1]


@router.get("/samples/{sample_id}/coverage-summary")
def get_coverage_summary(sample_id: str, run_id: str | None = None):
    sample = next((s for s in samples if s.sample_id == sample_id or s.id == sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")
    sample_key = sample.sample_id

    run_ids = {r.id for r in runs if r.sample_id == sample.id}
    if run_id:
        run_ids = {run_id} if run_id in run_ids else set()
    c = next((x for x in reversed(coverage_metrics) if x.run_id in run_ids), None)

    return {
        "sample_id": sample_id,
        "status": "imported" if c else "missing",
        "mean_coverage": c.mean_coverage if c else None,
        "median_coverage": c.median_coverage if c else None,
        "callable_fraction": c.callable_fraction if c else None,
        "coverage_ge_20x": c.coverage_ge_20x if c else None,
        "note": (
            "Imported mosdepth summary metrics are available."
            if c
            else "Coverage has not been imported for this sample."
        ),
    }


def _coverage_primary_contig_key(contig: str | None) -> str:
    key = re.sub(r"^chr", "", str(contig or ""), flags=re.IGNORECASE)
    return "M" if key in {"MT", "Mt", "m", "M"} else key


def _is_coverage_primary_contig(contig: str | None) -> bool:
    key = _coverage_primary_contig_key(contig)
    return bool(re.match(r"^(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)$", key))


def _other_contig_read_counts(run_id: str) -> list[dict]:
    alignment = next((x for x in reversed(alignment_metrics) if x.run_id == run_id), None)
    if not alignment:
        return []

    idxstats_source = next((p for p in reversed(alignment.source_files) if "idxstats" in Path(p).name.lower()), None)
    if not idxstats_source:
        return []

    parsed = parse_idxstats_text(Path(idxstats_source))
    rows = [
        {
            "contig": row.get("chr"),
            "length": row.get("length"),
            "reads": row.get("reads", 0),
            "unmapped": row.get("unmapped", 0),
            "pct": row.get("pct", 0.0),
        }
        for row in parsed.get("contigs", [])
        if not _is_coverage_primary_contig(row.get("chr")) and int(row.get("reads") or 0) > 0
    ]
    rows.sort(key=lambda row: (int(row.get("reads") or 0), str(row.get("contig") or "")), reverse=True)
    return rows


@router.get("/samples/{sample_id}/coverage-tiles")
def get_coverage_tiles(sample_id: str, level: str = "1mb", run_id: str | None = None):
    sample = next((s for s in samples if s.sample_id == sample_id or s.id == sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")
    sample_key = sample.sample_id

    run_ids = {r.id for r in runs if r.sample_id == sample.id}
    if run_id:
        run_ids = {run_id} if run_id in run_ids else set()
    c = next((x for x in reversed(coverage_metrics) if x.run_id in run_ids), None)
    if not c:
        return {
            "sample_id": sample_id,
            "level": level,
            "status": "missing",
            "mode": "not_imported",
            "tiles": [],
            "note": "Coverage has not been imported for this sample; no terrain bars are available.",
        }

    level_key = level.strip().lower()
    bin_size = {"5mb": 5_000_000, "1mb": 1_000_000, "500kb": 500_000}.get(level_key, 1_000_000)
    base = c.mean_coverage or c.median_coverage or 0.0

    low_threshold = max(10.0, base * 0.70)
    high_threshold = max(20.0, base * 1.25)

    regions_source = next(
        (
            s
            for s in reversed(c.source_files)
            if s.endswith(".regions.bed.gz") or s.endswith(".regions.bed") or s.endswith("regions.bed.gz")
        ),
        None,
    )

    tiles = []
    mode = "summary_only"
    if regions_source:
        rows = parse_mosdepth_regions(Path(regions_source))
        if rows:
            tiles = build_tiles_from_regions(rows=rows, level=level_key)
            mode = "materialized"

    tiles = annotate_reference_masks(tiles, reference_id=sample.reference_id)
    tiles = annotate_coverage_interpretation_tracks(tiles, reference_id=sample.reference_id)

    for i, tile in enumerate(tiles):
        depth = float(tile.get("coverage", 0.0))
        if depth <= low_threshold:
            anomaly = "reference_masked" if (tile.get("reference_masked") or tile.get("coverage_track_explained")) else "low"
        elif depth >= high_threshold:
            anomaly = "high"
        else:
            anomaly = "normal"
        tile["coverage"] = round(depth, 2)
        tile["anomaly"] = anomaly
        tile["tile_id"] = f"{sample_id}:{level_key}:{i + 1}"

    reference_mask_summary = summarize_reference_masks(tiles)
    reference_track_summary = summarize_coverage_interpretation_tracks(tiles)
    primary_tiles = [tile for tile in tiles if _is_coverage_primary_contig(tile.get("contig"))]
    other_contigs = _other_contig_read_counts(c.run_id)

    return {
        "sample_id": sample_id,
        "level": level,
        "status": "imported",
        "mode": mode,
        "mean_coverage": c.mean_coverage,
        "median_coverage": c.median_coverage,
        "low_threshold": round(low_threshold, 2),
        "high_threshold": round(high_threshold, 2),
        "reference_mask_summary": reference_mask_summary,
        "reference_track_summary": reference_track_summary,
        "display_contigs": [f"chr{i}" for i in range(1, 23)] + ["chrX", "chrY", "chrM"],
        "primary_tile_count": len(primary_tiles),
        "other_contigs": other_contigs,
        "tiles": tiles,
        "note": (
            "Coverage tiles materialized from mosdepth regions input with reference mask/track annotations."
            if mode == "materialized"
            else "Coverage summary is imported, but no mosdepth regions file was imported; terrain bars are intentionally not synthesized."
        ),
    }


@router.get("/samples/{sample_id}/coverage-terrain")
def get_coverage_terrain(sample_id: str, level: str = "1mb"):
    payload = get_coverage_tiles(sample_id=sample_id, level=level)
    tiles = payload.get("tiles", [])

    if payload.get("status") != "imported":
        return {
            "sample_id": sample_id,
            "level": level,
            "status": "missing",
            "mode": "not_imported",
            "overlay": {"low": [], "high": []},
            "summary": {
                "tile_count": 0,
                "low_count": 0,
                "high_count": 0,
                "normal_count": 0,
            },
            "note": "Coverage has not been imported for this sample; no terrain overlays are available.",
        }

    low = [t for t in tiles if t.get("anomaly") == "low"]
    high = [t for t in tiles if t.get("anomaly") == "high"]
    reference_masked = [t for t in tiles if t.get("reference_masked")]
    track_explained = [t for t in tiles if t.get("coverage_track_explained")]
    normal_count = len([t for t in tiles if t.get("anomaly") == "normal"])

    return {
        "sample_id": sample_id,
        "level": level,
        "status": "imported",
        "overlay": {"low": low, "high": high, "reference_masked": reference_masked, "track_explained": track_explained},
        "summary": {
            "tile_count": len(tiles),
            "low_count": len(low),
            "high_count": len(high),
            "reference_masked_count": len(reference_masked),
            "track_explained_count": len(track_explained),
            "normal_count": normal_count,
        },
        "note": (
            "No coverage terrain bars are available because mosdepth regions were not imported."
            if payload.get("mode") == "summary_only"
            else "Low/high diagnostic overlay plus reference mask and coverage-track annotations derived from imported coverage metrics."
        ),
    }


def _resolve_sample_key(sample_id: str) -> str:
    """Resolve sample_id from either internal PK (smp_xxx) or human-readable ID."""
    sample = next((s for s in samples if s.id == sample_id), None)
    return sample.sample_id if sample else sample_id


def _agreement_bucket(v: VariantCall) -> str:
    if v.caller_agreement_score >= 0.75 and len(v.caller_list) >= 2:
        return "consensus"
    if v.caller_agreement_score < 0.5 or len(v.caller_list) <= 1:
        return "disagreement"
    return "mixed"


@router.get("/samples/{sample_id}/variants")
def list_sample_variants(sample_id: str, min_trust: float = 0.0, run_id: str | None = None):
    sample = next((s for s in samples if s.sample_id == sample_id or s.id == sample_id), None)
    key = sample.sample_id if sample else sample_id
    items = [v for v in variants if v.sample_id == key and v.trust_score >= min_trust]
    if run_id:
        items = [v for v in items if v.run_id == run_id]
    return {"items": items, "count": len(items)}


def _resolve_sample_or_404(sample_id: str) -> Sample:
    sample = next((s for s in samples if s.sample_id == sample_id or s.id == sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")
    return sample


def _latest_run_for_sample(sample: Sample) -> Run | None:
    sample_runs = [r for r in runs if r.sample_id in {sample.id, sample.sample_id}]
    sample_runs.sort(key=lambda r: r.created_at or "", reverse=True)
    return sample_runs[0] if sample_runs else None


def _reference_for_sample(sample: Sample):
    return next((r for r in references if r.id == sample.reference_id), None)


def _latest_mtdna_vcf_for_run(run: Run | None) -> tuple[Path | None, str | None]:
    if not run:
        return None, None

    for event in sorted(
        [ev for ev in run_events if ev.run_id == run.id and ev.event_type == "mtdna.imported"],
        key=lambda ev: ev.created_at or "",
        reverse=True,
    ):
        for key in ("mtdna_vcf_path", "mtdna_vcf"):
            value = event.payload.get(key)
            if value:
                path = Path(value)
                if path.exists() and path.is_file():
                    return path, f"run_event:{key}"

    output_dir = Path("/data/results") / run.id
    if not output_dir.exists():
        return None, None
    for pattern in (
        "*.mtdna.vcf",
        "*.mtdna.vcf.gz",
        "*mtdna*.vcf",
        "*mtdna*.vcf.gz",
        "*.mt.vcf",
        "*.mt.vcf.gz",
    ):
        matches = sorted(path for path in output_dir.glob(pattern) if path.is_file())
        if matches:
            return matches[0], f"artifact_glob:{pattern}"
    return None, None


def _variants_for_sample(sample: Sample) -> list[VariantCall]:
    return [v for v in variants if v.sample_id == sample.sample_id]


@router.get("/interpretation/resources")
def interpretation_resources():
    status = interpretation_tool_status()
    registry = [r.model_dump() for r in interpretation_resource_registry()]
    traits_validation = validate_traits_manifest()
    pgx_validation = validate_pgx_rules_manifest()
    return {
        "status": status,
        "registry": registry,
        "resources_by_module": resources_by_module(),
        "modules": {
            "provenance": {"ready": True},
            "build_validation": {"ready": True, "requires": ["reference metadata", "imported variants"]},
            "clinvar_monogenic": {"ready": bool(status.get("clinvar_tsv")), "requires": ["ClinVar exact-match TSV", "normalized variants"], "pipeline": clinvar_resource_pipeline_status()},
            "acmg_secondary_findings": {"ready": bool(status.get("clinvar_tsv")), "version": ACMG_SF_VERSION, "gene_count": len(ACMG_SF_GENES), "opt_in_required": True},
            "pharmcat_pgx": {"ready": bool(status.get("pharmcat")), "requires": ["PharmCAT", "normalized VCF"]},
            "cpic_pharmgkb_rules": {
                "ready": bool(pgx_validation.get("valid")),
                "requires": ["curated CPIC/PharmGKB rule manifest", "exact variant matches", "source/version metadata"],
                "validation": pgx_validation,
            },
            "cyp2d6_specialized": {"ready": bool(status.get("cyrius") or status.get("stellarpgx")), "requires": ["Cyrius or StellarPGx", "WGS BAM/CRAM"]},
            "haplogrep_mtdna": {"ready": bool(status.get("haplogrep")), "requires": ["HaploGrep", "mtDNA variants"]},
            "vep_annotation": {"ready": bool(status.get("vep")), "requires": ["VEP offline cache"]},
            "traits_wellness": {
                "ready": bool(traits_validation.get("valid")),
                "requires": ["curated traits manifest", "exact variant matches", "build validation", "source/citation metadata"],
                "validation": traits_validation,
            },
        },
        "non_diagnostic": True,
    }


@router.get("/interpretation/resources/clinvar/validate")
def interpretation_clinvar_validate(path: str | None = None):
    return validate_clinvar_tsv(path)


@router.post("/interpretation/resources/clinvar/build-tsv")
def interpretation_clinvar_build_tsv(
    vcf_path: str | None = None,
    output_path: str | None = None,
    max_rows: int = 0,
):
    """Convert ClinVar VCF to exact-match TSV for monogenic matching."""
    return build_clinvar_tsv_from_vcf(vcf_path, output_path, max_rows=max_rows)


@router.get("/interpretation/resources/pgs-manifest/validate")
def interpretation_pgs_manifest_validate(path: str | None = None):
    return validate_curated_pgs_manifest(path)


@router.get("/interpretation/resources/traits-manifest/validate")
def interpretation_traits_manifest_validate(path: str | None = None):
    return validate_traits_manifest(path)


@router.get("/interpretation/resources/pgx-rules/validate")
def interpretation_pgx_rules_validate(path: str | None = None):
    return validate_pgx_rules_manifest(path)


@router.get("/interpretation/resources/{resource_id}")
def interpretation_resource_detail(resource_id: str):
    for resource in interpretation_resource_registry():
        if resource.id == resource_id:
            return resource.model_dump()
    raise HTTPException(status_code=404, detail="interpretation_resource_not_found")


@router.get("/samples/{sample_id}/interpretation/foundation")
def interpretation_foundation(sample_id: str):
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)
    sample_variants = _variants_for_sample(sample)
    ref = _reference_for_sample(sample)
    build = validate_build(ref, sample_variants)
    tools = interpretation_tool_status()
    return {
        "sample_id": sample.sample_id,
        "run_id": run.id if run else None,
        "reference_id": sample.reference_id,
        "build_validation": build.model_dump(),
        "variant_count": len(sample_variants),
        "resources": tools,
        "ready_for_interpretation": build.ready_for_interpretation,
        "provenance_required": True,
        "non_diagnostic": True,
    }


@router.get("/samples/{sample_id}/interpretation/annotation")
def interpretation_annotation(sample_id: str):
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)
    ref = _reference_for_sample(sample)
    sample_variants = _variants_for_sample(sample)
    build = validate_build(ref, sample_variants)
    if not build.ready_for_interpretation:
        return {
            "sample_id": sample.sample_id,
            "status": build.status,
            "items": [],
            "count": 0,
            "build_validation": build.model_dump(),
            "non_diagnostic": True,
        }
    return {
        "sample_id": sample.sample_id,
        "build_validation": build.model_dump(),
        **annotation_summary(
            sample_variants,
            sample_id=sample.sample_id,
            run_id=run.id if run else None,
            genome_build=build.expected_build,
        ),
    }


@router.get("/samples/{sample_id}/interpretation/monogenic")
def interpretation_monogenic(sample_id: str, include_vus: bool = True, min_review_rank: int = 1):
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)
    ref = _reference_for_sample(sample)
    build = validate_build(ref, _variants_for_sample(sample))
    if not build.ready_for_interpretation:
        return {
            "sample_id": sample.sample_id,
            "status": build.status,
            "items": [],
            "count": 0,
            "build_validation": build.model_dump(),
            "non_diagnostic": True,
        }
    return {
        "sample_id": sample.sample_id,
        "build_validation": build.model_dump(),
        **classify_monogenic_variants(
            variants=_variants_for_sample(sample),
            sample_id=sample.sample_id,
            run_id=run.id if run else None,
            genome_build=build.expected_build,
            include_vus=include_vus,
            min_review_rank=min_review_rank,
        ),
    }


@router.get("/samples/{sample_id}/interpretation/acmg-secondary-findings")
def interpretation_acmg_secondary_findings(sample_id: str, enabled: bool = False):
    sample = _resolve_sample_or_404(sample_id)
    if not enabled:
        return {
            "sample_id": sample.sample_id,
            "status": "opt_in_required",
            "version": ACMG_SF_VERSION,
            "gene_count": len(ACMG_SF_GENES),
            "items": [],
            "count": 0,
            "message": "ACMG secondary findings are opt-in. Re-run with enabled=true after explicit consent.",
            "non_diagnostic": True,
        }
    run = _latest_run_for_sample(sample)
    ref = _reference_for_sample(sample)
    build = validate_build(ref, _variants_for_sample(sample))
    if not build.ready_for_interpretation:
        return {"sample_id": sample.sample_id, "status": build.status, "items": [], "count": 0, "build_validation": build.model_dump(), "non_diagnostic": True}
    return {
        "sample_id": sample.sample_id,
        "version": ACMG_SF_VERSION,
        "build_validation": build.model_dump(),
        **classify_monogenic_variants(
            variants=_variants_for_sample(sample),
            sample_id=sample.sample_id,
            run_id=run.id if run else None,
            genome_build=build.expected_build,
            include_vus=False,
            min_review_rank=1,
            acmg_only=True,
        ),
    }


@router.get("/samples/{sample_id}/interpretation/traits")
def interpretation_traits(sample_id: str):
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)
    ref = _reference_for_sample(sample)
    sample_variants = _variants_for_sample(sample)
    build = validate_build(ref, sample_variants)
    if not build.ready_for_interpretation:
        return {"sample_id": sample.sample_id, "status": build.status, "items": [], "count": 0, "build_validation": build.model_dump(), "non_diagnostic": True}
    return {
        "sample_id": sample.sample_id,
        "build_validation": build.model_dump(),
        **evaluate_traits(sample_variants, sample_id=sample.sample_id, run_id=run.id if run else None, genome_build=build.expected_build),
    }


@router.get("/samples/{sample_id}/interpretation/pgx/readiness")
def interpretation_pgx_readiness(sample_id: str):
    sample = _resolve_sample_or_404(sample_id)
    tools = interpretation_tool_status()
    rule_validation = validate_pgx_rules_manifest()
    if tools.get("pharmcat"):
        status = "ready"
    elif rule_validation.get("valid"):
        status = "curated_rules_ready"
    else:
        status = "not_configured"
    return {
        "sample_id": sample.sample_id,
        "pharmcat_ready": bool(tools.get("pharmcat")),
        "rule_manifest_ready": bool(rule_validation.get("valid")),
        "rule_manifest": rule_validation,
        "cyp2d6_specialized_ready": bool(tools.get("cyrius") or tools.get("stellarpgx")),
        "tools": {"pharmcat": tools.get("pharmcat"), "cyrius": tools.get("cyrius"), "stellarpgx": tools.get("stellarpgx")},
        "status": status,
        "next": "Install/wire PharmCAT JSON output; use curated CPIC/PharmGKB rules only as an auditable exact-match layer; use Cyrius/StellarPGx for CYP2D6 instead of naive VCF-only calls.",
        "non_diagnostic": True,
    }


@router.get("/samples/{sample_id}/interpretation/pgx/rules")
def interpretation_pgx_rules(sample_id: str):
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)
    ref = _reference_for_sample(sample)
    sample_variants = _variants_for_sample(sample)
    build = validate_build(ref, sample_variants)
    if not build.ready_for_interpretation:
        return {
            "sample_id": sample.sample_id,
            "status": build.status,
            "items": [],
            "count": 0,
            "build_validation": build.model_dump(),
            "non_diagnostic": True,
        }
    return {
        "sample_id": sample.sample_id,
        "build_validation": build.model_dump(),
        **evaluate_pgx_rules(
            sample_variants,
            sample_id=sample.sample_id,
            run_id=run.id if run else None,
            genome_build=build.expected_build,
        ),
    }


@router.get("/samples/{sample_id}/interpretation/haplogroups/readiness")
def interpretation_haplogroup_readiness(sample_id: str):
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)
    tools = interpretation_tool_status()
    mt = [m for m in mtdna_results if m.sample_id == sample.sample_id]
    mtdna_vcf, mtdna_vcf_source = _latest_mtdna_vcf_for_run(run)
    haplogrep_ready = bool(tools.get("haplogrep"))
    return {
        "sample_id": sample.sample_id,
        "run_id": run.id if run else None,
        "haplogrep_ready": haplogrep_ready,
        "mtdna_results": len(mt),
        "mtdna_vcf_path": str(mtdna_vcf) if mtdna_vcf else None,
        "mtdna_vcf_source": mtdna_vcf_source,
        "status": (
            "ready"
            if haplogrep_ready and mtdna_vcf
            else "not_configured"
            if not haplogrep_ready
            else "mtdna_variants_missing"
        ),
        "y_haplogroup_status": "planned_requires_y_coverage_and_karyotype_context",
        "non_diagnostic": True,
    }


@router.post("/interpretation/resources/pharmcat/install")
def interpretation_pharmcat_install(force: bool = False):
    """Install PharmCAT JAR from GitHub releases."""
    return install_pharmcat(force=force)


@router.get("/samples/{sample_id}/interpretation/pgx")
def interpretation_pgx(sample_id: str):
    """Run PharmCAT on sample VCF for pharmacogenomics interpretation."""
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)

    # Find the sample's VCF from the latest run
    output_dir = Path("/data/results") / (run.id if run else "unknown")
    vcf_candidates = list(output_dir.glob("*.vcf")) if output_dir.exists() else []
    vcf_candidates.extend(list(output_dir.glob("*.vcf.gz")))

    if not vcf_candidates:
        return {
            "sample_id": sample.sample_id,
            "status": "vcf_not_found",
            "message": "No VCF file found for this sample. Run variant calling first.",
            "non_diagnostic": True,
            "warning": "PGx results are research-only; not diagnostic.",
        }

    vcf_path = vcf_candidates[0]
    pgx_output = output_dir / "pharmcat"

    return {
        "sample_id": sample.sample_id,
        "run_id": run.id if run else None,
        **run_pharmcat(vcf_path, pgx_output),
    }


def _interpretation_result_from_payload(
    *,
    sample: Sample,
    run: Run | None,
    module: str,
    payload: dict,
) -> InterpretationResult:
    status = payload.get("status")
    if not status:
        status = "ready" if payload.get("ready_for_interpretation") else "unknown"
    count = payload.get("count")
    if count is None:
        count = payload.get("variant_count", 0)
    provenance = payload.get("provenance") or {
        "source_database": "wgs-cockpit interpretation runtime",
        "sample_id": sample.sample_id,
        "last_run_id": run.id if run else payload.get("run_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return InterpretationResult(
        id=f"interp_{uuid4().hex[:10]}",
        sample_id=sample.sample_id,
        run_id=run.id if run else payload.get("run_id"),
        module=module,
        status=str(status),
        count=int(count or 0),
        summary=payload,
        provenance=provenance,
        non_diagnostic=True,
    )


@router.post("/samples/{sample_id}/interpretation/materialize")
def materialize_interpretation_results(sample_id: str, replace_existing_for_run: bool = True):
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)
    if replace_existing_for_run and run:
        delete_interpretation_results_by_run(run.id)

    payloads = {
        "foundation": interpretation_foundation(sample.sample_id),
        "annotation": interpretation_annotation(sample.sample_id),
        "monogenic": interpretation_monogenic(sample.sample_id),
        "acmg_secondary_findings": interpretation_acmg_secondary_findings(sample.sample_id),
        "traits_wellness": interpretation_traits(sample.sample_id),
        "pharmacogenomics_rules": interpretation_pgx_rules(sample.sample_id),
        "pharmacogenomics_readiness": interpretation_pgx_readiness(sample.sample_id),
        "haplogroups_readiness": interpretation_haplogroup_readiness(sample.sample_id),
    }
    created = [
        _interpretation_result_from_payload(sample=sample, run=run, module=module, payload=payload)
        for module, payload in payloads.items()
    ]
    add_interpretation_results(created)
    if run:
        add_run_event(
            RunEvent(
                id=f"ev_{uuid4().hex[:10]}",
                run_id=run.id,
                event_type="interpretation.results_materialized",
                payload={"count": len(created), "modules": [item.module for item in created]},
            )
        )
        add_run_log_line(
            RunLogLine(
                run_id=run.id,
                line_no=len(run_logs) + 1,
                message=f"Interpretation results materialized count={len(created)}",
            )
        )
    return {
        "sample_id": sample.sample_id,
        "run_id": run.id if run else None,
        "count": len(created),
        "replace_existing_for_run": replace_existing_for_run,
        "items": created,
        "non_diagnostic": True,
    }


@router.get("/samples/{sample_id}/interpretation/results")
def get_interpretation_results_for_sample(sample_id: str, run_id: str | None = None, module: str | None = None):
    skey = _resolve_sample_key(sample_id)
    items = [
        item for item in interpretation_results
        if item.sample_id == skey
        and (run_id is None or item.run_id == run_id)
        and (module is None or item.module == module)
    ]
    items = sorted(items, key=lambda item: item.created_at, reverse=True)
    return {
        "sample_id": sample_id,
        "run_id": run_id,
        "module": module,
        "count": len(items),
        "items": items,
        "non_diagnostic": True,
    }


@router.post("/interpretation/resources/haplogrep/install")
def interpretation_haplogrep_install(force: bool = False):
    """Install HaploGrep3 JAR from GitHub releases."""
    return install_haplogrep(force=force)


@router.get("/samples/{sample_id}/interpretation/haplogroups")
def interpretation_haplogroups(sample_id: str):
    """Run HaploGrep on sample VCF for mtDNA haplogroup classification."""
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)

    output_dir = Path("/data/results") / (run.id if run else "unknown")
    vcf_path, vcf_source = _latest_mtdna_vcf_for_run(run)
    if not vcf_path:
        return {
            "sample_id": sample.sample_id,
            "run_id": run.id if run else None,
            "status": "mtdna_vcf_not_found",
            "message": "No mtDNA VCF file found for this sample. Run/import the mtDNA stage first.",
            "non_diagnostic": True,
        }

    haplogrep_output = output_dir / "haplogrep"

    return {
        "sample_id": sample.sample_id,
        "run_id": run.id if run else None,
        "input_vcf_path": str(vcf_path),
        "input_vcf_source": vcf_source,
        **run_haplogrep(vcf_path, haplogrep_output),
    }


@router.post("/interpretation/resources/clinvar/install")
def interpretation_clinvar_install(force: bool = False):
    """Download ClinVar VCF from NCBI FTP."""
    return install_clinvar_vcf(force=force)


@router.post("/samples/{sample_id}/interpretation/normalize")
def interpretation_normalize(sample_id: str):
    """Run VCF normalization on sample's raw variants using bcftools norm."""
    sample = _resolve_sample_or_404(sample_id)
    run = _latest_run_for_sample(sample)
    ref = _reference_for_sample(sample)

    bcftools_ok = bool(shutil.which("bcftools"))
    if not bcftools_ok:
        return {
            "sample_id": sample.sample_id,
            "status": "tool_missing",
            "message": "bcftools not installed; cannot normalize VCF.",
            "non_diagnostic": True,
        }

    output_dir = Path("/data/results") / (run.id if run else "unknown")
    vcf_candidates = list(output_dir.glob("*.vcf")) if output_dir.exists() else []
    vcf_candidates.extend(list(output_dir.glob("*.vcf.gz")))

    if not vcf_candidates:
        return {
            "sample_id": sample.sample_id,
            "status": "vcf_not_found",
            "message": "No VCF file found for this sample. Run variant calling first.",
            "non_diagnostic": True,
        }

    vcf_path = vcf_candidates[0]
    ref_fasta = _resolve_reference_fasta(sample.reference_id)

    from app.core.interpretation import InterpretationProvenance
    provenance = InterpretationProvenance(
        source_database="bcftools norm",
        source_version="bcftools",
        genome_build=ref.version if ref else None,
        rule_id="vcf_normalization_bcftools_norm",
        sample_id=sample.sample_id,
        last_run_id=run.id if run else None,
    )

    norm_vcf = output_dir / f"{sample.sample_id}.normalized.vcf"
    try:
        cmd = ["bcftools", "norm", "-m", "-any", "--threads", "4"]
        if ref_fasta and ref_fasta.exists():
            cmd.extend(["-f", str(ref_fasta)])
        cmd.extend([str(vcf_path), "-Ov", "-o", str(norm_vcf)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        provenance.warnings.extend([
            line for line in (result.stderr or "").splitlines() if line.strip()
        ][:10])

        return {
            "sample_id": sample.sample_id,
            "run_id": run.id if run else None,
            "status": "completed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "normalized_vcf": str(norm_vcf),
            "reference_used": str(ref_fasta) if ref_fasta else None,
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }
    except subprocess.TimeoutExpired:
        provenance.warnings.append("bcftools norm timed out (300s).")
        return {
            "sample_id": sample.sample_id,
            "status": "timeout",
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }
    except Exception as exc:
        provenance.warnings.append(str(exc))
        return {
            "sample_id": sample.sample_id,
            "status": "error",
            "error": str(exc),
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }


@router.get("/samples/{sample_id}/caller-agreement")
def get_caller_agreement(sample_id: str):
    sample = next((s for s in samples if s.sample_id == sample_id or s.id == sample_id), None)
    key = sample.sample_id if sample else sample_id
    items = [v for v in variants if v.sample_id == key]
    grouped = {
        "consensus": [v for v in items if _agreement_bucket(v) == "consensus"],
        "mixed": [v for v in items if _agreement_bucket(v) == "mixed"],
        "disagreement": [v for v in items if _agreement_bucket(v) == "disagreement"],
    }
    return {
        "sample_id": sample_id,
        "summary": {k: len(v) for k, v in grouped.items()},
        "items": [
            {
                "variant_id": v.id,
                "chrom": v.chrom,
                "pos": v.pos,
                "callers": v.caller_list,
                "caller_agreement_score": v.caller_agreement_score,
                "bucket": _agreement_bucket(v),
                "trust_score": v.trust_score,
            }
            for v in items
        ],
    }


@router.get("/samples/{sample_id}/caller-disagreement")
def get_caller_disagreement(sample_id: str, run_id: str | None = None):
    skey = _resolve_sample_key(sample_id)
    items = [v for v in variants if v.sample_id == skey and _agreement_bucket(v) == "disagreement"]
    if run_id:
        items = [v for v in items if v.run_id == run_id]
    return {
        "sample_id": skey,
        "count": len(items),
        "items": [
            {
                "variant_id": v.id,
                "chrom": v.chrom,
                "pos": v.pos,
                "caller_agreement_score": v.caller_agreement_score,
                "callers": v.caller_list,
                "trust_score": v.trust_score,
                "trust_label": v.trust_label,
            }
            for v in items
        ],
        "non_diagnostic": True,
    }


@router.get("/variants/{variant_id}")
def get_variant(variant_id: str):
    item = next((v for v in variants if v.id == variant_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="variant_not_found")
    return item


@router.get("/samples/{sample_id}/trust-map")
def get_sample_trust_map(sample_id: str):
    skey = _resolve_sample_key(sample_id)
    items = [v for v in variants if v.sample_id == skey]
    disagreements = [v for v in items if _agreement_bucket(v) == "disagreement"]
    return {
        "sample_id": skey,
        "score_range": [0, 100],
        "labels": ["high", "medium", "low", "unknown"],
        "non_diagnostic": True,
        "caller_disagreement_count": len(disagreements),
        "layers": [
            "giab_confidence_overlay",
            "difficult_regions",
            "false_positive_hotspots",
            "false_negative_risk_zones",
            "caller_disagreement_map",
        ],
        "variant_points": [
            {
                "variant_id": v.id,
                "chrom": v.chrom,
                "pos": v.pos,
                "trust_score": v.trust_score,
                "trust_label": v.trust_label,
                "explainability": v.explainability,
            }
            for v in items
        ],
    }


@router.get("/samples/{sample_id}/caller-disagreement-overlay")
def get_caller_disagreement_overlay(sample_id: str, level: str = "1mb", run_id: str | None = None):
    level_key = level.strip().lower()
    bin_size = {"5mb": 5_000_000, "1mb": 1_000_000, "500kb": 500_000}.get(level_key, 1_000_000)
    skey = _resolve_sample_key(sample_id)

    items = [v for v in variants if v.sample_id == skey and _agreement_bucket(v) == "disagreement"]
    if run_id:
        items = [v for v in items if v.run_id == run_id]
    if not items:
        return {
            "sample_id": skey,
            "level": level,
            "status": "empty",
            "hotspots": [],
            "count": 0,
            "note": "No caller-disagreement variants for this sample.",
        }

    buckets: dict[tuple[str, int], list[VariantCall]] = {}
    for v in items:
        idx = max(0, (v.pos - 1) // bin_size)
        key = (v.chrom, idx)
        buckets.setdefault(key, []).append(v)

    hotspots = []
    for (chrom, idx), vars_in_bin in sorted(buckets.items(), key=lambda x: (x[0][0], x[0][1])):
        avg_trust = sum(v.trust_score for v in vars_in_bin) / len(vars_in_bin)
        avg_agreement = sum(v.caller_agreement_score for v in vars_in_bin) / len(vars_in_bin)
        hotspots.append(
            {
                "hotspot_id": f"{skey}:{level_key}:{chrom}:{idx}",
                "chrom": chrom,
                "start": idx * bin_size + 1,
                "end": (idx + 1) * bin_size,
                "variant_count": len(vars_in_bin),
                "avg_trust_score": round(avg_trust, 2),
                "avg_caller_agreement_score": round(avg_agreement, 3),
                "variant_ids": [v.id for v in vars_in_bin],
            }
        )

    hotspots_sorted = sorted(hotspots, key=lambda h: (-h["variant_count"], h["avg_caller_agreement_score"]))

    return {
        "sample_id": skey,
        "level": level,
        "status": "imported",
        "count": len(hotspots_sorted),
        "hotspots": hotspots_sorted,
        "note": "Disagreement hotspots aggregated by genomic bins.",
    }


@router.get("/samples/{sample_id}/sv")
def get_structural_variants(sample_id: str, run_id: str | None = None):
    skey = _resolve_sample_key(sample_id)
    items = [sv for sv in structural_variants if sv.sample_id == skey]
    if run_id:
        items = [sv for sv in items if sv.run_id == run_id]
    return {
        "sample_id": skey,
        "count": len(items),
        "items": items,
        "note": "Short-read SV findings are technical candidates and may be uncertain.",
        "non_diagnostic": True,
    }


@router.get("/samples/{sample_id}/cnv")
def get_cnv_segments(sample_id: str, run_id: str | None = None):
    skey = _resolve_sample_key(sample_id)
    items = [cnv for cnv in cnv_segments if cnv.sample_id == skey]
    if run_id:
        items = [cnv for cnv in items if cnv.run_id == run_id]
    return {
        "sample_id": sample_id,
        "count": len(items),
        "items": items,
        "note": "CNV calls are technical signals and require validation.",
        "non_diagnostic": True,
    }


@router.get("/samples/{sample_id}/mtdna")
def get_mtdna(sample_id: str):
    skey = _resolve_sample_key(sample_id)
    items = [m for m in mtdna_results if m.sample_id == skey]
    if not items:
        return {
            "sample_id": sample_id,
            "count": 0,
            "items": [],
            "note": "mtDNA module scaffold. No results imported yet.",
            "non_diagnostic": True,
        }
    warning_items = [
        {"id": item.id, "run_id": item.run_id, "reasons": _mtdna_warning_reasons(item)}
        for item in items
        if _mtdna_warning_reasons(item)
    ]
    return {
        "sample_id": sample_id,
        "count": len(items),
        "items": items,
        "numts_warning_count": len([m for m in items if m.numts_warning]),
        "warnings": warning_items,
        "note": "mtDNA results are technical/research outputs.",
        "non_diagnostic": True,
    }


@router.get("/samples/{sample_id}/prs")
def get_prs(sample_id: str, run_id: str | None = None):
    skey = _resolve_sample_key(sample_id)
    items = [p for p in prs_results if p.sample_id == skey]
    if run_id:
        items = [p for p in items if p.run_id == run_id]
    if not items:
        return {
            "sample_id": sample_id,
            "count": 0,
            "items": [],
            "note": "PRS module scaffold. No score files imported yet.",
            "non_diagnostic": True,
        }
    return {
        "sample_id": sample_id,
        "count": len(items),
        "items": items,
        "note": "PRS has research/informational character and is not a diagnosis.",
        "non_diagnostic": True,
    }


@router.get("/prs/catalog/manifest")
def prs_catalog_manifest():
    return {"source": "operator_curated_manifest", **curated_manifest_status(), "non_diagnostic": True}


@router.get("/prs/catalog/manifest/validate")
def prs_catalog_manifest_validate(path: str | None = None):
    return validate_curated_pgs_manifest(path)


@router.get("/prs/catalog/storage-estimate")
def prs_catalog_storage_estimate():
    return pgs_storage_estimate()


@router.get("/prs/catalog/recommended")
def prs_catalog_recommended(per_category: int = 25, max_total: int = 300):
    return recommended_pgs_from_downloaded(per_category=max(1, min(per_category, 100)), max_total=max(1, min(max_total, 1000)))


@router.get("/prs/catalog/draft-manifest")
def prs_catalog_draft_manifest(limit: int = 500):
    return draft_manifest_from_downloaded_scores(limit=limit)


@router.get("/prs/catalog/draft-manifest.tsv")
def prs_catalog_draft_manifest_tsv(limit: int = 500):
    draft = draft_manifest_from_downloaded_scores(limit=limit)
    return PlainTextResponse(draft_manifest_tsv(draft.get("items", [])), media_type="text/tab-separated-values")


@router.get("/prs/catalog/search")
def search_prs_catalog(q: str = "", trait: str = "", limit: int = 20, offset: int = 0, source: str = "curated"):
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    if source == "remote":
        try:
            remote_items = _search_pgs_remote(q=q, trait=trait, limit=safe_limit, offset=safe_offset)
            return {"items": remote_items, "count": len(remote_items), "source": "pgscatalog.org", "categories": {}}
        except Exception:
            pass

    items, count = search_curated_pgs(q=q, trait=trait, limit=safe_limit, offset=safe_offset)
    compact = [
        {
            "pgs_id": x.get("pgs_id"),
            "name": x.get("name"),
            "trait": x.get("trait_reported"),
            "variants_count": x.get("variants_number"),
            "publication": x.get("publication"),
            "ftp_url": x.get("ftp_url"),
            "trait_category": x.get("trait_category"),
        }
        for x in items
    ]
    return {
        "items": compact,
        "count": count,
        "source": "curated",
        "categories": pgs_category_counts(),
    }


def _search_pgs_remote(q: str = "", trait: str = "", limit: int = 20, offset: int = 0) -> list[dict]:
    """Search PGS Catalog EBI REST API."""
    import json as _json
    params = f"limit={limit}&offset={offset}"
    if q:
        params += f"&search_params={q}"
    if trait:
        params += f"&trait_category={trait}"
    url = f"https://www.pgscatalog.org/rest/score/search?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "wgs-cockpit/0.6"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = _json.loads(resp.read())
    results = []
    for item in data.get("results", []):
        pub = item.get("publication", {})
        results.append({
            "pgs_id": item.get("id"),
            "name": item.get("name", ""),
            "trait": item.get("trait_reported", ""),
            "variants_count": item.get("variants_number"),
            "publication": pub.get("firstauthor", "") if isinstance(pub, dict) else "",
            "ftp_url": item.get("ftp_scoring_file", ""),
            "trait_category": item.get("trait_category", ""),
        })
    return results


PGS_DOWNLOAD_JOBS: dict[str, dict] = {}


def _discover_all_pgs_ids(limit: int = 0) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    page_size = 200
    offset = 0
    while True:
        url = f"https://www.pgscatalog.org/rest/score/all?limit={page_size}&offset={offset}"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "wgs-cockpit/0.6"})
        last_exc = None
        for attempt in range(1, 6):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                break
            except Exception as exc:
                last_exc = exc
                time.sleep(min(20, attempt * 3))
        else:
            raise last_exc
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            pgs_id = str(item.get("id") or "").upper()
            if pgs_id.startswith("PGS") and pgs_id not in seen:
                seen.add(pgs_id)
                ids.append(pgs_id)
                if limit and len(ids) >= limit:
                    return ids
        if len(results) < page_size:
            break
        offset += page_size
    return ids


def _run_pgs_download_job(job_id: str, *, limit: int, retry_count: int, force: bool):
    job = PGS_DOWNLOAD_JOBS[job_id]
    try:
        job.update({"status": "discovering", "message": "Discovering PGS Catalog score IDs", "started_at": datetime.now(timezone.utc).isoformat()})
        pgs_ids = _discover_all_pgs_ids(limit=limit)
        downloaded_meta = {m.get("pgs_id"): m for m in list_downloaded_scores()}
        if not force:
            pgs_ids = [pid for pid in pgs_ids if pid not in downloaded_meta]
        job.update({"status": "running", "total": len(pgs_ids), "completed": 0, "failed": 0, "skipped_existing": len(downloaded_meta) if not force else 0, "ids_preview": pgs_ids[:20]})
        errors: list[dict] = []
        for idx, pgs_id in enumerate(pgs_ids, start=1):
            job.update({"current": pgs_id, "completed": idx - 1, "progress_pct": round(((idx - 1) / max(1, len(pgs_ids))) * 100, 2)})
            ok = False
            last_error = None
            for attempt in range(1, max(1, retry_count) + 1):
                try:
                    download_pgs_score(pgs_id)
                    ok = True
                    break
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(min(10, attempt * 2))
            if not ok:
                errors.append({"pgs_id": pgs_id, "error": last_error})
                job["failed"] = int(job.get("failed", 0)) + 1
            job["completed"] = idx
            job["progress_pct"] = round((idx / max(1, len(pgs_ids))) * 100, 2)
        job.update({
            "status": "completed" if not errors else "completed_with_errors",
            "current": None,
            "errors": errors[-100:],
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "message": f"Downloaded {max(0, len(pgs_ids) - len(errors))}/{len(pgs_ids)} PGS score files",
        })
    except Exception as exc:
        job.update({"status": "failed", "error": str(exc), "finished_at": datetime.now(timezone.utc).isoformat()})


@router.post("/prs/catalog/download")
def prs_catalog_download(req: PRSCatalogDownloadRequest):
    try:
        return download_pgs_score(req.pgs_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"pgs_download_failed: {exc}") from exc


@router.post("/prs/catalog/download-all")
def prs_catalog_download_all(req: PRSCatalogDownloadAllRequest):
    active = next((j for j in PGS_DOWNLOAD_JOBS.values() if j.get("status") in {"discovering", "running"}), None)
    if active:
        return active
    job_id = f"pgsdl_{uuid4().hex[:10]}"
    safe_limit = 0 if req.limit == 0 else max(1, min(req.limit, 500))
    PGS_DOWNLOAD_JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "total": 0,
        "completed": 0,
        "failed": 0,
        "progress_pct": 0.0,
        "retry_count": req.retry_count,
        "force": req.force,
        "limit": safe_limit,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "storage_path": "/data/references/pgs",
    }
    t = threading.Thread(target=_run_pgs_download_job, args=(job_id,), kwargs={"limit": safe_limit, "retry_count": req.retry_count, "force": req.force}, daemon=True)
    t.start()
    return PGS_DOWNLOAD_JOBS[job_id]


@router.get("/prs/catalog/download-jobs")
def prs_catalog_download_jobs():
    return {"items": sorted(PGS_DOWNLOAD_JOBS.values(), key=lambda x: x.get("created_at", ""), reverse=True)}


@router.get("/prs/catalog/download-jobs/{job_id}")
def prs_catalog_download_job(job_id: str):
    job = PGS_DOWNLOAD_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="pgs_download_job_not_found")
    return job


@router.get("/prs/scores")
def prs_scores():
    items = list_downloaded_scores()
    return {
        "items": [
            {
                "pgs_id": x.get("pgs_id"),
                "name": x.get("pgs_name") or x.get("name"),
                "trait": x.get("trait_reported"),
                "variants_count": x.get("variants_number"),
                "downloaded_at": x.get("downloaded_at"),
                "local_path": x.get("local_path"),
            }
            for x in items
        ]
    }


def _prs_readiness(sample: Sample, min_mean_coverage: float = 20.0, min_callable_fraction: float = 0.8, run_id: str | None = None) -> dict:
    """Determine if PRS interpretation is allowed. Calculation without interpretation is OK."""
    sample_runs = [r for r in runs if r.sample_id == sample.id]
    run_ids = {r.id for r in sample_runs}
    if run_id:
        run_ids = {run_id} if run_id in run_ids else set()
    latest_cov = next((c for c in reversed(coverage_metrics) if c.run_id in run_ids), None)
    sample_variants = _sample_variant_dicts(sample, run_id=run_id)
    reasons: list[str] = []

    if not sample_variants:
        reasons.append("no imported variants; run/import the variants stage first")

    if sample.reference_id.lower().endswith("chr20") or "chr20" in sample.reference_id.lower():
        reasons.append("test chromosome reference, not whole genome")

    if not latest_cov:
        reasons.append("no coverage metrics imported")
    else:
        if latest_cov.mean_coverage is None or latest_cov.mean_coverage < min_mean_coverage:
            reasons.append(f"mean coverage below {min_mean_coverage}x")
        if latest_cov.callable_fraction is None:
            reasons.append("callable fraction missing")
        elif latest_cov.callable_fraction < min_callable_fraction:
            reasons.append(f"callable fraction below {min_callable_fraction:.0%}")

    return {
        "ready": len(reasons) == 0,
        "reasons": reasons,
        "requirements": {
            "whole_genome_reference": True,
            "imported_variants": True,
            "min_mean_coverage": min_mean_coverage,
            "min_callable_fraction": min_callable_fraction,
        },
        "variant_count": len(sample_variants),
        "coverage": {
            "mean_coverage": latest_cov.mean_coverage if latest_cov else None,
            "callable_fraction": latest_cov.callable_fraction if latest_cov else None,
        },
    }


def _sample_variant_dicts(sample: Sample, run_id: str | None = None) -> list[dict]:
    sample_key = sample.sample_id
    return [
        {
            "chrom": v.chrom,
            "pos": v.pos,
            "ref": v.ref,
            "alt": v.alt,
            "rsid": None,
            "genotype": v.genotype,
            "zygosity": v.zygosity,
        }
        for v in variants
        if v.sample_id == sample_key and (not run_id or v.run_id == run_id)
    ]


def _risk_band_from_percentile(percentile: float | None, interpretable: bool) -> str:
    if not interpretable or percentile is None:
        return "Not interpretable"
    if percentile >= 97:
        return "Very High"
    if percentile >= 85:
        return "High"
    if percentile >= 60:
        return "Moderate"
    return "Lower relative score"


def _prs_panel_caveats(calc: dict, meta: dict, readiness: dict) -> list[str]:
    caveats = ["Research-only PRS; not diagnostic and not a low-risk clearance."]
    match_rate = float(calc.get("match_rate") or 0.0)
    if match_rate < 0.5:
        caveats.append("Variant overlap is low; do not interpret this score as meaningful.")
    elif match_rate < 0.8:
        caveats.append("Variant overlap is moderate; confidence is limited by missing score variants.")

    if not readiness.get("ready"):
        reasons = "; ".join(readiness.get("reasons") or [])
        caveats.append(f"Coverage/readiness gate is not satisfied{': ' + reasons if reasons else ''}.")

    genome_build = calc.get("genome_build") or meta.get("genome_build")
    if not genome_build or str(genome_build).upper() in {"NR", "NA", "UNKNOWN"}:
        caveats.append("Genome build is missing or not reported by the score file.")

    ancestry = meta.get("ancestry") or meta.get("development_ancestry") or meta.get("evaluation_ancestry")
    if ancestry:
        caveats.append(f"Development/evaluation ancestry: {ancestry}; portability may differ.")
    else:
        caveats.append("Development/evaluation ancestry is unavailable; population portability is unknown.")
    return caveats


@router.get("/samples/{sample_id}/prs/readiness")
def prs_readiness(sample_id: str, run_id: str | None = None):
    sample = next((s for s in samples if s.sample_id == sample_id or s.id == sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")
    return {"sample_id": sample.sample_id, **_prs_readiness(sample, run_id=run_id)}


@router.post("/prs/calculate")
def prs_calculate(req: PRSCalculateRequest):
    sample = next((s for s in samples if s.sample_id == req.sample_id or s.id == req.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    sample_key = sample.sample_id
    sample_variants = _sample_variant_dicts(sample, run_id=req.run_id)

    if not sample_variants:
        raise HTTPException(status_code=400, detail="sample_variants_not_found")

    out: list[dict] = []
    run = next((r for r in runs if r.id == req.run_id), None) if req.run_id else None
    run_id = run.id if run else (next((r.id for r in runs if r.sample_id == sample.id), None) or f"run_{uuid4().hex[:10]}")

    downloaded_meta = {m.get("pgs_id"): m for m in list_downloaded_scores()}
    readiness = _prs_readiness(sample, run_id=req.run_id)

    for pgs_id in req.pgs_ids:
        score_file_path = Path(f"/data/references/pgs/{pgs_id.upper()}.txt.gz")
        if not score_file_path.exists():
            raise HTTPException(status_code=404, detail=f"pgs_score_not_downloaded:{pgs_id}")

        calc = calculate_prs(sample_variants, str(score_file_path))
        z = calc["score"]
        interpretable = readiness["ready"] and calc["match_rate"] >= 0.5
        percentile = max(0.0, min(100.0, 50.0 + (z * 10.0))) if interpretable else None
        quality_label = "high" if calc["match_rate"] >= 0.8 else "medium" if calc["match_rate"] >= 0.5 else "low"

        meta = downloaded_meta.get(pgs_id.upper(), {})
        trait = meta.get("trait_reported") or pgs_id.upper()

        result = PRSResult(
            id=f"prs_{uuid4().hex[:10]}",
            sample_id=sample_key,
            run_id=run_id,
            reference_id=sample.reference_id,
            trait=trait,
            score_value=calc["score"],
            overlap_pct=calc["match_rate"] * 100.0,
            variant_count_total=calc["variants_total"],
            variant_count_matched=calc["variants_matched"],
            quality_label=quality_label,
            warning="Research-use PRS. No diagnostic intent.",
            non_diagnostic=True,
        )
        add_prs_result(result)
        out.append(
            {
                "pgs_id": pgs_id.upper(),
                "trait": trait,
            "score": calc["score"],
            "percentile": percentile,
            "risk_band": _risk_band_from_percentile(percentile, interpretable),
            "interpretable": interpretable,
            "readiness": readiness,
            "variants_matched": calc["variants_matched"],
                "variants_total": calc["variants_total"],
                "match_rate": calc["match_rate"],
                "top_contributors": calc["top_contributors"],
                "quality_label": quality_label,
            }
        )

    return {
        "sample_id": sample_key,
        "run_id": run_id,
        "count": len(out),
        "readiness": readiness,
        "items": out,
    }


@router.post("/prs/panel/run")
def prs_panel_run(req: PRSPanelRunRequest):
    """Run an operator-approved PRS panel.

    Downloaded PGS Catalog files are raw resources. They must not silently
    become a patient/sample panel without a curated manifest and build gate.
    """
    sample = next((s for s in samples if s.sample_id == req.sample_id or s.id == req.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")
    sample_variants = _sample_variant_dicts(sample, run_id=req.run_id)
    if not sample_variants:
        raise HTTPException(status_code=400, detail="sample_variants_not_found")

    manifest_status = validate_curated_pgs_manifest()
    if not manifest_status.get("valid"):
        raise HTTPException(
            status_code=501,
            detail={
                "code": "prs_curated_manifest_missing",
                "message": "Curated PGS manifest is not configured. Downloaded PGS Catalog files remain draft resources and are not used for sample PRS reporting.",
                "expected_paths": manifest_status.get("expected_paths", []),
            },
        )
    limit = max(1, min(req.limit, 1000))
    selected = load_curated_pgs_manifest()[:limit]
    sample_build = "GRCh38" if "GRCH38" in sample.reference_id.upper() else "GRCh37" if "GRCH37" in sample.reference_id.upper() else sample.reference_id
    incompatible = [
        entry["pgs_id"]
        for entry in selected
        if entry.get("genome_build") and sample_build in {"GRCh37", "GRCh38"} and str(entry.get("genome_build")).upper() != sample_build.upper()
    ]
    if incompatible:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "prs_manifest_build_mismatch",
                "message": f"Curated PGS manifest is not compatible with sample reference {sample.reference_id}.",
                "sample_reference_id": sample.reference_id,
                "sample_build": sample_build,
                "incompatible_pgs_ids": incompatible[:25],
            },
        )

    downloaded_meta = {m.get("pgs_id"): m for m in list_downloaded_scores()}
    if not downloaded_meta:
        raise HTTPException(status_code=400, detail="pgs_scores_not_downloaded")
    panel_source = "operator_curated_manifest"
    readiness = _prs_readiness(sample, req.min_mean_coverage, req.min_callable_fraction, run_id=req.run_id)
    run = next((r for r in runs if r.id == req.run_id), None) if req.run_id else None
    run_id = run.id if run else (next((r.id for r in runs if r.sample_id == sample.id), None) or f"run_{uuid4().hex[:10]}")

    out: list[dict] = []
    errors: list[dict] = []
    for entry in selected:
        pgs_id = str(entry.get("pgs_id") or "").upper()
        meta = downloaded_meta.get(pgs_id, entry)
        score_file_path = Path(meta.get("local_path") or f"/data/references/pgs/{pgs_id}.txt.gz")
        if not pgs_id or not score_file_path.exists():
            errors.append({"pgs_id": pgs_id, "error": "score_file_missing"})
            continue
        try:
            calc = calculate_prs(sample_variants, str(score_file_path))
        except Exception as exc:
            errors.append({"pgs_id": pgs_id, "error": str(exc)})
            continue
        interpretable = calc["match_rate"] >= req.min_match_rate
        percentile = max(0.0, min(100.0, 50.0 + (calc["score"] * 10.0))) if interpretable else None
        trait = entry.get("trait_reported") or meta.get("trait_reported") or calc.get("trait") or pgs_id
        risk_band = _risk_band_from_percentile(percentile, interpretable)
        quality_label = "high" if interpretable and calc["match_rate"] >= 0.8 else "not_interpretable" if not interpretable else "medium"
        caveats = _prs_panel_caveats(calc, meta, readiness)
        rec = PRSResult(
            id=f"prs_{uuid4().hex[:10]}",
            sample_id=sample.sample_id,
            run_id=run_id,
            reference_id=sample.reference_id,
            trait=trait,
            score_value=calc["score"],
            overlap_pct=calc["match_rate"] * 100.0,
            variant_count_total=calc["variants_total"],
            variant_count_matched=calc["variants_matched"],
            quality_label=quality_label,
            warning=" ".join(caveats[:2]),
            non_diagnostic=True,
        )
        add_prs_result(rec)
        out.append({
            "pgs_id": pgs_id,
            "trait": trait,
            "score": calc["score"],
            "percentile": percentile,
            "risk_band": risk_band,
            "interpretable": interpretable,
            "readiness": readiness,
            "variants_matched": calc["variants_matched"],
            "variants_total": calc["variants_total"],
            "match_rate": calc["match_rate"],
            "top_contributors": calc["top_contributors"],
            "quality_label": quality_label,
            "genome_build": calc.get("genome_build") or meta.get("genome_build"),
            "ancestry": meta.get("ancestry") or meta.get("development_ancestry") or meta.get("evaluation_ancestry"),
            "caveats": caveats,
        })

    out.sort(key=lambda x: (-1 if x["percentile"] is None else -x["percentile"], -x["match_rate"]))
    return {"sample_id": sample.sample_id, "run_id": run_id, "readiness": readiness, "panel_source": panel_source, "count": len(out), "errors": errors[:100], "items": out, "development_mode": True, "non_diagnostic": True}


def _prs_panel_run_legacy_disabled(req: PRSPanelRunRequest):
    sample = next((s for s in samples if s.sample_id == req.sample_id or s.id == req.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")
    sample_variants = _sample_variant_dicts(sample, run_id=req.run_id)
    if not sample_variants:
        raise HTTPException(status_code=400, detail="sample_variants_not_found")

    limit = max(1, min(req.limit, 300))
    selected = load_curated_pgs_manifest()[:limit]
    if not selected:
        raise HTTPException(
            status_code=501,
            detail={
                "code": "prs_curated_manifest_missing",
                "message": "Curated PGS manifest is not configured. No PRS panel results are generated.",
                "expected_paths": curated_manifest_status()["expected_paths"],
            },
        )
    downloaded_meta = {m.get("pgs_id"): m for m in list_downloaded_scores()}
    download_errors: list[dict] = []

    for entry in selected:
        pgs_id = entry["pgs_id"].upper()
        if pgs_id in downloaded_meta and Path(f"/data/references/pgs/{pgs_id}.txt.gz").exists():
            continue
        try:
            meta = download_pgs_score(pgs_id)
            downloaded_meta[pgs_id] = meta
        except Exception as exc:
            download_errors.append({"pgs_id": pgs_id, "error": str(exc)})

    readiness = _prs_readiness(sample, req.min_mean_coverage, req.min_callable_fraction, run_id=req.run_id)
    run = next((r for r in runs if r.id == req.run_id), None) if req.run_id else None
    run_id = run.id if run else (next((r.id for r in runs if r.sample_id == sample.id), None) or f"run_{uuid4().hex[:10]}")

    out: list[dict] = []
    for entry in selected:
        pgs_id = entry["pgs_id"].upper()
        score_file_path = Path(f"/data/references/pgs/{pgs_id}.txt.gz")
        if not score_file_path.exists():
            continue
        calc = calculate_prs(sample_variants, str(score_file_path))
        interpretable = readiness["ready"] and calc["match_rate"] >= req.min_match_rate
        percentile = max(0.0, min(100.0, 50.0 + (calc["score"] * 10.0))) if interpretable else None
        trait = (downloaded_meta.get(pgs_id) or {}).get("trait_reported") or entry.get("trait_reported") or pgs_id
        risk_band = _risk_band_from_percentile(percentile, interpretable)
        warning = "Research-use PRS. No diagnostic intent."
        if not interpretable:
            warning = "Insufficient data for PRS interpretation; do not report as low risk."
        rec = PRSResult(
            id=f"prs_{uuid4().hex[:10]}",
            sample_id=sample.sample_id,
            run_id=run_id,
            reference_id=sample.reference_id,
            trait=trait,
            score_value=calc["score"],
            overlap_pct=calc["match_rate"] * 100.0,
            variant_count_total=calc["variants_total"],
            variant_count_matched=calc["variants_matched"],
            quality_label="high" if interpretable and calc["match_rate"] >= 0.8 else "not_interpretable" if not interpretable else "medium",
            warning=warning,
            non_diagnostic=True,
        )
        add_prs_result(rec)
        out.append({
            "pgs_id": pgs_id,
            "trait": trait,
            "score": calc["score"],
            "percentile": percentile,
            "risk_band": risk_band,
            "interpretable": interpretable,
            "variants_matched": calc["variants_matched"],
            "variants_total": calc["variants_total"],
            "match_rate": calc["match_rate"],
            "top_contributors": calc["top_contributors"],
            "warning": warning,
        })

    out.sort(key=lambda x: (-1 if x["percentile"] is None else -x["percentile"], -x["match_rate"]))
    return {
        "sample_id": sample.sample_id,
        "run_id": run_id,
        "readiness": readiness,
        "count": len(out),
        "download_errors": download_errors[:25],
        "items": out,
    }


TAXONOMY_PAGE_MAX_LIMIT = 1000
TAXONOMY_FILTERS = {"species", "genus", "lineage", "review", "bacteria", "viruses", "fungi", "unclassified", "all"}
TAXONOMY_CLADE_TAXIDS = {
    "bacteria": "2",
    "viruses": "10239",
    "fungi": "4751",
}


def _taxonomy_page_params(limit: int | None, offset: int, filter: str | None, search: str | None) -> tuple[int | None, int, str, str]:
    page_limit = None if limit is None else max(1, min(int(limit), TAXONOMY_PAGE_MAX_LIMIT))
    page_offset = max(0, int(offset or 0))
    row_filter = (filter or "all").strip().lower()
    if row_filter not in TAXONOMY_FILTERS:
        row_filter = "all"
    return page_limit, page_offset, row_filter, (search or "").strip()


def _taxonomy_hit_from_row(row) -> TaxonomyHit:
    data = {c.name: getattr(row, c.name) for c in sm.TaxonomyHit.__table__.columns}
    data["reference_id"] = data.get("reference_id") or "unknown"
    data["organism"] = data.get("organism") or "unknown"
    data["kingdom"] = data.get("kingdom") or "unknown"
    data["read_count"] = data.get("read_count") or 0
    data["confidence"] = data.get("confidence") or 0.0
    data["evidence_score"] = data.get("evidence_score") or 0.0
    data["lineage"] = data.get("lineage") or []
    data["tools"] = data.get("tools") or []
    return TaxonomyHit.model_validate(data)


def _taxonomy_apply_db_filter(query, row_filter: str, search: str):
    rank = func.lower(func.coalesce(sm.TaxonomyHit.rank, ""))
    organism = func.lower(func.coalesce(sm.TaxonomyHit.organism, ""))
    top_clade = func.lower(func.coalesce(sm.TaxonomyHit.top_clade, ""))
    lineage_text = func.lower(cast(sm.TaxonomyHit.lineage, SqlString))
    if row_filter == "species":
        query = query.filter(rank == "species")
    elif row_filter == "genus":
        query = query.filter(rank == "genus")
    elif row_filter == "lineage":
        query = query.filter(rank.notin_(("species", "genus", "unclassified")))
    elif row_filter == "review":
        query = query.filter(
            rank == "species",
            func.coalesce(sm.TaxonomyHit.read_count, 0) >= 100,
            sm.TaxonomyHit.likely_contaminant.is_(False),
            or_(
                func.coalesce(sm.TaxonomyHit.confidence, 0.0) >= 0.0001,
                func.coalesce(sm.TaxonomyHit.evidence_score, 0.0) >= 0.0001,
            ),
        )
    elif row_filter in TAXONOMY_CLADE_TAXIDS:
        taxid = TAXONOMY_CLADE_TAXIDS[row_filter]
        query = query.filter(lineage_text.contains(f'"taxid": "{taxid}"'))
    elif row_filter == "unclassified":
        query = query.filter(organism.contains("unclassified"))

    if search:
        needle = search.lower()
        query = query.filter(or_(
            organism.contains(needle),
            rank.contains(needle),
            func.lower(func.coalesce(sm.TaxonomyHit.taxid, "")).contains(needle),
            top_clade.contains(needle),
            func.lower(func.coalesce(sm.TaxonomyHit.warning, "")).contains(needle),
            lineage_text.contains(needle),
        ))
    return query


def _taxonomy_memory_filter(items: list[TaxonomyHit], row_filter: str, search: str) -> list[TaxonomyHit]:
    def rank(hit: TaxonomyHit) -> str:
        return str(hit.rank or hit.kingdom or "taxon").lower()

    def lineage_taxids(hit: TaxonomyHit) -> set[str]:
        return {str(node.get("taxid", "")).strip() for node in (hit.lineage or []) if isinstance(node, dict) and node.get("taxid")}

    def clade_matches(hit: TaxonomyHit, value: str) -> bool:
        taxid = TAXONOMY_CLADE_TAXIDS.get(value)
        return bool(taxid and taxid in lineage_taxids(hit))

    def review_level(hit: TaxonomyHit) -> bool:
        score = max(float(hit.confidence or 0), float(hit.evidence_score or 0))
        return rank(hit) == "species" and int(hit.read_count or 0) >= 100 and score >= 0.0001 and not hit.likely_contaminant

    out = []
    needle = search.lower()
    for hit in items:
        hit_rank = rank(hit)
        if row_filter == "species" and hit_rank != "species":
            continue
        if row_filter == "genus" and hit_rank != "genus":
            continue
        if row_filter == "lineage" and hit_rank in {"species", "genus", "unclassified"}:
            continue
        if row_filter == "review" and not review_level(hit):
            continue
        if row_filter in {"bacteria", "viruses", "fungi"} and not clade_matches(hit, row_filter):
            continue
        if row_filter == "unclassified" and "unclassified" not in str(hit.organism or "").lower():
            continue
        if needle:
            haystack = " ".join([
                str(hit.organism or ""),
                str(hit.rank or ""),
                str(hit.taxid or ""),
                str(hit.top_clade or ""),
                str(hit.warning or ""),
                *[str(node.get("name", "")) for node in (hit.lineage or []) if isinstance(node, dict) and node.get("name")],
                *lineage_taxids(hit),
            ]).lower()
            if needle not in haystack:
                continue
        out.append(hit)
    return out


def _taxonomy_total_reads(items: list[TaxonomyHit]) -> int:
    root = next((hit for hit in items if str(hit.rank or "").lower() == "root" or str(hit.organism or "").lower() == "root"), None)
    if root and root.read_count:
        return int(root.read_count)
    return max((int(hit.read_count or 0) for hit in items), default=0)


def _taxonomy_run_provenance(run_id: str, item_count: int, latest_item_created_at: str | None) -> tuple[dict | None, bool]:
    provenance = None
    latest_imported = next((e for e in reversed(run_events) if e.run_id == run_id and e.event_type == "taxonomy.imported"), None)
    latest_cleared = next((e for e in reversed(run_events) if e.run_id == run_id and e.event_type == "taxonomy.results_cleared"), None)
    latest_stage_event = next(
        (
            e for e in reversed(run_events)
            if e.run_id == run_id and e.event_type in {"taxonomy_started", "taxonomy_done"}
        ),
        None,
    )
    taxonomy_step_done = any(
        step.run_id == run_id and step.step_name == "taxonomy" and step.status == "done"
        for step in run_steps
    )
    taxonomy_step_status = next(
        (
            step.status
            for step in reversed(run_steps)
            if step.run_id == run_id and step.step_name == "taxonomy"
        ),
        None,
    )
    if latest_cleared and (not latest_imported or latest_cleared.created_at > latest_imported.created_at):
        provenance_event = latest_cleared
        cleared = True
    elif latest_imported:
        provenance_event = latest_imported
        cleared = False
    elif item_count > 0 and taxonomy_step_done:
        provenance_event = latest_stage_event
        cleared = False
        provenance = {
            "event_type": "taxonomy.imported",
            "created_at": latest_item_created_at,
            "count": item_count,
            "warning": "taxonomy_import_event_missing",
        }
    elif item_count > 0 and (latest_stage_event or taxonomy_step_status not in {None, "queued"}):
        provenance_event = latest_stage_event
        cleared = False
        provenance = {
            "event_type": "taxonomy.imported",
            "created_at": latest_item_created_at,
            "count": item_count,
            "warning": "taxonomy_import_event_missing_or_step_stale",
            "step_status": taxonomy_step_status,
        }
    else:
        provenance_event = latest_stage_event
        cleared = True
    if provenance is None and provenance_event:
        provenance = {
            "event_type": provenance_event.event_type,
            "created_at": provenance_event.created_at,
            **(provenance_event.payload or {}),
        }
    return provenance, cleared


def _taxonomy_db_page(skey: str, run_id: str | None, limit: int | None, offset: int, row_filter: str, search: str) -> dict | None:
    if SessionLocal is None:
        return None
    with SessionLocal() as session:
        base = session.query(sm.TaxonomyHit).filter(sm.TaxonomyHit.sample_id == skey)
        if run_id:
            base = base.filter(sm.TaxonomyHit.run_id == run_id)
        total_count = int(base.with_entities(func.count(sm.TaxonomyHit.id)).scalar() or 0)
        latest_created_at = base.with_entities(func.max(sm.TaxonomyHit.created_at)).scalar()
        root_reads = base.filter(or_(
            func.lower(func.coalesce(sm.TaxonomyHit.rank, "")) == "root",
            func.lower(func.coalesce(sm.TaxonomyHit.organism, "")) == "root",
        )).order_by(func.coalesce(sm.TaxonomyHit.read_count, 0).desc()).with_entities(sm.TaxonomyHit.read_count).first()
        max_reads = base.with_entities(func.max(sm.TaxonomyHit.read_count)).scalar() or 0
        filtered = _taxonomy_apply_db_filter(base, row_filter, search)
        filtered_count = int(filtered.with_entities(func.count(sm.TaxonomyHit.id)).scalar() or 0)
        ordered = filtered.order_by(func.coalesce(sm.TaxonomyHit.read_count, 0).desc(), sm.TaxonomyHit.created_at.desc())
        if limit is not None:
            ordered = ordered.offset(offset).limit(limit)
        rows = ordered.all()
        items = [_taxonomy_hit_from_row(row) for row in rows]
        return {
            "items": items,
            "total_count": total_count,
            "filtered_count": filtered_count,
            "latest_created_at": latest_created_at,
            "total_reads": int(root_reads[0]) if root_reads and root_reads[0] else int(max_reads or 0),
            "source": "db",
        }


def _taxonomy_memory_page(skey: str, run_id: str | None, limit: int | None, offset: int, row_filter: str, search: str) -> dict:
    items = [t for t in taxonomy_hits if t.sample_id == skey and (run_id is None or t.run_id == run_id)]
    items = sorted(items, key=lambda t: (t.read_count, t.created_at), reverse=True)
    total_count = len(items)
    latest_created_at = max((t.created_at for t in items if t.created_at), default=None)
    total_reads = _taxonomy_total_reads(items)
    items = _taxonomy_memory_filter(items, row_filter, search)
    filtered_count = len(items)
    page_items = items[offset:offset + limit] if limit is not None else items[offset:]
    return {
        "items": page_items,
        "total_count": total_count,
        "filtered_count": filtered_count,
        "latest_created_at": latest_created_at,
        "total_reads": total_reads,
        "source": "memory",
    }


@router.get("/samples/{sample_id}/taxonomy")
def get_taxonomy(
    sample_id: str,
    run_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    filter: str | None = None,
    search: str | None = None,
):
    skey = _resolve_sample_key(sample_id)
    page_limit, page_offset, row_filter, query_search = _taxonomy_page_params(limit, offset, filter, search)
    try:
        page_data = _taxonomy_db_page(skey, run_id, page_limit, page_offset, row_filter, query_search)
    except SQLAlchemyError as exc:
        print(f"[taxonomy] WARN: DB taxonomy read failed, falling back to memory cache: {exc}", flush=True)
        page_data = None
    if page_data is None:
        page_data = _taxonomy_memory_page(skey, run_id, page_limit, page_offset, row_filter, query_search)
    items = page_data["items"]
    total_count = page_data["total_count"]
    filtered_count = page_data["filtered_count"]
    provenance = None
    if run_id:
        provenance, cleared = _taxonomy_run_provenance(run_id, total_count, page_data.get("latest_created_at"))
        if cleared:
            items = []
            total_count = 0
            filtered_count = 0
    coverage_summary = _taxonomy_coverage_summary(items)
    return {
        "sample_id": sample_id,
        "run_id": run_id,
        "count": filtered_count,
        "total_count": total_count,
        "filtered_count": filtered_count,
        "limit": page_limit,
        "offset": page_offset,
        "has_more": page_limit is not None and page_offset + len(items) < filtered_count,
        "page_count": len(items),
        "total_reads": page_data.get("total_reads", 0),
        "source": page_data.get("source"),
        "items": items,
        "provenance": provenance,
        "coverage_breadth": coverage_summary,
        "interpretation_guardrail": "Sygnał taksonomiczny może oznaczać kontaminację, artefakt lub realną obecność materiału biologicznego.",
        "non_diagnostic": True,
    }


@router.get("/samples/{sample_id}/dark-matter/report")
def get_dark_matter_report(sample_id: str):
    sample = _resolve_sample_or_404(sample_id)
    return _dark_matter_summary_for_sample(sample)


@router.post("/runs/{run_id}/benchmark/import")
def import_benchmark_metrics(run_id: str, req: BenchmarkImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    parsed = {}
    if req.benchmark_report_path:
        report_path = Path(req.benchmark_report_path)
        if not report_path.exists():
            raise HTTPException(status_code=400, detail="benchmark_report_not_found")
        parsed = parse_benchmark_report(report_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="benchmark_report_parse_failed")

    benchmark_id = req.benchmark_id if req.benchmark_id is not None else parsed.get("benchmark_id")
    precision = req.precision if req.precision is not None else parsed.get("precision")
    recall = req.recall if req.recall is not None else parsed.get("recall")
    f1 = req.f1 if req.f1 is not None else parsed.get("f1")
    stratified_metrics = req.stratified_metrics if req.stratified_metrics else parsed.get("stratified_metrics", {})

    if not benchmark_id:
        raise HTTPException(status_code=400, detail="benchmark_id_required")
    if precision is None or recall is None or f1 is None:
        raise HTTPException(status_code=400, detail="benchmark_required_fields_missing")

    previous = [
        b
        for b in benchmark_records
        if b.benchmark_id == benchmark_id and b.sample_id == sample.sample_id and b.reference_id == run.reference_id
    ]
    previous_sorted = sorted(previous, key=lambda x: x.created_at)
    prev_f1 = previous_sorted[-1].f1 if previous_sorted else None

    regression_alert = None
    if prev_f1 is not None and f1 < (prev_f1 - 0.01):
        regression_alert = f"Benchmark regression detected: previous F1={prev_f1:.4f}, current F1={f1:.4f}"

    record = BenchmarkRecord(
        id=f"bm_{uuid4().hex[:10]}",
        benchmark_id=benchmark_id,
        sample_id=sample.sample_id,
        run_id=run.id,
        reference_id=run.reference_id,
        precision=precision,
        recall=recall,
        f1=f1,
        stratified_metrics=stratified_metrics,
        regression_alert=regression_alert,
    )
    add_benchmark_record(record)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="benchmark.imported",
            payload={
                "benchmark_id": benchmark_id,
                "f1": f1,
                "regression_alert": regression_alert,
                "benchmark_report_path": req.benchmark_report_path,
            },
        )
    )
    add_run_log_line(RunLogLine(run_id=run.id, line_no=len(run_logs) + 1, message="Benchmark metrics imported"))

    return record


@router.post("/runs/{run_id}/validation/vendor-assembly/import")
def import_vendor_assembly_validation(run_id: str, req: VendorAssemblyValidationImportRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    parsed = {}
    if req.vendor_validation_report_path:
        report_path = Path(req.vendor_validation_report_path)
        if not report_path.exists():
            raise HTTPException(status_code=400, detail="vendor_validation_report_not_found")
        parsed = parse_vendor_validation_report(report_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="vendor_validation_report_parse_failed")

    vendor_assembly_path = req.vendor_assembly_path if req.vendor_assembly_path is not None else parsed.get("vendor_assembly_path")
    if not vendor_assembly_path:
        raise HTTPException(status_code=400, detail="vendor_assembly_path_required")

    pipeline_assembly_path = (
        req.pipeline_assembly_path if req.pipeline_assembly_path is not None else parsed.get("pipeline_assembly_path")
    )
    similarity_score = req.similarity_score if req.similarity_score is not None else parsed.get("similarity_score")
    snv_concordance = req.snv_concordance if req.snv_concordance is not None else parsed.get("snv_concordance")
    indel_concordance = req.indel_concordance if req.indel_concordance is not None else parsed.get("indel_concordance")
    structural_concordance = (
        req.structural_concordance if req.structural_concordance is not None else parsed.get("structural_concordance")
    )
    comparator_method = (
        req.comparator_method if req.comparator_method != "proxy" else parsed.get("comparator_method", "proxy")
    )
    kmer_size = req.kmer_size if req.kmer_size is not None else parsed.get("kmer_size")
    pass_threshold = req.pass_threshold if req.pass_threshold != 0.98 else parsed.get("pass_threshold", 0.98)
    summary = req.summary if req.summary else parsed.get("summary", {})
    non_diagnostic = req.non_diagnostic if req.non_diagnostic is not True else parsed.get("non_diagnostic", True)

    vendor_path = Path(vendor_assembly_path)
    if not vendor_path.exists():
        raise HTTPException(status_code=400, detail="vendor_assembly_not_found")

    pipeline_path = Path(pipeline_assembly_path) if pipeline_assembly_path else None
    if pipeline_path and not pipeline_path.exists():
        raise HTTPException(status_code=400, detail="pipeline_assembly_not_found")

    if comparator_method not in {"proxy", "kmer", "exact", "vcf_exact"}:
        raise HTTPException(status_code=400, detail="unsupported_comparator_method")
    if kmer_size is not None and (kmer_size < 3 or kmer_size > 101):
        raise HTTPException(status_code=400, detail="invalid_kmer_size")

    if similarity_score is None and pipeline_path is not None:
        if comparator_method == "vcf_exact":
            computed = compare_vendor_vcfs(vendor_path, pipeline_path)
        else:
            computed = compare_vendor_assemblies(vendor_path, pipeline_path, method=comparator_method, kmer_size=kmer_size)
        similarity_score = computed.get("similarity_score")
        if snv_concordance is None:
            snv_concordance = computed.get("snv_concordance")
        if indel_concordance is None:
            indel_concordance = computed.get("indel_concordance")
        if structural_concordance is None:
            structural_concordance = computed.get("structural_concordance")
        summary = {**computed.get("stats", {}), **summary}
    summary = {"comparator_method": comparator_method, "kmer_size": kmer_size, **summary}

    metrics = [x for x in [similarity_score, snv_concordance, indel_concordance, structural_concordance] if x is not None]
    aggregate = similarity_score if similarity_score is not None else (sum(metrics) / len(metrics) if metrics else None)
    status = parsed.get("status", "unknown")
    if aggregate is not None:
        status = "passed" if aggregate >= pass_threshold else "failed"

    rec = VendorAssemblyValidation(
        id=f"vav_{uuid4().hex[:10]}",
        sample_id=sample.sample_id,
        run_id=run.id,
        reference_id=run.reference_id,
        vendor_assembly_path=str(vendor_path),
        pipeline_assembly_path=str(pipeline_path) if pipeline_path else None,
        similarity_score=similarity_score,
        snv_concordance=snv_concordance,
        indel_concordance=indel_concordance,
        structural_concordance=structural_concordance,
        comparator_method=comparator_method,
        kmer_size=kmer_size,
        pass_threshold=pass_threshold,
        status=status,
        summary=summary,
        non_diagnostic=non_diagnostic,
    )
    add_vendor_assembly_validation(rec)

    add_run_event(
        RunEvent(
            id=f"ev_{uuid4().hex[:10]}",
            run_id=run.id,
            event_type="vendor_assembly.validation_imported",
            payload={
                "validation_id": rec.id,
                "status": rec.status,
                "vendor_assembly_path": rec.vendor_assembly_path,
                "pipeline_assembly_path": rec.pipeline_assembly_path,
                "vendor_validation_report_path": req.vendor_validation_report_path,
            },
        )
    )
    add_run_log_line(
        RunLogLine(
            run_id=run.id,
            line_no=len(run_logs) + 1,
            message=f"Vendor assembly validation imported status={rec.status} id={rec.id}",
        )
    )

    return rec


@router.post("/runs/{run_id}/validation/vendor-assembly/import-from-fastq")
def import_vendor_assembly_validation_from_fastq(run_id: str, req: VendorAssemblyValidationFromFastqRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")
    if not sample.r1_path or not sample.r2_path:
        raise HTTPException(status_code=400, detail="sample_fastq_paths_required")

    r1 = Path(sample.r1_path)
    r2 = Path(sample.r2_path)
    if not r1.exists() or not r2.exists():
        raise HTTPException(status_code=400, detail="sample_fastq_not_found")

    vendor = Path(req.vendor_assembly_path)
    if not vendor.exists():
        raise HTTPException(status_code=400, detail="vendor_assembly_not_found")

    if req.comparator_method not in {"proxy", "kmer", "exact"}:
        raise HTTPException(status_code=400, detail="unsupported_comparator_method")
    if req.kmer_size is not None and (req.kmer_size < 3 or req.kmer_size > 101):
        raise HTTPException(status_code=400, detail="invalid_kmer_size")

    pipeline_out = (
        Path(req.pipeline_assembly_output_path)
        if req.pipeline_assembly_output_path
        else Path(f"results/validation/{run.id}.pipeline_assembly.from_fastq.fasta")
    )
    pipeline_out.parent.mkdir(parents=True, exist_ok=True)

    seq = build_stub_assembly_from_fastq(r1, r2, max_reads=max(1, req.max_reads))
    if not seq:
        raise HTTPException(status_code=400, detail="pipeline_assembly_empty")
    pipeline_out.write_text(f">pipeline_assembly\n{seq}\n", encoding="utf-8")

    rec = import_vendor_assembly_validation(
        run_id,
        VendorAssemblyValidationImportRequest(
            vendor_assembly_path=str(vendor),
            pipeline_assembly_path=str(pipeline_out),
            comparator_method=req.comparator_method,
            kmer_size=req.kmer_size,
            pass_threshold=req.pass_threshold,
            non_diagnostic=req.non_diagnostic,
        ),
    )

    return {
        "run_id": run.id,
        "sample_id": sample.sample_id,
        "pipeline_assembly_path": str(pipeline_out),
        "validation": rec,
        "non_diagnostic": True,
    }


@router.post("/runs/{run_id}/validation/vendor-assembly/e2e-from-fastq")
def run_vendor_assembly_validation_e2e_from_fastq(run_id: str, req: VendorAssemblyFastqE2ERequest):
    imported = import_vendor_assembly_validation_from_fastq(
        run_id,
        VendorAssemblyValidationFromFastqRequest(
            vendor_assembly_path=req.vendor_assembly_path,
            comparator_method=req.comparator_method,
            kmer_size=req.kmer_size,
            pass_threshold=req.pass_threshold,
            max_reads=req.max_reads,
            pipeline_assembly_output_path=req.pipeline_assembly_output_path,
            non_diagnostic=req.non_diagnostic,
        ),
    )

    bundle = None
    if req.generate_reports:
        bundle = generate_all_reports(run_id)

    latest = get_run_vendor_assembly_validation_latest(run_id)
    gate = get_run_vendor_assembly_validation_gate(run_id, min_similarity=req.pass_threshold)

    return {
        "run_id": run_id,
        "pipeline_assembly_path": imported.get("pipeline_assembly_path"),
        "validation": latest,
        "gate": gate,
        "report_bundle": {
            "count": bundle.get("count") if bundle else None,
            "bundle_manifest_path": bundle.get("bundle_manifest_path") if bundle else None,
            "bundle_index_path": bundle.get("bundle_index_path") if bundle else None,
        }
        if bundle
        else None,
        "non_diagnostic": True,
    }


@router.post("/validation/vendor-assembly/e2e-from-fastq")
def run_vendor_assembly_global_e2e_from_fastq(req: VendorAssemblyGlobalFastqE2ERequest):
    project_created = False
    if req.project_id:
        project = next((p for p in projects if p.id == req.project_id), None)
        if not project:
            raise HTTPException(status_code=404, detail="project_not_found")
    else:
        project = next((p for p in projects if p.name == req.project_name), None)
        if not project:
            if not req.create_project_if_missing:
                raise HTTPException(status_code=404, detail="project_not_found")
            project = create_project(ProjectCreateRequest(name=req.project_name))
            project_created = True

    sample_reused = False
    sample = None
    if req.reuse_existing_sample:
        sample = next((s for s in samples if s.project_id == project.id and s.sample_id == req.sample_id), None)

    if sample is None:
        sample = create_sample(
            project.id,
            SampleCreateRequest(
                sample_id=req.sample_id,
                reference_id=req.reference_id,
                r1_path=req.r1_path,
                r2_path=req.r2_path,
            ),
        )
    else:
        sample_reused = True
        if sample.reference_id != req.reference_id:
            raise HTTPException(status_code=400, detail="sample_reference_locked")
        sample.r1_path = req.r1_path
        sample.r2_path = req.r2_path

    if req.run_mode not in {"full", "benchmark"}:
        raise HTTPException(status_code=400, detail="unsupported_run_mode")
    if req.run_mode == "benchmark":
        run = create_run_benchmark(
            project.id,
            RunCreateRequest(
                sample_id=sample.id,
                reference_id=req.reference_id,
            ),
        )
    else:
        run = create_run_full(
            project.id,
            RunCreateRequest(
                sample_id=sample.id,
                reference_id=req.reference_id,
            ),
        )

    e2e = run_vendor_assembly_validation_e2e_from_fastq(
        run.id,
        VendorAssemblyFastqE2ERequest(
            vendor_assembly_path=req.vendor_assembly_path,
            comparator_method=req.comparator_method,
            kmer_size=req.kmer_size,
            pass_threshold=req.pass_threshold,
            max_reads=req.max_reads,
            generate_reports=req.generate_reports,
            non_diagnostic=req.non_diagnostic,
        ),
    )

    return {
        "project": project,
        "sample": sample,
        "run": run,
        "project_created": project_created,
        "sample_reused": sample_reused,
        "e2e": e2e,
        "non_diagnostic": True,
    }


@router.post("/runs/{run_id}/validation/vendor-assembly/compare")
def compare_vendor_assembly_validation(run_id: str, req: VendorAssemblyCompareRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    parsed = {}
    if req.vendor_validation_report_path:
        report_path = Path(req.vendor_validation_report_path)
        if not report_path.exists():
            raise HTTPException(status_code=400, detail="vendor_validation_report_not_found")
        parsed = parse_vendor_validation_report(report_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="vendor_validation_report_parse_failed")

    vendor_assembly_path = req.vendor_assembly_path if req.vendor_assembly_path is not None else parsed.get("vendor_assembly_path")
    pipeline_assembly_path = (
        req.pipeline_assembly_path if req.pipeline_assembly_path is not None else parsed.get("pipeline_assembly_path")
    )
    if not vendor_assembly_path:
        raise HTTPException(status_code=400, detail="vendor_assembly_path_required")
    if not pipeline_assembly_path:
        raise HTTPException(status_code=400, detail="pipeline_assembly_path_required")

    comparator_method = (
        req.comparator_method if req.comparator_method != "proxy" else parsed.get("comparator_method", "proxy")
    )
    kmer_size = req.kmer_size if req.kmer_size is not None else parsed.get("kmer_size")
    if comparator_method not in {"proxy", "kmer", "exact"}:
        raise HTTPException(status_code=400, detail="unsupported_comparator_method")
    if kmer_size is not None and (kmer_size < 3 or kmer_size > 101):
        raise HTTPException(status_code=400, detail="invalid_kmer_size")

    pass_threshold = req.pass_threshold if req.pass_threshold != 0.98 else parsed.get("pass_threshold", 0.98)

    vendor_path = Path(vendor_assembly_path)
    if not vendor_path.exists():
        raise HTTPException(status_code=400, detail="vendor_assembly_not_found")

    pipeline_path = Path(pipeline_assembly_path)
    if not pipeline_path.exists():
        raise HTTPException(status_code=400, detail="pipeline_assembly_not_found")

    computed = compare_vendor_assemblies(vendor_path, pipeline_path, method=comparator_method, kmer_size=kmer_size)
    similarity_score = computed.get("similarity_score")
    status = "unknown"
    if similarity_score is not None:
        status = "passed" if similarity_score >= pass_threshold else "failed"

    return {
        "run_id": run.id,
        "sample_id": sample.sample_id,
        "reference_id": run.reference_id,
        "vendor_assembly_path": str(vendor_path),
        "pipeline_assembly_path": str(pipeline_path),
        "similarity_score": computed.get("similarity_score"),
        "snv_concordance": computed.get("snv_concordance"),
        "indel_concordance": computed.get("indel_concordance"),
        "structural_concordance": computed.get("structural_concordance"),
        "comparator_method": comparator_method,
        "kmer_size": kmer_size,
        "pass_threshold": pass_threshold,
        "status": status,
        "summary": computed.get("stats", {}),
        "non_diagnostic": True,
    }


@router.post("/runs/{run_id}/validation/vendor-vcf/compare")
def compare_vendor_vcf_validation(run_id: str, req: VendorVcfCompareRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    vendor_path = Path(req.vendor_vcf_path)
    pipeline_path = Path(req.pipeline_vcf_path)
    if not vendor_path.exists():
        raise HTTPException(status_code=400, detail="vendor_vcf_not_found")
    if not pipeline_path.exists():
        raise HTTPException(status_code=400, detail="pipeline_vcf_not_found")

    computed = compare_vendor_vcfs(vendor_path, pipeline_path)
    similarity_score = computed.get("similarity_score")
    status = "unknown"
    if similarity_score is not None:
        status = "passed" if similarity_score >= req.pass_threshold else "failed"

    imported = None
    if req.import_result:
        imported = import_vendor_assembly_validation(
            run_id,
            VendorAssemblyValidationImportRequest(
                vendor_assembly_path=str(vendor_path),
                pipeline_assembly_path=str(pipeline_path),
                similarity_score=similarity_score,
                snv_concordance=computed.get("snv_concordance"),
                indel_concordance=computed.get("indel_concordance"),
                structural_concordance=computed.get("structural_concordance"),
                comparator_method="vcf_exact",
                pass_threshold=req.pass_threshold,
                summary=computed.get("stats", {}),
                non_diagnostic=True,
            ),
        )

    return {
        "run_id": run.id,
        "sample_id": sample.sample_id,
        "reference_id": run.reference_id,
        "vendor_vcf_path": str(vendor_path),
        "pipeline_vcf_path": str(pipeline_path),
        "similarity_score": similarity_score,
        "snv_concordance": computed.get("snv_concordance"),
        "indel_concordance": computed.get("indel_concordance"),
        "structural_concordance": computed.get("structural_concordance"),
        "comparator_method": "vcf_exact",
        "pass_threshold": req.pass_threshold,
        "status": status,
        "summary": computed.get("stats", {}),
        "imported_validation_id": imported.id if imported else None,
        "non_diagnostic": True,
    }


@router.post("/runs/{run_id}/validation/vendor-assembly/compare-kmer-sweep")
def compare_vendor_assembly_validation_kmer_sweep(run_id: str, req: VendorAssemblyKmerSweepRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    parsed = {}
    if req.vendor_validation_report_path:
        report_path = Path(req.vendor_validation_report_path)
        if not report_path.exists():
            raise HTTPException(status_code=400, detail="vendor_validation_report_not_found")
        parsed = parse_vendor_validation_report(report_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="vendor_validation_report_parse_failed")

    vendor_assembly_path = req.vendor_assembly_path if req.vendor_assembly_path is not None else parsed.get("vendor_assembly_path")
    pipeline_assembly_path = (
        req.pipeline_assembly_path if req.pipeline_assembly_path is not None else parsed.get("pipeline_assembly_path")
    )
    if not vendor_assembly_path:
        raise HTTPException(status_code=400, detail="vendor_assembly_path_required")
    if not pipeline_assembly_path:
        raise HTTPException(status_code=400, detail="pipeline_assembly_path_required")

    vendor_path = Path(vendor_assembly_path)
    if not vendor_path.exists():
        raise HTTPException(status_code=400, detail="vendor_assembly_not_found")

    pipeline_path = Path(pipeline_assembly_path)
    if not pipeline_path.exists():
        raise HTTPException(status_code=400, detail="pipeline_assembly_not_found")

    ks = sorted(set([int(k) for k in req.kmer_sizes if isinstance(k, int)]))
    if not ks:
        raise HTTPException(status_code=400, detail="kmer_sizes_required")
    if any((k < 3 or k > 101) for k in ks):
        raise HTTPException(status_code=400, detail="invalid_kmer_size")

    rows = []
    for k in ks:
        computed = compare_vendor_assemblies(vendor_path, pipeline_path, method="kmer", kmer_size=k)
        similarity_score = computed.get("similarity_score")
        status = "unknown"
        if similarity_score is not None:
            status = "passed" if similarity_score >= req.pass_threshold else "failed"
        rows.append(
            {
                "kmer_size": k,
                "similarity_score": similarity_score,
                "snv_concordance": computed.get("snv_concordance"),
                "indel_concordance": computed.get("indel_concordance"),
                "structural_concordance": computed.get("structural_concordance"),
                "status": status,
            }
        )

    sims = [r["similarity_score"] for r in rows if r.get("similarity_score") is not None]
    pass_rows = [r for r in rows if r.get("status") == "passed"]
    fail_kmers = [r["kmer_size"] for r in rows if r.get("status") == "failed"]
    best_row = max(rows, key=lambda r: (r.get("similarity_score") if r.get("similarity_score") is not None else -1.0))
    recommended_kmer_size = None
    if pass_rows:
        passing_sizes = sorted([r["kmer_size"] for r in pass_rows])
        recommended_kmer_size = passing_sizes[len(passing_sizes) // 2]
    else:
        recommended_kmer_size = best_row.get("kmer_size")

    return {
        "run_id": run.id,
        "sample_id": sample.sample_id,
        "reference_id": run.reference_id,
        "vendor_assembly_path": str(vendor_path),
        "pipeline_assembly_path": str(pipeline_path),
        "pass_threshold": req.pass_threshold,
        "count": len(rows),
        "kmer_sizes": ks,
        "results": rows,
        "summary": {
            "similarity_score_min": min(sims) if sims else None,
            "similarity_score_max": max(sims) if sims else None,
            "similarity_score_avg": round(sum(sims) / len(sims), 6) if sims else None,
            "pass_rate": round(len(pass_rows) / len(rows), 6),
            "failing_kmer_sizes": fail_kmers,
            "best_result": {
                "kmer_size": best_row.get("kmer_size"),
                "similarity_score": best_row.get("similarity_score"),
            },
            "recommended_kmer_size": recommended_kmer_size,
            "all_passed": all(r["status"] == "passed" for r in rows),
        },
        "non_diagnostic": True,
    }


@router.post("/runs/{run_id}/validation/vendor-assembly/recommendation")
def recommend_vendor_assembly_validation_method(run_id: str, req: VendorAssemblyRecommendationRequest):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    sample = next((s for s in samples if s.id == run.sample_id), None)
    if not sample:
        raise HTTPException(status_code=404, detail="sample_not_found")

    parsed = {}
    if req.vendor_validation_report_path:
        report_path = Path(req.vendor_validation_report_path)
        if not report_path.exists():
            raise HTTPException(status_code=400, detail="vendor_validation_report_not_found")
        parsed = parse_vendor_validation_report(report_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="vendor_validation_report_parse_failed")

    vendor_assembly_path = req.vendor_assembly_path if req.vendor_assembly_path is not None else parsed.get("vendor_assembly_path")
    pipeline_assembly_path = (
        req.pipeline_assembly_path if req.pipeline_assembly_path is not None else parsed.get("pipeline_assembly_path")
    )
    if not vendor_assembly_path:
        raise HTTPException(status_code=400, detail="vendor_assembly_path_required")
    if not pipeline_assembly_path:
        raise HTTPException(status_code=400, detail="pipeline_assembly_path_required")

    vendor_path = Path(vendor_assembly_path)
    if not vendor_path.exists():
        raise HTTPException(status_code=400, detail="vendor_assembly_not_found")
    pipeline_path = Path(pipeline_assembly_path)
    if not pipeline_path.exists():
        raise HTTPException(status_code=400, detail="pipeline_assembly_not_found")

    ks = sorted(set([int(k) for k in req.kmer_sizes if isinstance(k, int)]))
    if not ks:
        raise HTTPException(status_code=400, detail="kmer_sizes_required")
    if any((k < 3 or k > 101) for k in ks):
        raise HTTPException(status_code=400, detail="invalid_kmer_size")

    proxy = compare_vendor_assemblies(vendor_path, pipeline_path, method="proxy")
    exact = compare_vendor_assemblies(vendor_path, pipeline_path, method="exact")
    kmer_rows = []
    for k in ks:
        row = compare_vendor_assemblies(vendor_path, pipeline_path, method="kmer", kmer_size=k)
        kmer_rows.append({"kmer_size": k, "similarity_score": row.get("similarity_score")})

    candidates = [
        {
            "method": "proxy",
            "kmer_size": None,
            "similarity_score": proxy.get("similarity_score"),
            "status": "passed" if (proxy.get("similarity_score") or 0.0) >= req.pass_threshold else "failed",
        },
        {
            "method": "exact",
            "kmer_size": None,
            "similarity_score": exact.get("similarity_score"),
            "status": "passed" if (exact.get("similarity_score") or 0.0) >= req.pass_threshold else "failed",
        },
    ]
    for row in kmer_rows:
        sim = row.get("similarity_score")
        candidates.append(
            {
                "method": "kmer",
                "kmer_size": row.get("kmer_size"),
                "similarity_score": sim,
                "status": "passed" if (sim or 0.0) >= req.pass_threshold else "failed",
            }
        )

    passed = [c for c in candidates if c["status"] == "passed"]
    base = passed if passed else candidates
    recommended = max(base, key=lambda c: (c["similarity_score"] if c.get("similarity_score") is not None else -1.0))

    return {
        "run_id": run.id,
        "sample_id": sample.sample_id,
        "reference_id": run.reference_id,
        "vendor_assembly_path": str(vendor_path),
        "pipeline_assembly_path": str(pipeline_path),
        "pass_threshold": req.pass_threshold,
        "kmer_sizes": ks,
        "candidates": candidates,
        "recommendation": {
            "method": recommended.get("method"),
            "kmer_size": recommended.get("kmer_size"),
            "similarity_score": recommended.get("similarity_score"),
            "status": recommended.get("status"),
        },
        "non_diagnostic": True,
    }


@router.get("/runs/{run_id}/validation/vendor-assembly/latest")
def get_run_vendor_assembly_validation_latest(run_id: str):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    items = [x for x in vendor_assembly_validations if x.run_id == run.id]
    if not items:
        raise HTTPException(status_code=404, detail="vendor_assembly_validation_not_found")

    items.sort(key=lambda x: x.created_at)
    return items[-1]


@router.get("/runs/{run_id}/validation/vendor-assembly/history")
def get_run_vendor_assembly_validation_history(run_id: str):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    items = [x for x in vendor_assembly_validations if x.run_id == run.id]
    items.sort(key=lambda x: x.created_at)

    return {
        "run_id": run.id,
        "sample_id": run.sample_id,
        "count": len(items),
        "items": items,
        "non_diagnostic": True,
    }


@router.get("/benchmarks/{benchmark_id}")
def get_benchmark(benchmark_id: str):
    history = [b for b in benchmark_records if b.benchmark_id == benchmark_id]
    if not history:
        raise HTTPException(status_code=404, detail="benchmark_not_found")

    sorted_history = sorted(history, key=lambda x: x.created_at)
    last = sorted_history[-1]

    return {
        "benchmark_id": benchmark_id,
        "latest": last,
        "history": sorted_history,
        "regression_alert": last.regression_alert,
        "ui_tabs": ["Trust", "Benchmark", "Difficult Regions"],
    }


@router.get("/samples/{sample_id}/benchmark-history")
def get_sample_benchmark_history(sample_id: str):
    history = [b for b in benchmark_records if b.sample_id == sample_id]
    return {
        "sample_id": sample_id,
        "count": len(history),
        "history": sorted(history, key=lambda x: x.created_at),
    }


from app.core.benchmark_parser import get_giab_stratification_info


@router.get("/giab/info")
def get_giab_info():
    """Return GIAB truth set metadata, stratification resources, and download URLs."""
    info = get_giab_stratification_info()
    info["download_urls"] = {
        "HG002_GRCh38_v4.2.1_benchmark": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/latest/GRCh38/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz",
        "HG002_GRCh38_v4.2.1_benchmark_bed": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/latest/GRCh38/HG002_GRCh38_1_22_v4.2.1_benchmark_noinconsistent.bed",
        "HG002_GRCh37_v4.2.1_benchmark": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/latest/GRCh37/HG002_GRCh37_1_22_v4.2.1_benchmark.vcf.gz",
        "HG002_GRCh37_v4.2.1_benchmark_bed": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/latest/GRCh37/HG002_GRCh37_1_22_v4.2.1_benchmark_noinconsistent.bed",
        "stratification_GRCh38": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/latest/GRCh38/HG002_GRCh38_v4.2.1-stratifications/",
        "happy_tool": "https://github.com/Illumina/hap.py",
        "truvari_sv": "https://github.com/EnglishCabbage/Truvari",
    }
    return info


@router.get("/samples/{sample_id}/stratified-trust")
def get_stratified_trust(sample_id: str):
    """Return trust scores stratified by GIAB benchmark regions."""
    skey = _resolve_sample_key(sample_id)
    sample_variants = [v for v in variants if v.sample_id == skey]
    sample_benchmarks = [b for b in benchmark_records if b.sample_id == skey]

    latest_bm = sorted(sample_benchmarks, key=lambda x: x.created_at)[-1] if sample_benchmarks else None

    # Build variant-level trust distribution
    trust_bins = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for v in sample_variants:
        label = v.trust_label if hasattr(v, 'trust_label') else "unknown"
        trust_bins[label] = trust_bins.get(label, 0) + 1

    # Chrom distribution
    chrom_trust = {}
    for v in sample_variants:
        c = v.chrom if hasattr(v, 'chrom') else "unknown"
        if c not in chrom_trust:
            chrom_trust[c] = {"count": 0, "avg_trust": 0, "total": 0}
        chrom_trust[c]["count"] += 1
        chrom_trust[c]["total"] += v.trust_score if hasattr(v, 'trust_score') and v.trust_score else 0
    for c in chrom_trust:
        if chrom_trust[c]["count"] > 0:
            chrom_trust[c]["avg_trust"] = round(chrom_trust[c]["total"] / chrom_trust[c]["count"], 2)
        del chrom_trust[c]["total"]

    result = {
        "sample_id": skey,
        "variant_count": len(sample_variants),
        "trust_distribution": trust_bins,
        "chrom_trust": chrom_trust,
        "benchmark": None,
        "giab_stratified": None,
    }

    if latest_bm:
        result["benchmark"] = {
            "benchmark_id": latest_bm.benchmark_id,
            "precision": latest_bm.precision,
            "recall": latest_bm.recall,
            "f1": latest_bm.f1,
            "stratified_metrics": latest_bm.stratified_metrics,
            "regression_alert": latest_bm.regression_alert,
        }

        if latest_bm.stratified_metrics:
            result["giab_stratified"] = {
                region: {
                    "f1": val,
                    "rating": "pass" if val >= 0.99 else "warn" if val >= 0.95 else "fail",
                }
                for region, val in latest_bm.stratified_metrics.items()
            }

    return result


@router.get("/samples/{sample_id}/vendor-assembly-validations")
def get_sample_vendor_assembly_validations(sample_id: str):
    items = [x for x in vendor_assembly_validations if x.sample_id == sample_id]
    items.sort(key=lambda x: x.created_at, reverse=True)
    return {
        "sample_id": sample_id,
        "count": len(items),
        "items": items,
    }


@router.get("/samples/{sample_id}/vendor-assembly-validation-summary")
def get_sample_vendor_assembly_validation_summary(sample_id: str):
    items = [x for x in vendor_assembly_validations if x.sample_id == sample_id]
    if not items:
        return {
            "sample_id": sample_id,
            "count": 0,
            "status_counts": {"passed": 0, "failed": 0, "unknown": 0},
            "latest": None,
            "similarity_score_avg": None,
            "non_diagnostic": True,
        }

    items.sort(key=lambda x: x.created_at)
    status_counts = {
        "passed": len([x for x in items if x.status == "passed"]),
        "failed": len([x for x in items if x.status == "failed"]),
        "unknown": len([x for x in items if x.status == "unknown"]),
    }
    with_similarity = [x.similarity_score for x in items if x.similarity_score is not None]
    similarity_score_avg = round(sum(with_similarity) / len(with_similarity), 6) if with_similarity else None
    latest = items[-1]

    return {
        "sample_id": sample_id,
        "count": len(items),
        "status_counts": status_counts,
        "latest": latest,
        "similarity_score_avg": similarity_score_avg,
        "non_diagnostic": True,
    }


@router.get("/samples/{sample_id}/vendor-assembly-validation-gate")
def get_sample_vendor_assembly_validation_gate(sample_id: str, min_pass_rate: float = 0.8):
    summary = get_sample_vendor_assembly_validation_summary(sample_id)

    count = int(summary.get("count", 0) or 0)
    if count == 0:
        return {
            "sample_id": sample_id,
            "gate_status": "no_data",
            "pass_rate": None,
            "min_pass_rate": min_pass_rate,
            "latest_status": None,
            "non_diagnostic": True,
        }

    status_counts = summary.get("status_counts", {}) if isinstance(summary.get("status_counts"), dict) else {}
    passed = int(status_counts.get("passed", 0) or 0)
    pass_rate = passed / count
    latest = summary.get("latest")
    latest_status = getattr(latest, "status", None) if latest is not None else None

    gate_status = "failed"
    if pass_rate >= min_pass_rate and latest_status == "passed":
        gate_status = "passed"

    return {
        "sample_id": sample_id,
        "gate_status": gate_status,
        "pass_rate": round(pass_rate, 6),
        "min_pass_rate": min_pass_rate,
        "latest_status": latest_status,
        "non_diagnostic": True,
    }


@router.get("/runs/{run_id}/validation/vendor-assembly/gate")
def get_run_vendor_assembly_validation_gate(run_id: str, min_similarity: float = 0.98):
    run = next((r for r in runs if r.id == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

    latest = get_run_vendor_assembly_validation_latest(run_id)
    similarity = latest.similarity_score

    if similarity is None:
        return {
            "run_id": run_id,
            "sample_id": latest.sample_id,
            "gate_status": "no_data",
            "min_similarity": min_similarity,
            "similarity_score": None,
            "latest_status": latest.status,
            "non_diagnostic": True,
        }

    gate_status = "passed" if (latest.status == "passed" and similarity >= min_similarity) else "failed"

    return {
        "run_id": run_id,
        "sample_id": latest.sample_id,
        "gate_status": gate_status,
        "min_similarity": min_similarity,
        "similarity_score": similarity,
        "latest_status": latest.status,
        "non_diagnostic": True,
    }
