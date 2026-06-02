from app.routers.foundation import (
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    create_project,
    create_run_full,
    create_sample,
    get_mtdna,
    get_prs,
)
from app.store.memory_store import (
    cnv_segments,
    mtdna_results,
    projects,
    prs_results,
    reports,
    run_events,
    run_logs,
    run_steps,
    runs,
    samples,
    structural_variants,
    variants,
)


def _reset_stores():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()
    reports.clear()
    variants.clear()
    structural_variants.clear()
    cnv_segments.clear()
    mtdna_results.clear()
    prs_results.clear()


def test_mtdna_and_prs_endpoints_start_empty_until_real_stage_imports():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pmtdna"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_mito", reference_id="GRCh38_standard"))
    _ = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    mtdna = get_mtdna("S_mito")
    prs = get_prs("S_mito")

    assert mtdna["count"] == 0
    assert prs["count"] == 0
    assert mtdna["non_diagnostic"] is True
    assert prs["non_diagnostic"] is True
