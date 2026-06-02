import pytest
from fastapi import HTTPException

from app.routers.foundation import (
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    create_project,
    create_run_full,
    create_sample,
    reference_compatibility,
)
from app.store.memory_store import projects, run_events, run_logs, run_steps, runs, samples


def _reset_stores():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()


def test_create_run_rejects_reference_lock_mismatch():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="P1"))
    sample = create_sample(
        project.id,
        SampleCreateRequest(sample_id="S1", reference_id="GRCh38_standard"),
    )

    with pytest.raises(HTTPException) as exc:
        create_run_full(
            project.id,
            RunCreateRequest(sample_id=sample.id, reference_id="GRCh37_legacy"),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "sample_reference_locked"


def test_create_run_rejects_contig_style_mismatch():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="P1"))
    sample = create_sample(
        project.id,
        SampleCreateRequest(sample_id="S1", reference_id="GRCh38_standard"),
    )

    with pytest.raises(HTTPException) as exc:
        create_run_full(
            project.id,
            RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard", contig_style="numeric"),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "reference_contig_style_mismatch"


def test_reference_compatibility_reports_mismatch_and_match():
    ok_payload = reference_compatibility("GRCh38_standard", "chr")
    bad_payload = reference_compatibility("GRCh38_standard", "numeric")

    assert ok_payload["compatible"] is True
    assert bad_payload["compatible"] is False
