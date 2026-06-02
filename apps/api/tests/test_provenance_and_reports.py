import json
from pathlib import Path

from app.routers.foundation import (
    ProjectCreateRequest,
    ReportCreateRequest,
    RunCreateRequest,
    RunProvenanceUpdateRequest,
    SampleCreateRequest,
    create_project,
    create_run_qc,
    create_run_report,
    create_sample,
    get_report,
    update_run_provenance,
)
from app.store.memory_store import projects, reports, run_events, run_logs, run_steps, runs, samples


def _reset_stores():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()
    reports.clear()


def test_provenance_update_and_report_creation_flow():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="P1"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S1", reference_id="GRCh38_standard"))
    run = create_run_qc(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    updated = update_run_provenance(
        run.id,
        RunProvenanceUpdateRequest(
            repo_commit="abc123",
            nextflow_version="24.10.0",
            pipeline_version="0.2.0",
            input_checksums={"r1": "deadbeef"},
        ),
    )
    assert updated.repo_commit == "abc123"
    assert updated.nextflow_version == "24.10.0"

    report = create_run_report(run.id, ReportCreateRequest(report_type="qc"))
    fetched = get_report(report.id)
    assert fetched.id == report.id
    assert fetched.report_type == "qc"
    assert fetched.status == "generated"
    payload = json.loads(Path(fetched.json_path).read_text())
    assert payload["_report"]["schema_version"] == "wgs.report.v1"
    assert any(event.event_type == "report.generated" and event.run_id == run.id for event in run_events)
