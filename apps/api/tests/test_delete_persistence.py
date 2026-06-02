"""
Tests proving that delete operations actually persist to the database,
not just clear in-memory lists. Prevents regression of the zombie-data bug.

Uses its own SQLite in-memory engine, patched into memory_store for each test.
Does NOT use autouse to avoid contaminating other test modules.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db import sql_models as sm
from app.store import memory_store


@pytest.fixture
def db_engine():
    """Create a fresh SQLite in-memory engine with all tables."""
    eng = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture
def db_session(db_engine):
    """Patch memory_store to use our SQLite engine, yield (engine, SessionLocal), restore."""
    SL = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    # Save originals
    orig_engine = memory_store.engine
    orig_SL = memory_store.SessionLocal
    orig_use = memory_store.USE_DB
    orig_active = memory_store._DB_ACTIVE

    # Patch
    memory_store.engine = db_engine
    memory_store.SessionLocal = SL
    memory_store.USE_DB = True
    memory_store._DB_ACTIVE = True

    # Clear all in-memory lists
    _clear_test_lists()

    yield db_engine, SL

    # Restore
    _clear_test_lists()
    memory_store.engine = orig_engine
    memory_store.SessionLocal = orig_SL
    memory_store.USE_DB = orig_use
    memory_store._DB_ACTIVE = orig_active


def _clear_test_lists():
    """Clear data lists but NOT references (built-in refs must survive)."""
    for lst in [
        memory_store.projects, memory_store.samples, memory_store.runs,
        memory_store.variants, memory_store.structural_variants,
        memory_store.cnv_segments, memory_store.mtdna_results,
        memory_store.prs_results, memory_store.taxonomy_hits,
        memory_store.coverage_metrics, memory_store.alignment_metrics,
        memory_store.qc_summaries, memory_store.run_events,
        memory_store.run_steps, memory_store.run_logs, memory_store.reports,
        memory_store.interpretation_results,
        memory_store.benchmark_records,
        memory_store.vendor_assembly_validations,
    ]:
        lst.clear()


def _count(SL, orm_cls, **filters):
    with SL() as session:
        q = session.query(orm_cls)
        for field, value in filters.items():
            q = q.filter(getattr(orm_cls, field) == value)
        return q.count()


def _seed():
    """Insert project + sample + run + variant + SV + CNV via memory_store."""
    from app.db.models import Project, Sample, Run, VariantCall, StructuralVariant, CNVSegment, TaxonomyHit
    now = "2026-05-08T20:00:00+00:00"

    memory_store.add_project(Project(id="p1", name="P1", description="", created_at=now))
    memory_store.add_sample(Sample(id="s1", project_id="p1", sample_id="smp_001", reference_id="GRCh38_standard", created_at=now))
    memory_store.add_run(Run(id="r1", project_id="p1", sample_id="s1", mode="full", status="done", reference_id="GRCh38_standard", created_at=now))
    memory_store.add_variant(VariantCall(id="v1", run_id="r1", sample_id="smp_001", reference_id="GRCh38_standard", chrom="chr1", pos=1000, ref="A", alt="G"))
    memory_store.add_structural_variant(StructuralVariant(id="sv1", run_id="r1", sample_id="smp_001", reference_id="GRCh38_standard", chrom="chr1", start=5000, end=6000, sv_type="DEL", size_bp=1000))
    memory_store.add_cnv_segment(CNVSegment(id="cnv1", run_id="r1", sample_id="smp_001", reference_id="GRCh38_standard", chrom="chr1", start=10000, end=20000, copy_number=1.0, cnv_type="del", method="CNVkit"))
    memory_store.add_taxonomy_hit(
        TaxonomyHit(
            id="tax1",
            run_id="r1",
            sample_id="smp_001",
            reference_id="GRCh38_standard",
            organism="Rothia dentocariosa",
            kingdom="Bacteria",
            read_count=175748,
            confidence=0.9,
            evidence_score=0.8,
            tools=["kraken2"],
        )
    )


# ── delete_*_by_run ──

def test_delete_variants_by_run(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.VariantCall, run_id="r1") == 1
    memory_store.delete_variants_by_run("r1")
    assert _count(SL, sm.VariantCall, run_id="r1") == 0
    assert not any(v.run_id == "r1" for v in memory_store.variants)


def test_save_run_persists_when_db_active_flag_is_stale(db_session):
    """A stale inactive flag must not make API writes look successful but vanish.

    The live API can still read from Postgres via refresh_from_db even when a
    worker/process-local active flag is stale. In that state, write helpers must
    keep writing to DB instead of returning a false in-memory-only success.
    """
    _, SL = db_session
    _seed()
    run = memory_store.get_run("r1")
    run.status = "running"
    run.parameters = {"stage_options": {"taxonomy_database": "standard"}}

    memory_store._DB_ACTIVE = False
    memory_store.save_run(run)

    with SL() as session:
        stored = session.get(sm.Run, "r1")
        assert stored.status == "running"
        assert stored.parameters["stage_options"]["taxonomy_database"] == "standard"


def test_delete_sv_by_run(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.StructuralVariant, run_id="r1") == 1
    memory_store.delete_structural_variants_by_run("r1")
    assert _count(SL, sm.StructuralVariant, run_id="r1") == 0


def test_delete_cnv_by_run(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.CNVSegment, run_id="r1") == 1
    memory_store.delete_cnv_segments_by_run("r1")
    assert _count(SL, sm.CNVSegment, run_id="r1") == 0


def test_taxonomy_hit_persists_and_reloads(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.TaxonomyHit, run_id="r1") == 1

    memory_store.taxonomy_hits.clear()
    memory_store.refresh_from_db(recover_stale_running=False)

    assert any(hit.run_id == "r1" and hit.organism == "Rothia dentocariosa" for hit in memory_store.taxonomy_hits)


def test_delete_taxonomy_by_run(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.TaxonomyHit, run_id="r1") == 1
    memory_store.delete_taxonomy_hits_by_run("r1")
    assert _count(SL, sm.TaxonomyHit, run_id="r1") == 0
    assert not any(hit.run_id == "r1" for hit in memory_store.taxonomy_hits)


def test_remove_run(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.Run, id="r1") == 1
    memory_store.remove_run("r1")
    assert _count(SL, sm.Run, id="r1") == 0


def test_cancel_running_run_persists_status_and_events(db_session):
    _, SL = db_session
    from app.db.models import Project, Run, Sample
    from app.routers import foundation

    now = "2026-05-24T05:30:00+00:00"
    memory_store.add_project(Project(id="p_cancel", name="Cancel P", description="", created_at=now))
    memory_store.add_sample(
        Sample(id="s_cancel", project_id="p_cancel", sample_id="S_CANCEL", reference_id="GRCh38_standard", created_at=now)
    )
    memory_store.add_run(
        Run(id="r_cancel", project_id="p_cancel", sample_id="s_cancel", mode="full", status="running", reference_id="GRCh38_standard", created_at=now)
    )
    foundation._ACTIVE_PROCESSES.pop("r_cancel", None)
    foundation._CANCEL_FLAGS.pop("r_cancel", None)
    foundation._PAUSE_FLAGS.pop("r_cancel", None)

    result = foundation.cancel_run("r_cancel")

    assert result["run_status"] == "cancelled"
    with SL() as session:
        db_run = session.query(sm.Run).filter(sm.Run.id == "r_cancel").one()
        events = session.query(sm.RunEvent).filter(sm.RunEvent.run_id == "r_cancel").all()
    assert db_run.status == "cancelled"
    assert {event.event_type for event in events} >= {"pipeline_cancel_requested", "pipeline_cancelled"}


# ── delete_*_by_sample_ids (the original zombie bug) ──

def test_delete_variants_by_sample_ids(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.VariantCall, sample_id="smp_001") == 1
    memory_store.delete_variants_by_sample_ids({"smp_001"})
    assert _count(SL, sm.VariantCall, sample_id="smp_001") == 0


def test_delete_sv_by_sample_ids(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.StructuralVariant, sample_id="smp_001") == 1
    memory_store.delete_structural_variants_by_sample_ids({"smp_001"})
    assert _count(SL, sm.StructuralVariant, sample_id="smp_001") == 0


def test_delete_cnv_by_sample_ids(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.CNVSegment, sample_id="smp_001") == 1
    memory_store.delete_cnv_segments_by_sample_ids({"smp_001"})
    assert _count(SL, sm.CNVSegment, sample_id="smp_001") == 0


def test_delete_taxonomy_by_sample_ids(db_session):
    _, SL = db_session
    _seed()
    assert _count(SL, sm.TaxonomyHit, sample_id="smp_001") == 1
    memory_store.delete_taxonomy_hits_by_sample_ids({"smp_001"})
    assert _count(SL, sm.TaxonomyHit, sample_id="smp_001") == 0


# ── Zombie scenario: delete then simulate restart ──

def test_zombie_data_does_not_return(db_session):
    _, SL = db_session
    _seed()

    memory_store.delete_variants_by_sample_ids({"smp_001"})
    memory_store.delete_structural_variants_by_sample_ids({"smp_001"})
    memory_store.delete_cnv_segments_by_sample_ids({"smp_001"})
    memory_store.delete_taxonomy_hits_by_sample_ids({"smp_001"})

    # Verify gone from DB
    assert _count(SL, sm.VariantCall, sample_id="smp_001") == 0
    assert _count(SL, sm.StructuralVariant, sample_id="smp_001") == 0
    assert _count(SL, sm.CNVSegment, sample_id="smp_001") == 0
    assert _count(SL, sm.TaxonomyHit, sample_id="smp_001") == 0

    # Simulate restart: reload from DB
    with SL() as session:
        assert session.query(sm.VariantCall).count() == 0, "ZOMBIE: variants returned!"
        assert session.query(sm.StructuralVariant).count() == 0, "ZOMBIE: SVs returned!"
        assert session.query(sm.CNVSegment).count() == 0, "ZOMBIE: CNVs returned!"
        assert session.query(sm.TaxonomyHit).count() == 0, "ZOMBIE: taxonomy hits returned!"


def test_delete_project_full_cascade(db_session):
    _, SL = db_session
    _seed()

    assert _count(SL, sm.Project, id="p1") == 1
    assert _count(SL, sm.Run, project_id="p1") == 1
    assert _count(SL, sm.VariantCall, run_id="r1") == 1
    assert _count(SL, sm.TaxonomyHit, run_id="r1") == 1

    run_ids = {r.id for r in memory_store.runs if r.project_id == "p1"}
    sample_ids = {s.sample_id for s in memory_store.samples if s.project_id == "p1"}

    memory_store.delete_runs_by_project("p1")
    memory_store.delete_samples_by_project("p1")
    memory_store.delete_variants_by_sample_ids(sample_ids)
    memory_store.delete_structural_variants_by_sample_ids(sample_ids)
    memory_store.delete_cnv_segments_by_sample_ids(sample_ids)
    memory_store.delete_taxonomy_hits_by_sample_ids(sample_ids)
    memory_store.delete_run_events_by_run_ids(run_ids)
    memory_store.delete_run_logs_by_run_ids(run_ids)
    memory_store.delete_run_steps_by_run_ids(run_ids)
    memory_store.delete_qc_summaries_by_run_ids(run_ids)
    memory_store.delete_coverage_metrics_by_run_ids(run_ids)
    memory_store.delete_alignment_metrics_by_run_ids(run_ids)
    memory_store.delete_reports_by_run_ids(run_ids)
    memory_store.remove_project("p1")

    assert _count(SL, sm.Project, id="p1") == 0
    assert _count(SL, sm.Sample, project_id="p1") == 0
    assert _count(SL, sm.Run, project_id="p1") == 0
    assert _count(SL, sm.VariantCall, run_id="r1") == 0
    assert _count(SL, sm.StructuralVariant, run_id="r1") == 0
    assert _count(SL, sm.CNVSegment, run_id="r1") == 0
    assert _count(SL, sm.TaxonomyHit, run_id="r1") == 0
