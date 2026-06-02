"""SQLAlchemy ORM models for Postgres persistence."""

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, JSON, Text, ForeignKey
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.db.connection import Base


def utc_now():
    return datetime.now(timezone.utc)


class ProjectRow(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    samples = relationship("SampleRow", back_populates="project", cascade="all, delete-orphan")
    runs = relationship("RunRow", back_populates="project", cascade="all, delete-orphan")


class SampleRow(Base):
    __tablename__ = "samples"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    sample_id = Column(String, nullable=False, index=True)
    reference_id = Column(String, nullable=False)
    r1_path = Column(String, nullable=True)
    r2_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    project = relationship("ProjectRow", back_populates="samples")


class RunRow(Base):
    __tablename__ = "runs"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    sample_id = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False, default="full")
    status = Column(String, nullable=False, default="queued")
    reference_id = Column(String, nullable=False)
    repo_commit = Column(String, nullable=True)
    docker_image_version = Column(String, nullable=True)
    nextflow_version = Column(String, nullable=True)
    pipeline_version = Column(String, nullable=True)
    command_line = Column(String, nullable=True)
    parameters = Column(JSON, default=dict)
    input_checksums = Column(JSON, default=dict)
    output_checksums = Column(JSON, default=dict)
    tool_versions = Column(JSON, default=dict)
    database_versions = Column(JSON, default=dict)
    environment = Column(JSON, default=dict)
    report_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    project = relationship("ProjectRow", back_populates="runs")


class RunStepRow(Base):
    __tablename__ = "run_steps"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    step_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")
    progress_pct = Column(Float, default=0.0)
    runtime_sec = Column(Float, nullable=True)
    cpu_pct = Column(Float, nullable=True)
    ram_mb = Column(Integer, nullable=True)
    disk_mb = Column(Integer, nullable=True)
    current_file = Column(String, nullable=True)
    last_log = Column(String, nullable=True)
    warning = Column(String, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class RunEventRow(Base):
    __tablename__ = "run_events"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)


class RunLogRow(Base):
    __tablename__ = "run_logs"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    stream = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)


class VariantCallRow(Base):
    __tablename__ = "variant_calls"
    id = Column(String, primary_key=True)
    sample_id = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    reference_id = Column(String, nullable=False)
    chrom = Column(String, nullable=False)
    pos = Column(Integer, nullable=False)
    ref = Column(String, nullable=False)
    alt = Column(String, nullable=False)
    variant_type = Column(String, default="SNV")
    caller_list = Column(JSON, default=list)
    caller_agreement_score = Column(Float, default=0.0)
    quality_score = Column(Float, nullable=True)
    genotype = Column(String, nullable=True)
    zygosity = Column(String, nullable=True)
    read_depth = Column(Integer, nullable=True)
    trust_score = Column(Float, default=0.0)
    trust_label = Column(String, default="unknown")
    explainability = Column(JSON, default=dict)
    clinical_annotation = Column(String, nullable=True)
    gnomad_freq = Column(Float, nullable=True)
    consequence = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class AlignmentMetricsRow(Base):
    __tablename__ = "alignment_metrics"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    sample_id = Column(String, nullable=False, index=True)
    mapped_reads_pct = Column(Float, nullable=True)
    properly_paired_pct = Column(Float, nullable=True)
    duplicates_pct = Column(Float, nullable=True)
    mapped_contigs = Column(Integer, nullable=True)
    unmapped_reads = Column(Integer, nullable=True)
    insert_size_median = Column(Float, nullable=True)
    insert_size_mad = Column(Float, nullable=True)
    source_files = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now)


class CoverageMetricsRow(Base):
    __tablename__ = "coverage_metrics"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    sample_id = Column(String, nullable=False, index=True)
    mean_coverage = Column(Float, nullable=True)
    median_coverage = Column(Float, nullable=True)
    callable_fraction = Column(Float, nullable=True)
    coverage_ge_1x = Column(Float, nullable=True)
    coverage_ge_10x = Column(Float, nullable=True)
    coverage_ge_20x = Column(Float, nullable=True)
    coverage_ge_30x = Column(Float, nullable=True)
    coverage_ge_50x = Column(Float, nullable=True)
    source_files = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now)


class StructuralVariantRow(Base):
    __tablename__ = "structural_variants"
    id = Column(String, primary_key=True)
    sample_id = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    sv_type = Column(String, nullable=True)
    chrom = Column(String, nullable=True)
    pos = Column(Integer, nullable=True)
    end_chrom = Column(String, nullable=True)
    end_pos = Column(Integer, nullable=True)
    sv_size = Column(Integer, nullable=True)
    quality_score = Column(Float, nullable=True)
    callers = Column(JSON, default=list)
    trust_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utc_now)


