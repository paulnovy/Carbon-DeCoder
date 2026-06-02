"""Postgres-backed store implementation."""

from typing import Optional
from sqlalchemy.orm import Session

from app.db.store_interface import Store
from app.db.postgres_models import (
    ProjectRow, SampleRow, RunRow, RunStepRow, RunEventRow, RunLogRow,
    VariantCallRow, AlignmentMetricsRow, CoverageMetricsRow,
    StructuralVariantRow, CNVSegmentRow, TaxonomyHitRow,
    ReportArtifactRow, InterpretationResultRow, ReferenceGenomeRow,
)


def _to_dict(row):
    """Convert SQLAlchemy row to dict."""
    if row is None:
        return None
    d = {}
    for c in row.__table__.columns:
        val = getattr(row, c.name)
        if hasattr(val, 'isoformat'):
            val = val.isoformat()
        d[c.name] = val
    return d


class PostgresStore(Store):
    def __init__(self, db: Session):
        self.db = db

    # --- Projects ---
    def get_project(self, project_id: str):
        row = self.db.query(ProjectRow).filter(ProjectRow.id == project_id).first()
        return _to_dict(row)

    def list_projects(self):
        rows = self.db.query(ProjectRow).all()
        return [_to_dict(r) for r in rows]

    def create_project(self, project):
        row = ProjectRow(
            id=project.id, name=project.name,
            description=project.description, created_at=project.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    def delete_project(self, project_id: str):
        self.db.query(ProjectRow).filter(ProjectRow.id == project_id).delete()
        self.db.commit()

    # --- Samples ---
    def get_sample(self, sample_id: str):
        row = self.db.query(SampleRow).filter(SampleRow.id == sample_id).first()
        return _to_dict(row)

    def list_samples(self, project_id=None):
        q = self.db.query(SampleRow)
        if project_id:
            q = q.filter(SampleRow.project_id == project_id)
        return [_to_dict(r) for r in q.all()]

    def create_sample(self, sample):
        row = SampleRow(
            id=sample.id, project_id=sample.project_id,
            sample_id=sample.sample_id, reference_id=sample.reference_id,
            r1_path=sample.r1_path, r2_path=sample.r2_path,
            created_at=sample.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    def resolve_sample(self, sample_id: str):
        row = self.db.query(SampleRow).filter(SampleRow.id == sample_id).first()
        if not row:
            row = self.db.query(SampleRow).filter(SampleRow.sample_id == sample_id).first()
        return _to_dict(row)

    # --- Runs ---
    def get_run(self, run_id: str):
        row = self.db.query(RunRow).filter(RunRow.id == run_id).first()
        return _to_dict(row)

    def list_runs(self, project_id=None):
        q = self.db.query(RunRow)
        if project_id:
            q = q.filter(RunRow.project_id == project_id)
        return [_to_dict(r) for r in q.all()]

    def create_run(self, run):
        row = RunRow(
            id=run.id, project_id=run.project_id, sample_id=run.sample_id,
            mode=run.mode, status=run.status, reference_id=run.reference_id,
            created_at=run.created_at, updated_at=run.updated_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- Steps ---
    def get_step(self, step_id: str):
        row = self.db.query(RunStepRow).filter(RunStepRow.id == step_id).first()
        return _to_dict(row)

    def list_steps(self, run_id: str):
        rows = self.db.query(RunStepRow).filter(RunStepRow.run_id == run_id).all()
        return [_to_dict(r) for r in rows]

    def create_step(self, step):
        row = RunStepRow(
            id=step.id, run_id=step.run_id, step_name=step.step_name,
            status=step.status, progress_pct=step.progress_pct,
            last_log=step.last_log, created_at=step.created_at,
            updated_at=step.updated_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    def update_step(self, step_id: str, **kwargs):
        row = self.db.query(RunStepRow).filter(RunStepRow.id == step_id).first()
        if row:
            for k, v in kwargs.items():
                setattr(row, k, v)
            self.db.commit()
        return _to_dict(row)

    # --- Events ---
    def list_events(self, run_id: str):
        rows = self.db.query(RunEventRow).filter(RunEventRow.run_id == run_id).all()
        return [_to_dict(r) for r in rows]

    def create_event(self, event):
        row = RunEventRow(
            id=event.id, run_id=event.run_id, event_type=event.event_type,
            payload=event.payload, created_at=event.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- Logs ---
    def list_logs(self, run_id: str):
        rows = self.db.query(RunLogRow).filter(RunLogRow.run_id == run_id).all()
        return [_to_dict(r) for r in rows]

    def create_log(self, log):
        row = RunLogRow(
            id=log.id, run_id=log.run_id, stream=log.stream,
            message=log.message, created_at=log.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- Variants ---
    def list_variants(self, sample_id=None, run_id=None):
        q = self.db.query(VariantCallRow)
        if sample_id:
            q = q.filter(VariantCallRow.sample_id == sample_id)
        if run_id:
            q = q.filter(VariantCallRow.run_id == run_id)
        return [_to_dict(r) for r in q.all()]

    def create_variant(self, variant):
        row = VariantCallRow(
            id=variant.id, sample_id=variant.sample_id, run_id=variant.run_id,
            reference_id=variant.reference_id, chrom=variant.chrom,
            pos=variant.pos, ref=variant.ref, alt=variant.alt,
            variant_type=variant.variant_type, caller_list=variant.caller_list,
            caller_agreement_score=variant.caller_agreement_score,
            genotype=variant.genotype, zygosity=variant.zygosity,
            trust_score=variant.trust_score, trust_label=variant.trust_label,
            explainability=variant.explainability,
            clinical_annotation=variant.clinical_annotation,
            gnomad_freq=variant.gnomad_freq, consequence=variant.consequence,
            created_at=variant.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    def get_variant(self, variant_id: str):
        row = self.db.query(VariantCallRow).filter(VariantCallRow.id == variant_id).first()
        return _to_dict(row)

    def delete_variants_for_run(self, run_id: str):
        self.db.query(VariantCallRow).filter(VariantCallRow.run_id == run_id).delete()
        self.db.commit()

    # --- Alignment Metrics ---
    def list_alignment_metrics(self, run_id=None):
        q = self.db.query(AlignmentMetricsRow)
        if run_id:
            q = q.filter(AlignmentMetricsRow.run_id == run_id)
        return [_to_dict(r) for r in q.all()]

    def create_alignment_metrics(self, metrics):
        row = AlignmentMetricsRow(
            id=metrics.id, run_id=metrics.run_id, sample_id=metrics.sample_id,
            mapped_reads_pct=metrics.mapped_reads_pct,
            properly_paired_pct=metrics.properly_paired_pct,
            duplicates_pct=metrics.duplicates_pct,
            mapped_contigs=metrics.mapped_contigs,
            unmapped_reads=metrics.unmapped_reads,
            insert_size_median=metrics.insert_size_median,
            insert_size_mad=metrics.insert_size_mad,
            source_files=metrics.source_files,
            created_at=metrics.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- Coverage Metrics ---
    def list_coverage_metrics(self, run_id=None):
        q = self.db.query(CoverageMetricsRow)
        if run_id:
            q = q.filter(CoverageMetricsRow.run_id == run_id)
        return [_to_dict(r) for r in q.all()]

    def create_coverage_metrics(self, metrics):
        row = CoverageMetricsRow(
            id=metrics.id, run_id=metrics.run_id, sample_id=metrics.sample_id,
            mean_coverage=metrics.mean_coverage,
            median_coverage=metrics.median_coverage,
            callable_fraction=metrics.callable_fraction,
            coverage_ge_10x=metrics.coverage_ge_10x,
            coverage_ge_20x=metrics.coverage_ge_20x,
            coverage_ge_30x=metrics.coverage_ge_30x,
            source_files=metrics.source_files,
            created_at=metrics.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- Structural Variants ---
    def list_structural_variants(self, sample_id=None):
        q = self.db.query(StructuralVariantRow)
        if sample_id:
            q = q.filter(StructuralVariantRow.sample_id == sample_id)
        return [_to_dict(r) for r in q.all()]

    def create_structural_variant(self, sv):
        row = StructuralVariantRow(
            id=sv.id, sample_id=sv.sample_id, run_id=sv.run_id,
            sv_type=sv.sv_type, chrom=sv.chrom, pos=sv.pos,
            end_chrom=getattr(sv, 'end_chrom', None),
            end_pos=getattr(sv, 'end_pos', None),
            sv_size=getattr(sv, 'sv_size', None),
            quality_score=getattr(sv, 'quality_score', None),
            callers=getattr(sv, 'callers', []),
            trust_score=getattr(sv, 'trust_score', 0.0),
            created_at=sv.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- CNV Segments ---
    def list_cnv_segments(self, sample_id=None):
        q = self.db.query(CNVSegmentRow)
        if sample_id:
            q = q.filter(CNVSegmentRow.sample_id == sample_id)
        return [_to_dict(r) for r in q.all()]

    def create_cnv_segment(self, cnv):
        row = CNVSegmentRow(
            id=cnv.id, sample_id=cnv.sample_id, run_id=cnv.run_id,
            chrom=cnv.chrom, start=cnv.start, end=cnv.end,
            copy_number=cnv.copy_number,
            quality_score=getattr(cnv, 'quality_score', None),
            caller=getattr(cnv, 'caller', None),
            created_at=cnv.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- Taxonomy ---
    def list_taxonomy_hits(self, sample_id=None):
        q = self.db.query(TaxonomyHitRow)
        if sample_id:
            q = q.filter(TaxonomyHitRow.sample_id == sample_id)
        return [_to_dict(r) for r in q.all()]

    def create_taxonomy_hit(self, hit):
        row = TaxonomyHitRow(
            id=hit.id, sample_id=hit.sample_id, run_id=hit.run_id,
            reference_id=getattr(hit, 'reference_id', None),
            organism=hit.organism, kingdom=getattr(hit, 'kingdom', None),
            rank=getattr(hit, 'rank', None),
            taxid=getattr(hit, 'taxid', None),
            lineage=getattr(hit, 'lineage', []),
            top_clade=getattr(hit, 'top_clade', None),
            read_count=hit.read_count,
            confidence=hit.confidence, evidence_score=hit.evidence_score,
            tools=getattr(hit, 'tools', []),
            likely_contaminant=getattr(hit, 'likely_contaminant', False),
            warning=getattr(hit, 'warning', None),
            breadth_fraction=getattr(hit, 'breadth_fraction', None),
            coverage_depth=getattr(hit, 'coverage_depth', None),
            genome_covered_bp=getattr(hit, 'genome_covered_bp', None),
            genome_length_bp=getattr(hit, 'genome_length_bp', None),
            coverage_method=getattr(hit, 'coverage_method', None),
            non_diagnostic=getattr(hit, 'non_diagnostic', True),
            created_at=hit.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- Reports ---
    def list_reports(self, run_id=None):
        q = self.db.query(ReportArtifactRow)
        if run_id:
            q = q.filter(ReportArtifactRow.run_id == run_id)
        return [_to_dict(r) for r in q.all()]

    def create_report(self, report):
        row = ReportArtifactRow(
            id=report.id, run_id=report.run_id,
            report_type=report.report_type, status=report.status,
            html_path=report.html_path, json_path=report.json_path,
            par=getattr(report, 'parquet_path', None),
            summary=report.summary, created_at=report.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- Interpretation results ---
    def list_interpretation_results(self, sample_id=None, run_id=None, module=None):
        q = self.db.query(InterpretationResultRow)
        if sample_id:
            q = q.filter(InterpretationResultRow.sample_id == sample_id)
        if run_id:
            q = q.filter(InterpretationResultRow.run_id == run_id)
        if module:
            q = q.filter(InterpretationResultRow.module == module)
        return [_to_dict(r) for r in q.all()]

    def create_interpretation_result(self, result):
        row = InterpretationResultRow(
            id=result.id,
            sample_id=result.sample_id,
            run_id=result.run_id,
            module=result.module,
            status=result.status,
            count=result.count,
            summary=result.summary,
            provenance=result.provenance,
            non_diagnostic=result.non_diagnostic,
            created_at=result.created_at,
        )
        self.db.add(row)
        self.db.commit()
        return _to_dict(row)

    # --- References ---
    def list_references(self):
        rows = self.db.query(ReferenceGenomeRow).all()
        return [_to_dict(r) for r in rows]

    def get_reference(self, ref_id: str):
        row = self.db.query(ReferenceGenomeRow).filter(ReferenceGenomeRow.id == ref_id).first()
        return _to_dict(row)
