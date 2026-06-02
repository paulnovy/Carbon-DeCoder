import pytest
from fastapi import HTTPException

from app.routers.foundation import (
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    create_project,
    create_run_full,
    create_sample,
    list_project_runs,
    list_project_samples,
    list_sample_runs,
)
from app.store.memory_store import projects, run_events, run_logs, run_steps, runs, samples


def setup_function():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()


def test_project_inventory_lists_samples_and_runs():
    project = create_project(ProjectCreateRequest(name="Inventory demo"))
    sample = create_sample(
        project.id,
        SampleCreateRequest(sample_id="S1", reference_id="GRCh38_standard", r1_path="S1_R1.fastq.gz"),
    )
    run = create_run_full(
        project.id,
        RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"),
    )

    assert [item.id for item in list_project_samples(project.id)["items"]] == [sample.id]
    assert [item.id for item in list_project_runs(project.id)["items"]] == [run.id]
    assert [item.id for item in list_sample_runs(sample.id)["items"]] == [run.id]


def test_inventory_endpoints_return_404_for_missing_parents():
    with pytest.raises(HTTPException) as project_samples:
        list_project_samples("missing")
    assert project_samples.value.status_code == 404

    with pytest.raises(HTTPException) as project_runs:
        list_project_runs("missing")
    assert project_runs.value.status_code == 404

    with pytest.raises(HTTPException) as sample_runs:
        list_sample_runs("missing")
    assert sample_runs.value.status_code == 404