class CNVSegmentRow(Base):
    __tablename__ = "cnv_segments"
    id = Column(String, primary_key=True)
    sample_id = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    chrom = Column(String, nullable=True)
    start = Column(Integer, nullable=True)
    end = Column(Integer, nullable=True)
    copy_number = Column(Integer, nullable=True)
    quality_score = Column(Float, nullable=True)
    caller = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class ReportArtifactRow(Base):
    __tablename__ = "report_artifacts"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    report_type = Column(String, nullable=False)
    status = Column(String, default="generated")
    html_path = Column(String, nullable=True)
    json_path = Column(String, nullable=True)
    parquet_path = Column(String, nullable=True)
    summary = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)


class InterpretationResultRow(Base):
    __tablename__ = "interpretation_results"
    id = Column(String, primary_key=True)
    sample_id = Column(String, nullable=False, index=True)
    run_id = Column(String, nullable=True, index=True)
    module = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    count = Column(Integer, default=0)
    summary = Column(JSON, default=dict)
    provenance = Column(JSON, default=dict)
    non_diagnostic = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)


class TaxonomyHitRow(Base):
    __tablename__ = "taxonomy_hits"
    id = Column(String, primary_key=True)
    sample_id = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    reference_id = Column(String, nullable=True)
    organism = Column(String, nullable=True)
    kingdom = Column(String, nullable=True)
    rank = Column(String, nullable=True)
    taxid = Column(String, nullable=True)
    lineage = Column(JSON, default=list)
    top_clade = Column(String, nullable=True)
    read_count = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    evidence_score = Column(Float, nullable=True)
    tools = Column(JSON, default=list)
    likely_contaminant = Column(Boolean, default=False)
    warning = Column(Text, nullable=True)
    breadth_fraction = Column(Float, nullable=True)
    coverage_depth = Column(Float, nullable=True)
    genome_covered_bp = Column(Integer, nullable=True)
    genome_length_bp = Column(Integer, nullable=True)
    coverage_method = Column(String, nullable=True)
    non_diagnostic = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)


class QCSummaryRow(Base):
    __tablename__ = "qc_summaries"
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    sample_id = Column(String, nullable=False, index=True)
    status = Column(String, default="unknown")
    total_reads = Column(Integer, nullable=True)
    gc_content_pct = Column(Float, nullable=True)
    duplication_rate_pct = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class PRSResultRow(Base):
    __tablename__ = "prs_results"
    id = Column(String, primary_key=True)
    sample_id = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    trait = Column(String, nullable=True)
    score_value = Column(Float, nullable=True)
    overlap_pct = Column(Float, nullable=True)
    quality_label = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class MtDNAResultRow(Base):
    __tablename__ = "mtdna_results"
    id = Column(String, primary_key=True)
    sample_id = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    haplogroup = Column(String, nullable=True)
    heteroplasmy_mean_vaf = Column(Float, nullable=True)
    num_variants = Column(Integer, nullable=True)
    numts_warning = Column(Boolean, default=False)
    trust_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utc_now)


class BenchmarkRecordRow(Base):
    __tablename__ = "benchmark_records"
    id = Column(String, primary_key=True)
    sample_id = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    benchmark_type = Column(String, nullable=True)
    snp_recall = Column(Float, nullable=True)
    snp_precision = Column(Float, nullable=True)
    indel_recall = Column(Float, nullable=True)
    indel_precision = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class VendorAssemblyValidationRow(Base):
    __tablename__ = "vendor_assembly_validations"
    id = Column(String, primary_key=True)
    sample_id = Column(String, nullable=False, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    status = Column(String, default="unknown")
    comparator_mode = Column(String, nullable=True)
    concordance_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class ReferenceGenomeRow(Base):
    __tablename__ = "reference_genomes"
    id = Column(String, primary_key=True)
    version = Column(String, nullable=True)
    source = Column(String, nullable=True)
    contig_style = Column(String, nullable=True)
    mitochondrial_contig = Column(String, nullable=True)
    status = Column(String, default="missing")
    aliases = Column(JSON, default=list)
    fasta_path = Column(String, nullable=True)
    fai_path = Column(String, nullable=True)
    dict_path = Column(String, nullable=True)
    download_url = Column(Text, nullable=True)
    download_sha256 = Column(Text, nullable=True)
