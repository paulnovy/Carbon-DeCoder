from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReferenceGenome(BaseModel):
    id: str
    version: str
    source: str
    contig_style: str
    status: str = "missing"
    aliases: list[str] = Field(default_factory=list)
    mitochondrial_contig: str | None = None
    fasta_path: str | None = None
    fai_path: str | None = None
    dict_path: str | None = None
    download_url: str | None = None
    download_sha256: str | None = None


class Project(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)


class Sample(BaseModel):
    id: str
    project_id: str
    sample_id: str
    reference_id: str
    r1_path: Optional[str] = None
    r2_path: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)


class Run(BaseModel):
    id: str
    project_id: str
    sample_id: str
    mode: str
    status: str = "queued"
    reference_id: str
    repo_commit: Optional[str] = None
    docker_image_version: Optional[str] = None
    nextflow_version: Optional[str] = None
    pipeline_version: Optional[str] = None
    command_line: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_checksums: dict[str, str] = Field(default_factory=dict)
    output_checksums: dict[str, str] = Field(default_factory=dict)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    database_versions: dict[str, str] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    report_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class RunEvent(BaseModel):
    id: str
    run_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class RunStep(BaseModel):
    id: str
    run_id: str
    step_name: str
    status: str = "queued"
    progress_pct: float = 0.0
    runtime_sec: int = 0
    cpu_pct: Optional[float] = None
    ram_mb: Optional[float] = None
    disk_mb: Optional[float] = None
    current_file: Optional[str] = None
    last_log: Optional[str] = None
    warning: Optional[str] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class RunLogLine(BaseModel):
    run_id: str
    line_no: int
    message: str
    created_at: str = Field(default_factory=utc_now)


class QCSummary(BaseModel):
    sample_id: str
    run_id: str
    total_reads: Optional[int] = None
    gc_content_pct: Optional[float] = None
    duplication_rate_pct: Optional[float] = None
    mean_read_length: Optional[float] = None
    status: str = "unknown"
    source_files: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class AlignmentMetrics(BaseModel):
    sample_id: str
    run_id: str
    mapped_reads_pct: Optional[float] = None
    properly_paired_pct: Optional[float] = None
    duplicates_pct: Optional[float] = None
    mapped_contigs: Optional[int] = None
    unmapped_reads: Optional[int] = None
    insert_size_median: Optional[float] = None
    insert_size_mad: Optional[float] = None
    source_files: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class CoverageMetrics(BaseModel):
    sample_id: str
    run_id: str
    mean_coverage: Optional[float] = None
    median_coverage: Optional[float] = None
    callable_fraction: Optional[float] = None
    coverage_ge_10x: Optional[float] = None
    coverage_ge_20x: Optional[float] = None
    coverage_ge_30x: Optional[float] = None
    source_files: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class ReportArtifact(BaseModel):
    id: str
    run_id: str
    report_type: str
    status: str = "generated"
    html_path: Optional[str] = None
    json_path: Optional[str] = None
    parquet_path: Optional[str] = None
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class InterpretationResult(BaseModel):
    id: str
    sample_id: str
    run_id: Optional[str] = None
    module: str
    status: str
    count: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    non_diagnostic: bool = True
    created_at: str = Field(default_factory=utc_now)


class VariantCall(BaseModel):
    id: str
    sample_id: str
    run_id: str
    reference_id: str
    chrom: str
    pos: int
    ref: str
    alt: str
    variant_type: str = "SNV"
    caller_list: list[str] = Field(default_factory=list)
    caller_agreement_score: float = 0.0
    trust_score: float = 0.0
    trust_label: str = "unknown"
    genotype: Optional[str] = None
    zygosity: Optional[str] = None
    explainability: dict[str, float] = Field(default_factory=dict)
    clinical_annotation: Optional[str] = None
    gnomad_freq: Optional[float] = None
    consequence: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)


class StructuralVariant(BaseModel):
    id: str
    sample_id: str
    run_id: str
    reference_id: str
    chrom: str
    start: int
    end: int
    sv_type: str
    size_bp: int
    evidence_types: list[str] = Field(default_factory=list)
    caller_list: list[str] = Field(default_factory=list)
    trust_score: float = 0.0
    trust_label: str = "unknown"
    created_at: str = Field(default_factory=utc_now)


class CNVSegment(BaseModel):
    id: str
    sample_id: str
    run_id: str
    reference_id: str
    chrom: str
    start: int
    end: int
    copy_number: float
    cnv_type: str
    method: str
    trust_score: float = 0.0
    trust_label: str = "unknown"
    created_at: str = Field(default_factory=utc_now)


class MtDNAResult(BaseModel):
    id: str
    sample_id: str
    run_id: str
    reference_id: str
    haplogroup: Optional[str] = None
    heteroplasmy_mean_vaf: Optional[float] = None
    num_variants: int = 0
    numts_warning: bool = False
    trust_score: float = 0.0
    trust_label: str = "unknown"
    created_at: str = Field(default_factory=utc_now)


class PRSResult(BaseModel):
    id: str
    sample_id: str
    run_id: str
    reference_id: str
    trait: str
    score_value: float
    overlap_pct: float
    variant_count_total: int
    variant_count_matched: int
    quality_label: str = "unknown"
    warning: Optional[str] = None
    non_diagnostic: bool = True
    created_at: str = Field(default_factory=utc_now)


class TaxonomyHit(BaseModel):
    id: str
    sample_id: str
    run_id: str
    reference_id: str
    organism: str
    kingdom: str
    rank: Optional[str] = None
    taxid: Optional[str] = None
    lineage: list[dict[str, Any]] = Field(default_factory=list)
    top_clade: Optional[str] = None
    read_count: int
    confidence: float
    evidence_score: float
    tools: list[str] = Field(default_factory=list)
    likely_contaminant: bool = False
    warning: Optional[str] = None
    breadth_fraction: Optional[float] = None
    coverage_depth: Optional[float] = None
    genome_covered_bp: Optional[int] = None
    genome_length_bp: Optional[int] = None
    coverage_method: Optional[str] = None
    non_diagnostic: bool = True
    created_at: str = Field(default_factory=utc_now)

    @field_validator("lineage", "tools", mode="before")
    @classmethod
    def _coerce_nullable_lists(cls, value):
        return [] if value is None else value


class BenchmarkRecord(BaseModel):
    id: str
    benchmark_id: str
    sample_id: str
    run_id: str
    reference_id: str
    precision: float
    recall: float
    f1: float
    stratified_metrics: dict[str, float] = Field(default_factory=dict)
    regression_alert: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)


class VendorAssemblyValidation(BaseModel):
    id: str
    sample_id: str
    run_id: str
    reference_id: str
    vendor_assembly_path: str
    pipeline_assembly_path: Optional[str] = None
    similarity_score: Optional[float] = None
    snv_concordance: Optional[float] = None
    indel_concordance: Optional[float] = None
    structural_concordance: Optional[float] = None
    comparator_method: str = "proxy"
    kmer_size: Optional[int] = None
    pass_threshold: float = 0.98
    status: str = "unknown"
    summary: dict[str, Any] = Field(default_factory=dict)
    non_diagnostic: bool = True
    created_at: str = Field(default_factory=utc_now)
