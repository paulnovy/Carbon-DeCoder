from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import SessionLocal, engine, init_db as _sql_init_db
from app.db.models import (
    AlignmentMetrics,
    BenchmarkRecord,
    CNVSegment,
    CoverageMetrics,
    InterpretationResult,
    MtDNAResult,
    PRSResult,
    Project,
    QCSummary,
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
from app.db import sql_models as sm


USE_DB = engine is not None and SessionLocal is not None


def _resolve_sample_key(sample_id: str) -> str:
    return sample_id


class BackedList(list):
    def __init__(self, items: list, on_change: Callable[[], None] | None = None):
        super().__init__(items)
        self._on_change = on_change

    def _changed(self):
        if self._on_change:
            self._on_change()

    def append(self, item):
        super().append(item)
        self._changed()

    def append_local(self, item):
        """Append without triggering table-wide sync. Used by explicit upsert helpers."""
        super().append(item)

    def extend(self, items):
        super().extend(items)
        self._changed()

    def remove(self, item):
        super().remove(item)
        self._changed()

    def remove_local(self, item):
        """Remove without triggering table-wide sync. Used by explicit delete helpers."""
        super().remove(item)

    def pop(self, idx=-1):
        value = super().pop(idx)
        self._changed()
        return value

    def clear(self):
        super().clear()
        self._changed()

    def insert(self, index, item):
        super().insert(index, item)
        self._changed()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._changed()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._changed()

    def replace_all(self, items: list, on_change: Callable[[], None] | None = None):
        old_on_change = self._on_change
        self._on_change = None
        super().clear()
        super().extend(items)
        self._on_change = on_change if on_change is not None else old_on_change


BASE_REFERENCES: list[ReferenceGenome] = [
    ReferenceGenome(id="GRCh38_standard", aliases=["grch38", "hg38"], version="GRCh38", source="NCBI/UCSC", contig_style="chr", mitochondrial_contig="chrM", status="missing"),
    ReferenceGenome(id="GRCh38_chr20", aliases=["chr20", "hg38_chr20"], version="GRCh38-chr20", source="UCSC chr20 (synthetic test reference)", contig_style="chr", mitochondrial_contig="chrM", status="available"),
    ReferenceGenome(id="GRCh38_GIAB_masked_false_duplications", aliases=["grch38_giab_masked"], version="GRCh38+GIAB-mask", source="GIAB/NIST", contig_style="chr", mitochondrial_contig="chrM", status="missing"),
    ReferenceGenome(id="GRCh37_legacy", aliases=["grch37", "hg19"], version="GRCh37", source="NCBI/1000G", contig_style="numeric", mitochondrial_contig="MT", status="missing"),
    ReferenceGenome(id="T2T_CHM13v2_hs1", aliases=["t2t", "chm13"], version="T2T-v2", source="T2T Consortium / NHGRI", contig_style="chr", mitochondrial_contig="chrM", status="missing"),
    ReferenceGenome(id="mtDNA_rCRS", aliases=["rCRS"], version="NC_012920.1", source="NCBI", contig_style="chrM", mitochondrial_contig="chrM", status="missing"),
    ReferenceGenome(id="mtDNA_RSRS", aliases=["RSRS"], version="RSRS", source="Behar et al. 2012", contig_style="chrM", mitochondrial_contig="chrM", status="missing"),
    ReferenceGenome(id="hs38d1_decoy", aliases=["decoy", "hs38d1"], version="GRCh38+decoy", source="NCBI hs38d1", contig_style="chr", mitochondrial_contig="chrM", status="missing"),
]


projects: BackedList[Project] = BackedList([])
samples: BackedList[Sample] = BackedList([])
runs: BackedList[Run] = BackedList([])
run_events: BackedList[RunEvent] = BackedList([])
run_steps: BackedList[RunStep] = BackedList([])
run_logs: BackedList[RunLogLine] = BackedList([])
qc_summaries: BackedList[QCSummary] = BackedList([])
alignment_metrics: BackedList[AlignmentMetrics] = BackedList([])
coverage_metrics: BackedList[CoverageMetrics] = BackedList([])
reports: BackedList[ReportArtifact] = BackedList([])
interpretation_results: BackedList[InterpretationResult] = BackedList([])
variants: BackedList[VariantCall] = BackedList([])
structural_variants: BackedList[StructuralVariant] = BackedList([])
cnv_segments: BackedList[CNVSegment] = BackedList([])
mtdna_results: BackedList[MtDNAResult] = BackedList([])
prs_results: BackedList[PRSResult] = BackedList([])
taxonomy_hits: BackedList[TaxonomyHit] = BackedList([])
benchmark_records: BackedList[BenchmarkRecord] = BackedList([])
vendor_assembly_validations: BackedList[VendorAssemblyValidation] = BackedList([])
references: BackedList[ReferenceGenome] = BackedList(BASE_REFERENCES.copy())
_DB_ACTIVE = False


def _dump(model):
    return model.model_dump()


def _load_all(session, orm_cls, mdl_cls):
    return [mdl_cls.model_validate({c.name: getattr(row, c.name) for c in orm_cls.__table__.columns}) for row in session.query(orm_cls).all()]


def _merge_row(orm_cls, data: dict):
    """Production-friendly single-row upsert for entities with primary keys.

    This avoids the old delete-all/reinsert sync path for hot core writes.
    The in-memory BackedList remains the read-through cache for now.
    """
    if not USE_DB:
        return
    try:
        with SessionLocal() as session:
            session.merge(orm_cls(**data))
            session.commit()
    except SQLAlchemyError as exc:
        print(f"[memory_store] WARN: merge failed for {orm_cls.__tablename__}: {exc}")
        raise


def _delete_row(orm_cls, pk: str):
    if not USE_DB:
        return
    try:
        with SessionLocal() as session:
            obj = session.get(orm_cls, pk)
            if obj is not None:
                session.delete(obj)
                session.commit()
    except SQLAlchemyError as exc:
        print(f"[memory_store] WARN: delete failed for {orm_cls.__tablename__}:{pk}: {exc}")
        raise


def _delete_where(orm_cls, field_name: str, values: set[str]):
    if not values or not USE_DB:
        return
    try:
        with SessionLocal() as session:
            field = getattr(orm_cls, field_name)
            session.execute(delete(orm_cls).where(field.in_(values)))
            session.commit()
    except SQLAlchemyError as exc:
        print(f"[memory_store] WARN: bulk delete failed for {orm_cls.__tablename__}.{field_name}: {exc}")
        raise


def _bulk_merge_rows(orm_cls, rows: list[dict]):
    if not rows or not USE_DB:
        return
    try:
        with SessionLocal() as session:
            for row in rows:
                session.merge(orm_cls(**row))
            session.commit()
    except SQLAlchemyError as exc:
        print(f"[memory_store] WARN: bulk merge failed for {orm_cls.__tablename__}: {exc}")
        raise


def _replace_local(list_ref: BackedList, items: list):
    list_ref.replace_all(items, list_ref._on_change)


def _sync_table(list_ref: list, orm_cls, transform: Callable):
    if not _DB_ACTIVE or not USE_DB:
        return
    with SessionLocal() as session:
        # Temporarily disable FK triggers so delete-all-reinsert doesn't cascade
        is_pg = engine and hasattr(engine, 'url') and 'postgresql' in str(engine.url)
        if is_pg:
            session.execute(text("SET session_replication_role = 'replica'"))
        session.execute(delete(orm_cls))
        for item in list_ref:
            session.add(orm_cls(**transform(item)))
        if is_pg:
            session.execute(text("SET session_replication_role = 'origin'"))
        session.commit()


def _as_run_log_row(item: RunLogLine):
    data = _dump(item)
    data["id"] = f"log_{uuid4().hex[:12]}"
    return data


def _as_alignment_row(item: AlignmentMetrics):
    return {**_dump(item), "id": f"aln_{uuid4().hex[:12]}"}


def _as_coverage_row(item: CoverageMetrics):
    return {**_dump(item), "id": f"cov_{uuid4().hex[:12]}", "sample_id": item.sample_id, "reference_id": None}


def _as_qc_row(item: QCSummary):
    return {**_dump(item), "id": f"qc_{uuid4().hex[:12]}"}


def _init_lists_from_memory():
    for lst in (
        projects, samples, runs, run_events, run_steps, run_logs, qc_summaries,
        alignment_metrics, coverage_metrics, reports, interpretation_results, variants, structural_variants,
        cnv_segments, mtdna_results, prs_results, taxonomy_hits, benchmark_records,
        vendor_assembly_validations,
    ):
        lst.replace_all([], None)
    references.replace_all(BASE_REFERENCES.copy(), None)


def _mark_stale_running_runs():
    """After API restart, in-process pipeline workers are gone.

    Any DB run still marked running cannot continue in this process, so mark
    it interrupted and add a clear audit event/step instead of leaving the UI
    stuck forever. Runs paused from an active process are also stale after an
    API/container restart because the process handle is gone. Queued runs are
    preserved; they have not started work yet.
    """
    now = datetime.now(timezone.utc).isoformat()
    stale_ids: list[str] = []
    pause_state_keys = {
        "pause_previous_status",
        "pause_reason",
        "pause_mode",
        "pause_requested_at",
        "pause_requested_at_stage_boundary",
        "pause_requested_by",
        "pause_next_stage",
    }
    restart_safe_pause_reasons = {"stage_boundary_pause", "disk_pressure_before_markdup"}
    for run in runs:
        params = run.parameters or {}
        pause_previous_status = params.get("pause_previous_status")
        restart_safe_pause = run.status == "paused" and (
            params.get("pause_mode") == "stage_boundary"
            or params.get("pause_reason") in restart_safe_pause_reasons
        )
        if run.status == "running" or (
            run.status == "paused" and pause_previous_status == "running" and not restart_safe_pause
        ):
            run.status = "interrupted"
            run.parameters = {k: v for k, v in params.items() if k not in pause_state_keys}
            run.updated_at = now
            stale_ids.append(run.id)
            _merge_row(sm.Run, _dump(run))

    for run_id in stale_ids:
        evt = RunEvent(
            id=f"evt_{uuid4().hex[:10]}",
            run_id=run_id,
            event_type="pipeline_interrupted_on_startup",
            payload={"reason": "api_process_restarted", "previous_state": "running"},
        )
        run_events.append_local(evt)
        _merge_row(sm.RunEvent, _dump(evt))
        step = RunStep(
            id=f"stp_{uuid4().hex[:10]}",
            run_id=run_id,
            step_name="process_recovery",
            status="interrupted",
            progress_pct=0,
            last_log="API process restarted; in-process pipeline worker was interrupted.",
        )
        run_steps.append_local(step)
        _merge_row(sm.RunStep, _dump(step))


def _init_lists_from_db(*, recover_stale_running: bool = True):
    with SessionLocal() as session:
        # Load DB state into read-through caches without attaching table-wide write callbacks.
        # All durable writes should go through explicit row-level/batch helpers below.
        projects.replace_all(_load_all(session, sm.Project, Project), None)
        samples.replace_all(_load_all(session, sm.Sample, Sample), None)
        runs.replace_all(_load_all(session, sm.Run, Run), None)
        run_events.replace_all(_load_all(session, sm.RunEvent, RunEvent), None)
        run_steps.replace_all(_load_all(session, sm.RunStep, RunStep), None)
        run_logs.replace_all(_load_all(session, sm.RunLogLine, RunLogLine), None)
        qc_summaries.replace_all(_load_all(session, sm.QCSummary, QCSummary), None)
        alignment_metrics.replace_all(_load_all(session, sm.AlignmentMetric, AlignmentMetrics), None)
        coverage_metrics.replace_all(_load_all(session, sm.CoverageMetric, CoverageMetrics), None)
        reports.replace_all(_load_all(session, sm.ReportArtifact, ReportArtifact), None)
        interpretation_results.replace_all(_load_all(session, sm.InterpretationResult, InterpretationResult), None)
        variants.replace_all(_load_all(session, sm.VariantCall, VariantCall), None)
        structural_variants.replace_all(_load_all(session, sm.StructuralVariant, StructuralVariant), None)
        cnv_segments.replace_all(_load_all(session, sm.CNVSegment, CNVSegment), None)
        mtdna_results.replace_all(_load_all(session, sm.MtDNAResult, MtDNAResult), None)
        prs_results.replace_all(_load_all(session, sm.PRSResult, PRSResult), None)
        taxonomy_hits.replace_all(_load_all(session, sm.TaxonomyHit, TaxonomyHit), None)
        benchmark_records.replace_all(_load_all(session, sm.BenchmarkRecord, BenchmarkRecord), None)
        vendor_assembly_validations.replace_all(_load_all(session, sm.VendorAssemblyValidation, VendorAssemblyValidation), None)
        loaded_refs = _load_all(session, sm.ReferenceGenome, ReferenceGenome)
        if loaded_refs:
            # Merge: ensure all BASE_REFERENCES are present
            loaded_ids = {r.id for r in loaded_refs}
            for base in BASE_REFERENCES:
                if base.id not in loaded_ids:
                    session.add(sm.ReferenceGenome(**_dump(base)))
                    loaded_refs.append(base)
            session.commit()
        else:
            # First boot: persist BASE_REFERENCES to DB
            for base in BASE_REFERENCES:
                session.add(sm.ReferenceGenome(**_dump(base)))
            session.commit()
            loaded_refs = BASE_REFERENCES.copy()
        references.replace_all(loaded_refs, None)
    if recover_stale_running:
        _mark_stale_running_runs()


def refresh_from_db(*, recover_stale_running: bool = False) -> bool:
    """Refresh read-through caches from DB without re-running schema init.

    Used by API read endpoints while worker-owned jobs update run state in a
    separate process.
    """
    if not USE_DB:
        return False
    try:
        _init_lists_from_db(recover_stale_running=recover_stale_running)
        return True
    except Exception as exc:
        print(f"[memory_store] WARN: database refresh failed: {exc}")
        return False


def init_db(*, recover_stale_running: bool = True) -> bool:
    global _DB_ACTIVE
    if USE_DB:
        try:
            _DB_ACTIVE = False
            _sql_init_db()
            _DB_ACTIVE = True
            _init_lists_from_db(recover_stale_running=recover_stale_running)
            return True
        except Exception as exc:
            print(f"[memory_store] WARN: database init failed, using in-memory fallback: {exc}")
            _DB_ACTIVE = False
            _init_lists_from_memory()
            return False
    _DB_ACTIVE = False
    _init_lists_from_memory()
    return False


def get_projects(): return projects

def add_project(project: Project):
    projects.append_local(project)
    _merge_row(sm.Project, _dump(project))
    return project

def save_project(project: Project):
    for idx, existing in enumerate(projects):
        if existing.id == project.id:
            projects[idx] = project
            break
    else:
        projects.append_local(project)
    _merge_row(sm.Project, _dump(project))
    return project

def get_project(project_id: str): return next((p for p in projects if p.id == project_id), None)

def get_samples(): return samples

def add_sample(sample: Sample):
    samples.append_local(sample)
    _merge_row(sm.Sample, _dump(sample))
    return sample

def get_sample(sample_id: str): return next((s for s in samples if s.id == sample_id or s.sample_id == sample_id), None)

def get_runs(): return runs

def add_run(run: Run):
    runs.append_local(run)
    _merge_row(sm.Run, _dump(run))
    return run

def get_run(run_id: str): return next((r for r in runs if r.id == run_id), None)

def save_run(run: Run):
    _merge_row(sm.Run, _dump(run))
    return run

def update_run(run_id: str, **kwargs):
    run = get_run(run_id)
    if run:
        for k, v in kwargs.items():
            setattr(run, k, v)
        save_run(run)
    return run

def get_run_steps(run_id: str | None = None):
    return [s for s in run_steps if run_id is None or s.run_id == run_id]

def save_run_step(step: RunStep):
    _merge_row(sm.RunStep, _dump(step))
    return step

def add_run_step(step: RunStep):
    run_steps.append_local(step)
    save_run_step(step)
    return step

def get_run_events(run_id: str | None = None):
    return [e for e in run_events if run_id is None or e.run_id == run_id]

def add_run_event(event: RunEvent):
    run_events.append_local(event)
    _merge_row(sm.RunEvent, _dump(event))
    return event

def get_run_log_lines(run_id: str | None = None):
    return [l for l in run_logs if run_id is None or l.run_id == run_id]

def _run_log_row(log: RunLogLine):
    return {**_dump(log), "id": f"log_{uuid4().hex[:12]}"}

def add_run_log_line(log: RunLogLine):
    run_logs.append_local(log)
    _merge_row(sm.RunLogLine, _run_log_row(log))
    return log

def add_variant(item: VariantCall):
    variants.append_local(item)
    _merge_row(sm.VariantCall, _dump(item))
    return item

def add_variants(items: list[VariantCall]):
    for item in items:
        variants.append_local(item)
    _bulk_merge_rows(sm.VariantCall, [_dump(item) for item in items])
    return items

def get_variants(run_id: str | None = None): return [v for v in variants if run_id is None or v.run_id == run_id]

def _coverage_metric_row(item: CoverageMetrics):
    return {**_dump(item), "id": f"cov_{uuid4().hex[:12]}", "sample_id": item.sample_id, "reference_id": None}

def add_coverage_metric(item: CoverageMetrics):
    coverage_metrics.append_local(item)
    _merge_row(sm.CoverageMetric, _coverage_metric_row(item))
    return item

def get_coverage_metrics(run_id: str | None = None): return [m for m in coverage_metrics if run_id is None or m.run_id == run_id]

def _alignment_metric_row(item: AlignmentMetrics):
    return {**_dump(item), "id": f"aln_{uuid4().hex[:12]}"}

def add_alignment_metric(item: AlignmentMetrics):
    alignment_metrics.append_local(item)
    _merge_row(sm.AlignmentMetric, _alignment_metric_row(item))
    return item

def get_alignment_metrics(run_id: str | None = None): return [m for m in alignment_metrics if run_id is None or m.run_id == run_id]

def add_structural_variant(item: StructuralVariant):
    structural_variants.append_local(item)
    _merge_row(sm.StructuralVariant, _dump(item))
    return item

def add_structural_variants(items: list[StructuralVariant]):
    for item in items:
        structural_variants.append_local(item)
    _bulk_merge_rows(sm.StructuralVariant, [_dump(item) for item in items])
    return items

def get_structural_variants(run_id: str | None = None): return [m for m in structural_variants if run_id is None or m.run_id == run_id]

def add_cnv_segment(item: CNVSegment):
    cnv_segments.append_local(item)
    _merge_row(sm.CNVSegment, _dump(item))
    return item

def add_cnv_segments(items: list[CNVSegment]):
    for item in items:
        cnv_segments.append_local(item)
    _bulk_merge_rows(sm.CNVSegment, [_dump(item) for item in items])
    return items

def get_cnv_segments(run_id: str | None = None): return [m for m in cnv_segments if run_id is None or m.run_id == run_id]

def add_taxonomy_hit(item: TaxonomyHit):
    taxonomy_hits.append_local(item)
    _merge_row(sm.TaxonomyHit, _dump(item))
    return item

def add_taxonomy_hits(items: list[TaxonomyHit]):
    for item in items:
        taxonomy_hits.append_local(item)
    _bulk_merge_rows(sm.TaxonomyHit, [_dump(item) for item in items])
    return items

def get_taxonomy_hits(run_id: str | None = None): return [m for m in taxonomy_hits if run_id is None or m.run_id == run_id]

def add_mtdna_hit(item: MtDNAResult):
    mtdna_results.append_local(item)
    _merge_row(sm.MtDNAResult, _dump(item))
    return item

def add_mtdna_hits(items: list[MtDNAResult]):
    for item in items:
        mtdna_results.append_local(item)
    _bulk_merge_rows(sm.MtDNAResult, [_dump(item) for item in items])
    return items

def get_mtdna_hits(run_id: str | None = None): return [m for m in mtdna_results if run_id is None or m.run_id == run_id]

def add_prs_result(item: PRSResult):
    prs_results.append_local(item)
    _merge_row(sm.PRSResult, _dump(item))
    return item

def add_prs_results(items: list[PRSResult]):
    for item in items:
        prs_results.append_local(item)
    _bulk_merge_rows(sm.PRSResult, [_dump(item) for item in items])
    return items

def get_prs_results(run_id: str | None = None): return [m for m in prs_results if run_id is None or m.run_id == run_id]

def get_references(): return references

def add_reference(ref: ReferenceGenome):
    references.append_local(ref)
    _merge_row(sm.ReferenceGenome, _dump(ref))
    return ref

def save_reference(ref: ReferenceGenome):
    existing = get_reference(ref.id)
    if existing and existing is not ref:
        idx = references.index(existing)
        references[idx] = ref
    _merge_row(sm.ReferenceGenome, _dump(ref))
    return ref

def remove_reference(reference_id: str):
    ref = get_reference(reference_id)
    if ref:
        references.remove_local(ref)
        _delete_row(sm.ReferenceGenome, reference_id)
    return ref

def get_reference(reference_id: str): return next((r for r in references if r.id == reference_id), None)

def add_report(item: ReportArtifact):
    reports.append_local(item)
    _merge_row(sm.ReportArtifact, _dump(item))
    return item

def add_interpretation_result(item: InterpretationResult):
    interpretation_results.append_local(item)
    _merge_row(sm.InterpretationResult, _dump(item))
    return item

def add_interpretation_results(items: list[InterpretationResult]):
    for item in items:
        interpretation_results.append_local(item)
    _bulk_merge_rows(sm.InterpretationResult, [_dump(item) for item in items])
    return items

def get_interpretation_results(sample_id: str | None = None, run_id: str | None = None, module: str | None = None):
    return [
        item for item in interpretation_results
        if (sample_id is None or item.sample_id == sample_id)
        and (run_id is None or item.run_id == run_id)
        and (module is None or item.module == module)
    ]

def add_benchmark_record(item: BenchmarkRecord):
    benchmark_records.append_local(item)
    _merge_row(sm.BenchmarkRecord, _dump(item))
    return item

def add_benchmark_records(items: list[BenchmarkRecord]):
    for item in items:
        benchmark_records.append_local(item)
    _bulk_merge_rows(sm.BenchmarkRecord, [_dump(item) for item in items])
    return items

def add_vendor_assembly_validation(item: VendorAssemblyValidation):
    vendor_assembly_validations.append_local(item)
    _merge_row(sm.VendorAssemblyValidation, _dump(item))
    return item

def add_vendor_assembly_validations(items: list[VendorAssemblyValidation]):
    for item in items:
        vendor_assembly_validations.append_local(item)
    _bulk_merge_rows(sm.VendorAssemblyValidation, [_dump(item) for item in items])
    return items

def replace_qc_summary_for_run(run_id: str, item: QCSummary):
    idx = next((i for i, q in enumerate(qc_summaries) if q.run_id == run_id), None)
    if idx is not None:
        qc_summaries[idx] = item
    else:
        qc_summaries.append_local(item)
    _delete_where(sm.QCSummary, "run_id", {run_id})
    _merge_row(sm.QCSummary, {**_dump(item), "id": f"qc_{uuid4().hex[:12]}"})
    return item

def replace_alignment_metric_for_run(run_id: str, item: AlignmentMetrics):
    idx = next((i for i, a in enumerate(alignment_metrics) if a.run_id == run_id), None)
    if idx is not None:
        alignment_metrics[idx] = item
    else:
        alignment_metrics.append_local(item)
    _delete_where(sm.AlignmentMetric, "run_id", {run_id})
    _merge_row(sm.AlignmentMetric, _alignment_metric_row(item))
    return item

def replace_coverage_metric_for_run(run_id: str, item: CoverageMetrics):
    idx = next((i for i, c in enumerate(coverage_metrics) if c.run_id == run_id), None)
    if idx is not None:
        coverage_metrics[idx] = item
    else:
        coverage_metrics.append_local(item)
    _delete_where(sm.CoverageMetric, "run_id", {run_id})
    _merge_row(sm.CoverageMetric, _coverage_metric_row(item))
    return item

def delete_runs_by_project(project_id: str):
    _replace_local(runs, [r for r in runs if r.project_id != project_id])
    _delete_where(sm.Run, "project_id", {project_id})

def delete_samples_by_project(project_id: str):
    _replace_local(samples, [s for s in samples if s.project_id != project_id])
    _delete_where(sm.Sample, "project_id", {project_id})

def delete_variants_by_sample_ids(sample_ids: set[str]):
    variants[:] = [v for v in variants if v.sample_id not in sample_ids]
    _delete_where(sm.VariantCall, "sample_id", sample_ids)

def delete_structural_variants_by_sample_ids(sample_ids: set[str]):
    structural_variants[:] = [sv for sv in structural_variants if sv.sample_id not in sample_ids]
    _delete_where(sm.StructuralVariant, "sample_id", sample_ids)

def delete_cnv_segments_by_sample_ids(sample_ids: set[str]):
    cnv_segments[:] = [c for c in cnv_segments if c.sample_id not in sample_ids]
    _delete_where(sm.CNVSegment, "sample_id", sample_ids)

def delete_mtdna_hits_by_sample_ids(sample_ids: set[str]):
    mtdna_results[:] = [m for m in mtdna_results if m.sample_id not in sample_ids]
    _delete_where(sm.MtDNAResult, "sample_id", sample_ids)

def delete_prs_results_by_sample_ids(sample_ids: set[str]):
    prs_results[:] = [p for p in prs_results if p.sample_id not in sample_ids]
    _delete_where(sm.PRSResult, "sample_id", sample_ids)

def delete_taxonomy_hits_by_sample_ids(sample_ids: set[str]):
    taxonomy_hits[:] = [t for t in taxonomy_hits if t.sample_id not in sample_ids]
    _delete_where(sm.TaxonomyHit, "sample_id", sample_ids)

def delete_interpretation_results_by_sample_ids(sample_ids: set[str]):
    interpretation_results[:] = [r for r in interpretation_results if r.sample_id not in sample_ids]
    _delete_where(sm.InterpretationResult, "sample_id", sample_ids)

def delete_coverage_metrics_by_sample_ids(sample_ids: set[str]):
    coverage_metrics[:] = [c for c in coverage_metrics if c.sample_id not in sample_ids]
    _delete_where(sm.CoverageMetric, "sample_id", sample_ids)

def delete_alignment_metrics_by_sample_ids(sample_ids: set[str]):
    alignment_metrics[:] = [a for a in alignment_metrics if a.sample_id not in sample_ids]
    _delete_where(sm.AlignmentMetric, "sample_id", sample_ids)

def delete_run_events_by_run_ids(run_ids: set[str]):
    _replace_local(run_events, [e for e in run_events if e.run_id not in run_ids])
    _delete_where(sm.RunEvent, "run_id", run_ids)

def delete_run_logs_by_run_ids(run_ids: set[str]):
    _replace_local(run_logs, [l for l in run_logs if l.run_id not in run_ids])
    _delete_where(sm.RunLogLine, "run_id", run_ids)

def delete_run_steps_by_run_ids(run_ids: set[str]):
    _replace_local(run_steps, [s for s in run_steps if s.run_id not in run_ids])
    _delete_where(sm.RunStep, "run_id", run_ids)

def remove_project(project_id: str):
    project = get_project(project_id)
    if project:
        projects.remove_local(project)
        _delete_row(sm.Project, project_id)
    return project

def delete_variants_by_run(run_id: str):
    _replace_local(variants, [v for v in variants if v.run_id != run_id])
    _delete_where(sm.VariantCall, "run_id", {run_id})

def delete_structural_variants_by_run(run_id: str):
    _replace_local(structural_variants, [sv for sv in structural_variants if sv.run_id != run_id])
    _delete_where(sm.StructuralVariant, "run_id", {run_id})

def delete_cnv_segments_by_run(run_id: str):
    _replace_local(cnv_segments, [c for c in cnv_segments if c.run_id != run_id])
    _delete_where(sm.CNVSegment, "run_id", {run_id})

def delete_mtdna_hits_by_run(run_id: str):
    _replace_local(mtdna_results, [m for m in mtdna_results if m.run_id != run_id])
    _delete_where(sm.MtDNAResult, "run_id", {run_id})

def delete_prs_results_by_run(run_id: str):
    _replace_local(prs_results, [p for p in prs_results if p.run_id != run_id])
    _delete_where(sm.PRSResult, "run_id", {run_id})

def delete_taxonomy_hits_by_run(run_id: str):
    _replace_local(taxonomy_hits, [t for t in taxonomy_hits if t.run_id != run_id])
    _delete_where(sm.TaxonomyHit, "run_id", {run_id})

def delete_run_events_by_run(run_id: str):
    _replace_local(run_events, [e for e in run_events if e.run_id != run_id])
    _delete_where(sm.RunEvent, "run_id", {run_id})

def delete_run_logs_by_run(run_id: str):
    _replace_local(run_logs, [l for l in run_logs if l.run_id != run_id])
    _delete_where(sm.RunLogLine, "run_id", {run_id})

def delete_run_steps_by_run(run_id: str):
    _replace_local(run_steps, [s for s in run_steps if s.run_id != run_id])
    _delete_where(sm.RunStep, "run_id", {run_id})

def delete_qc_summaries_by_run(run_id: str):
    qc_summaries[:] = [q for q in qc_summaries if q.run_id != run_id]
    _delete_where(sm.QCSummary, "run_id", {run_id})

def delete_coverage_metrics_by_run(run_id: str):
    coverage_metrics[:] = [c for c in coverage_metrics if c.run_id != run_id]
    _delete_where(sm.CoverageMetric, "run_id", {run_id})

def delete_alignment_metrics_by_run(run_id: str):
    alignment_metrics[:] = [a for a in alignment_metrics if a.run_id != run_id]
    _delete_where(sm.AlignmentMetric, "run_id", {run_id})

def delete_reports_by_run(run_id: str):
    reports[:] = [r for r in reports if r.run_id != run_id]
    _delete_where(sm.ReportArtifact, "run_id", {run_id})

def delete_interpretation_results_by_run(run_id: str):
    interpretation_results[:] = [r for r in interpretation_results if r.run_id != run_id]
    _delete_where(sm.InterpretationResult, "run_id", {run_id})

def delete_reports_by_run_ids(run_ids: set[str]):
    _replace_local(reports, [r for r in reports if r.run_id not in run_ids])
    _delete_where(sm.ReportArtifact, "run_id", run_ids)

def delete_interpretation_results_by_run_ids(run_ids: set[str]):
    _replace_local(interpretation_results, [r for r in interpretation_results if r.run_id not in run_ids])
    _delete_where(sm.InterpretationResult, "run_id", run_ids)

def delete_qc_summaries_by_run_ids(run_ids: set[str]):
    _replace_local(qc_summaries, [q for q in qc_summaries if q.run_id not in run_ids])
    _delete_where(sm.QCSummary, "run_id", run_ids)

def delete_coverage_metrics_by_run_ids(run_ids: set[str]):
    _replace_local(coverage_metrics, [c for c in coverage_metrics if c.run_id not in run_ids])
    _delete_where(sm.CoverageMetric, "run_id", run_ids)

def delete_alignment_metrics_by_run_ids(run_ids: set[str]):
    _replace_local(alignment_metrics, [a for a in alignment_metrics if a.run_id not in run_ids])
    _delete_where(sm.AlignmentMetric, "run_id", run_ids)

def remove_run(run_id: str):
    run = get_run(run_id)
    if run:
        runs.remove_local(run)
        _delete_row(sm.Run, run_id)
    return run
