from pathlib import Path

from app.routers.foundation import (
    ProjectCreateRequest,
    QcImportRequest,
    RunCreateRequest,
    SampleCreateRequest,
    create_project,
    create_run_qc,
    create_sample,
    get_run_steps,
    import_qc_artifacts,
)
from app.store.memory_store import projects, qc_summaries, run_events, run_logs, run_steps, runs, samples


def _reset_stores():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()
    qc_summaries.clear()


def test_run_qc_flow_adds_steps_and_imports_qc(tmp_path: Path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="P1"))
    sample = create_sample(
        project.id,
        SampleCreateRequest(sample_id="S1", reference_id="GRCh38_standard"),
    )

    run = create_run_qc(
        project.id,
        RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"),
    )

    steps_payload = get_run_steps(run.id)
    assert len(steps_payload["items"]) >= 4

    fastqc = tmp_path / "fastqc_data.txt"
    fastqc.write_text("Total Sequences\t100\n%GC\t45\n", encoding="utf-8")

    qc = import_qc_artifacts(run.id, QcImportRequest(fastqc_data_txt=str(fastqc)))
    assert qc.total_reads == 100
    assert qc.gc_content_pct == 45.0
