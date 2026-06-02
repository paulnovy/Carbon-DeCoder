from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SchemaVersion(Base):
    __tablename__ = "schema_versions"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    app_version: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[str] = mapped_column(String, nullable=False)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class Sample(Base):
    __tablename__ = "samples"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    sample_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    r1_path: Mapped[str | None] = mapped_column(String)
    r2_path: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    sample_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    repo_commit: Mapped[str | None] = mapped_column(String)
    docker_image_version: Mapped[str | None] = mapped_column(String)
    nextflow_version: Mapped[str | None] = mapped_column(String)
    pipeline_version: Mapped[str | None] = mapped_column(String)
    command_line: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    input_checksums: Mapped[dict] = mapped_column(JSON, default=dict)
    output_checksums: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    database_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    environment: Mapped[dict] = mapped_column(JSON, default=dict)
    report_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class RunStep(Base):
    __tablename__ = "run_steps"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    step_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    runtime_sec: Mapped[int] = mapped_column(Integer, default=0)
    cpu_pct: Mapped[float | None] = mapped_column(Float)
    ram_mb: Mapped[float | None] = mapped_column(Float)
    disk_mb: Mapped[float | None] = mapped_column(Float)
    current_file: Mapped[str | None] = mapped_column(String)
    last_log: Mapped[str | None] = mapped_column(Text)
    warning: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class RunLogLine(Base):
    __tablename__ = "run_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class QCSummary(Base):
    __tablename__ = "qc_summaries"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    total_reads: Mapped[int | None] = mapped_column(Integer)
    gc_content_pct: Mapped[float | None] = mapped_column(Float)
    duplication_rate_pct: Mapped[float | None] = mapped_column(Float)
    mean_read_length: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class AlignmentMetric(Base):
    __tablename__ = "alignment_metrics"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    mapped_reads_pct: Mapped[float | None] = mapped_column(Float)
    properly_paired_pct: Mapped[float | None] = mapped_column(Float)
    duplicates_pct: Mapped[float | None] = mapped_column(Float)
    mapped_contigs: Mapped[int | None] = mapped_column(Integer)
    unmapped_reads: Mapped[int | None] = mapped_column(Integer)
    insert_size_median: Mapped[float | None] = mapped_column(Float)
    insert_size_mad: Mapped[float | None] = mapped_column(Float)
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class CoverageMetric(Base):
    __tablename__ = "coverage_metrics"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    reference_id: Mapped[str | None] = mapped_column(String)
    mean_coverage: Mapped[float | None] = mapped_column(Float)
    median_coverage: Mapped[float | None] = mapped_column(Float)
    callable_fraction: Mapped[float | None] = mapped_column(Float)
    coverage_ge_10x: Mapped[float | None] = mapped_column(Float)
    coverage_ge_20x: Mapped[float | None] = mapped_column(Float)
    coverage_ge_30x: Mapped[float | None] = mapped_column(Float)
    source_files: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class VariantCall(Base):
    __tablename__ = "variant_calls"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    chrom: Mapped[str] = mapped_column(String, nullable=False)
    pos: Mapped[int] = mapped_column(Integer, nullable=False)
    ref: Mapped[str] = mapped_column(String, nullable=False)
    alt: Mapped[str] = mapped_column(String, nullable=False)
    variant_type: Mapped[str] = mapped_column(String, nullable=False, default="SNV")
    caller_list: Mapped[list] = mapped_column(JSON, default=list)
    caller_agreement_score: Mapped[float] = mapped_column(Float, default=0.0)
    trust_score: Mapped[float] = mapped_column(Float, default=0.0)
    trust_label: Mapped[str] = mapped_column(String, default="unknown")
    genotype: Mapped[str | None] = mapped_column(String)
    zygosity: Mapped[str | None] = mapped_column(String)
    explainability: Mapped[dict] = mapped_column(JSON, default=dict)
    clinical_annotation: Mapped[str | None] = mapped_column(Text)
    gnomad_freq: Mapped[float | None] = mapped_column(Float)
    consequence: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class StructuralVariant(Base):
    __tablename__ = "structural_variants"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    chrom: Mapped[str] = mapped_column(String, nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    sv_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_types: Mapped[list] = mapped_column(JSON, default=list)
    caller_list: Mapped[list] = mapped_column(JSON, default=list)
    trust_score: Mapped[float] = mapped_column(Float, default=0.0)
    trust_label: Mapped[str] = mapped_column(String, default="unknown")
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class CNVSegment(Base):
    __tablename__ = "cnv_segments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    chrom: Mapped[str] = mapped_column(String, nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    copy_number: Mapped[float] = mapped_column(Float, nullable=False)
    cnv_type: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    trust_score: Mapped[float] = mapped_column(Float, default=0.0)
    trust_label: Mapped[str] = mapped_column(String, default="unknown")
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class MtDNAResult(Base):
    __tablename__ = "mtdna_results"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    haplogroup: Mapped[str | None] = mapped_column(String)
    heteroplasmy_mean_vaf: Mapped[float | None] = mapped_column(Float)
    num_variants: Mapped[int] = mapped_column(Integer, default=0)
    numts_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    trust_score: Mapped[float] = mapped_column(Float, default=0.0)
    trust_label: Mapped[str] = mapped_column(String, default="unknown")
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class PRSResult(Base):
    __tablename__ = "prs_results"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    trait: Mapped[str] = mapped_column(String, nullable=False)
    score_value: Mapped[float] = mapped_column(Float, nullable=False)
    overlap_pct: Mapped[float] = mapped_column(Float, nullable=False)
    variant_count_total: Mapped[int] = mapped_column(Integer, default=0)
    variant_count_matched: Mapped[int] = mapped_column(Integer, default=0)
    quality_label: Mapped[str] = mapped_column(String, default="unknown")
    warning: Mapped[str | None] = mapped_column(Text)
    non_diagnostic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class TaxonomyHit(Base):
    __tablename__ = "taxonomy_hits"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    organism: Mapped[str] = mapped_column(String, nullable=False)
    kingdom: Mapped[str] = mapped_column(String, nullable=False)
    rank: Mapped[str | None] = mapped_column(String)
    taxid: Mapped[str | None] = mapped_column(String)
    lineage: Mapped[list] = mapped_column(JSON, default=list)
    top_clade: Mapped[str | None] = mapped_column(String)
    read_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    tools: Mapped[list] = mapped_column(JSON, default=list)
    likely_contaminant: Mapped[bool] = mapped_column(Boolean, default=False)
    warning: Mapped[str | None] = mapped_column(Text)
    breadth_fraction: Mapped[float | None] = mapped_column(Float)
    coverage_depth: Mapped[float | None] = mapped_column(Float)
    genome_covered_bp: Mapped[int | None] = mapped_column(Integer)
    genome_length_bp: Mapped[int | None] = mapped_column(Integer)
    coverage_method: Mapped[str | None] = mapped_column(String)
    non_diagnostic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class BenchmarkRecord(Base):
    __tablename__ = "benchmark_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    benchmark_id: Mapped[str] = mapped_column(String, nullable=False)
    sample_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    precision: Mapped[float] = mapped_column(Float, nullable=False)
    recall: Mapped[float] = mapped_column(Float, nullable=False)
    f1: Mapped[float] = mapped_column(Float, nullable=False)
    stratified_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    regression_alert: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class VendorAssemblyValidation(Base):
    __tablename__ = "vendor_assembly_validations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    vendor_assembly_path: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_assembly_path: Mapped[str | None] = mapped_column(Text)
    similarity_score: Mapped[float | None] = mapped_column(Float)
    snv_concordance: Mapped[float | None] = mapped_column(Float)
    indel_concordance: Mapped[float | None] = mapped_column(Float)
    structural_concordance: Mapped[float | None] = mapped_column(Float)
    comparator_method: Mapped[str] = mapped_column(String, nullable=False, default="proxy")
    kmer_size: Mapped[int | None] = mapped_column(Integer)
    pass_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.98)
    status: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    non_diagnostic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class ReferenceGenome(Base):
    __tablename__ = "reference_genomes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    contig_style: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    mitochondrial_contig: Mapped[str | None] = mapped_column(String)
    fasta_path: Mapped[str | None] = mapped_column(Text)
    fai_path: Mapped[str | None] = mapped_column(Text)
    dict_path: Mapped[str | None] = mapped_column(Text)
    download_url: Mapped[str | None] = mapped_column(Text)
    download_sha256: Mapped[str | None] = mapped_column(Text)


class ReportArtifact(Base):
    __tablename__ = "report_artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    html_path: Mapped[str | None] = mapped_column(String)
    json_path: Mapped[str | None] = mapped_column(String)
    parquet_path: Mapped[str | None] = mapped_column(String)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class InterpretationResult(Base):
    __tablename__ = "interpretation_results"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True)
    module: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    non_diagnostic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


Index("ix_variants_sample_run", VariantCall.sample_id, VariantCall.run_id)
Index("ix_structural_sample_run", StructuralVariant.sample_id, StructuralVariant.run_id)
Index("ix_cnv_sample_run", CNVSegment.sample_id, CNVSegment.run_id)
