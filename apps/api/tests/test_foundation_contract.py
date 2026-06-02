from fastapi.responses import StreamingResponse
import pytest

from app.db.models import Project, Run, Sample
from app.routers import foundation
from app.routers.foundation import (
    PauseRunRequest,
    PipelineStartRequest,
    cancel_run,
    delete_project,
    delete_run,
    events_stream,
    get_pipeline_settings,
    get_run_fast_clinvar_screen,
    get_run_multiqc,
    pause_run,
    resume_run,
    start_pipeline,
    version,
)


def test_version_contract_shape():
    payload = version()
    assert "version" in payload
    assert "service" in payload
    assert payload["database_schema"]["schema_key"] == "wgs_cockpit"


def test_events_stream_is_sse_response():
    resp = events_stream()
    assert isinstance(resp, StreamingResponse)


def test_multiqc_endpoint_reports_missing_without_placeholder(monkeypatch):
    run = Run(
        id="run_multiqc_missing",
        project_id="project_1",
        sample_id="sample_1",
        mode="qc-only",
        status="done",
        reference_id="GRCh38_standard",
    )
    monkeypatch.setattr(foundation, "runs", [run])

    payload = get_run_multiqc(run.id)

    assert payload["status"] == "missing"
    assert payload["report_path"] is None
    assert "No MultiQC report artifact" in payload["note"]


def test_fast_clinvar_screen_reads_run_artifacts(monkeypatch, tmp_path):
    run = Run(
        id="run_fastclinvar_1",
        project_id="project_1",
        sample_id="sample_1",
        mode="full",
        status="failed",
        reference_id="GRCh38_standard",
    )
    artifact_dir = tmp_path / run.id / "clinvar_fast_screen"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "clinvar.plp.highconf.targets.tsv").write_text("chrom\tpos\tref\talt\nchr1\t10\tA\tG\nchr1\t20\tC\tT\n", encoding="utf-8")
    (artifact_dir / "fast_screen.highconf.calls.tsv").write_text("chrom\tpos\tid\tref\talt\nchr1\t10\t.\tA\tG\n", encoding="utf-8")
    (artifact_dir / "fast_screen.highconf.report.tsv").write_text("chrom\tpos\tref\talt\tgt\tdp\tgene\tclinical_significance\nchr1\t10\tA\tG\t0/1\t32\tGENE1\tPathogenic\n", encoding="utf-8")
    (artifact_dir / "fast_screen.highconf.log").write_text("START\nDONE\n", encoding="utf-8")
    monkeypatch.setattr(foundation, "runs", [run])
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", tmp_path)

    payload = get_run_fast_clinvar_screen(run.id)

    assert payload["status"] == "matches_found"
    assert payload["target_count"] == 2
    assert payload["raw_call_count"] == 1
    assert payload["exact_match_count"] == 1
    assert payload["matches"][0]["gene"] == "GENE1"


def test_fast_clinvar_screen_reports_missing_artifact(monkeypatch, tmp_path):
    run = Run(
        id="run_fastclinvar_missing",
        project_id="project_1",
        sample_id="sample_1",
        mode="full",
        status="failed",
        reference_id="GRCh38_standard",
    )
    monkeypatch.setattr(foundation, "runs", [run])
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", tmp_path)

    payload = get_run_fast_clinvar_screen(run.id)

    assert payload["status"] == "missing"
    assert payload["exact_match_count"] == 0
    assert payload["artifacts"]["directory"] is None


def test_pipeline_settings_exposes_executor_default_decision(monkeypatch):
    monkeypatch.delenv(foundation.PIPELINE_EXECUTOR_ENV, raising=False)

    payload = get_pipeline_settings()
    policy = payload["executor_policy"]

    assert policy["effective_executor"] == "api_thread"
    assert policy["default_executor"] == "api_thread"
    assert policy["worker_queue_available"] is True
    assert policy["worker_queue_default_blocked"] is True
    assert "real long-running WGS alignment" in policy["default_decision"]
    assert payload["resource_plan"]["executor_policy"]["effective_executor"] == "api_thread"


def _seed_contract_run(monkeypatch, status="running"):
    run = Run(
        id="run_pause_1",
        project_id="project_1",
        sample_id="sample_1",
        mode="full",
        status=status,
        reference_id="GRCh38_standard",
    )
    monkeypatch.setattr(foundation, "runs", [run])
    monkeypatch.setattr(foundation, "save_run", lambda run: run)
    monkeypatch.setattr(foundation, "_emit_run_event", lambda *args, **kwargs: None)
    foundation._PAUSE_FLAGS.clear()
    foundation._CANCEL_FLAGS.clear()
    foundation._ACTIVE_PROCESSES.clear()
    foundation._ACTIVE_RUNNERS.clear()
    return run


class _FakeActiveProcess:
    pid = 4242

    def poll(self):
        return None


def test_pause_and_resume_queued_run_preserves_progress_state(monkeypatch):
    run = _seed_contract_run(monkeypatch, status="queued")

    paused = pause_run(run.id)

    assert paused["status"] == "paused"
    assert paused["mode"] == "queued"
    assert run.status == "paused"
    assert run.parameters["pause_previous_status"] == "queued"

    resumed = resume_run(run.id)

    assert resumed["status"] == "resumed"
    assert run.status == "queued"
    assert "pause_previous_status" not in run.parameters
    assert run.id not in foundation._PAUSE_FLAGS


def test_stage_boundary_pause_does_not_suspend_active_process(monkeypatch):
    run = _seed_contract_run(monkeypatch, status="running")
    foundation._ACTIVE_PROCESSES[run.id] = _FakeActiveProcess()

    def fail_if_signalled(*_args, **_kwargs):
        raise AssertionError("stage-boundary pause must not SIGSTOP the active process")

    monkeypatch.setattr(foundation.os, "killpg", fail_if_signalled)

    paused = pause_run(run.id, PauseRunRequest(mode="stage_boundary"))

    assert paused["status"] == "pause_requested"
    assert paused["mode"] == "stage_boundary"
    assert run.status == "running"
    assert run.id not in foundation._PAUSE_FLAGS
    assert run.parameters["pause_requested_at_stage_boundary"] is True
    assert run.parameters["pause_mode"] == "stage_boundary"
    assert run.parameters["pause_previous_status"] == "running"


def test_resume_running_stage_boundary_pause_request_clears_request(monkeypatch):
    run = _seed_contract_run(monkeypatch, status="running")
    run.parameters.update(
        {
            "pause_previous_status": "running",
            "pause_reason": "stage_boundary_pause",
            "pause_mode": "stage_boundary",
            "pause_requested_at_stage_boundary": True,
            "pause_requested_at": "2026-05-24T01:00:00+00:00",
        }
    )

    resumed = resume_run(run.id)

    assert resumed["status"] == "pause_request_cleared"
    assert run.status == "running"
    assert "pause_requested_at_stage_boundary" not in run.parameters
    assert "pause_previous_status" not in run.parameters


def test_resume_stage_boundary_pause_with_live_runner_does_not_dispatch_duplicate(monkeypatch):
    run = _seed_contract_run(monkeypatch, status="paused")
    run.parameters.update(
        {
            "pause_previous_status": "running",
            "pause_reason": "stage_boundary_pause",
            "pause_mode": "stage_boundary",
            "pause_next_stage": "coverage",
        }
    )
    foundation._ACTIVE_RUNNERS[run.id] = True

    def fail_dispatch(*_args, **_kwargs):
        raise AssertionError("live parked runner should resume itself")

    monkeypatch.setattr(foundation, "_dispatch_pipeline_job", fail_dispatch)

    resumed = resume_run(run.id)

    assert resumed["status"] == "resumed"
    assert resumed["mode"] == "stage_boundary"
    assert run.status == "running"
    assert "pause_next_stage" not in run.parameters


def test_resume_stage_boundary_after_restart_dispatches_from_next_stage(monkeypatch):
    run = _seed_contract_run(monkeypatch, status="paused")
    run.parameters.update(
        {
            "pause_previous_status": "running",
            "pause_reason": "stage_boundary_pause",
            "pause_mode": "stage_boundary",
            "pause_next_stage": "coverage",
            "stages": ["alignment", "coverage", "variants"],
            "required_stages": ["alignment", "coverage", "variants"],
            "input_files": ["reads_R1.fastq.gz", "reads_R2.fastq.gz"],
            "stage_plan": {"final_stages": ["alignment", "coverage", "variants"]},
        }
    )
    sample = Sample(
        id="sample_1",
        project_id="project_1",
        sample_id="S1",
        reference_id="GRCh38_standard",
        r1_path="reads_R1.fastq.gz",
        r2_path="reads_R2.fastq.gz",
    )
    dispatched = []
    monkeypatch.setattr(foundation, "samples", [sample])
    monkeypatch.setattr(foundation, "_pipeline_executor", lambda: foundation.PIPELINE_EXECUTOR_API_THREAD)
    monkeypatch.setattr(foundation, "_dispatch_pipeline_job", lambda job: dispatched.append(job))

    resumed = resume_run(run.id)

    assert resumed["status"] == "resumed"
    assert resumed["mode"] == "stage_boundary_checkpoint"
    assert run.status == "running"
    assert dispatched
    assert dispatched[0].stages == ["coverage", "variants"]
    assert dispatched[0].required_stages == ["coverage", "variants"]
    assert run.parameters["stages"] == ["coverage", "variants"]


def test_cancel_paused_run_clears_pause_flag(monkeypatch):
    run = _seed_contract_run(monkeypatch, status="paused")
    foundation._PAUSE_FLAGS[run.id] = True

    cancelled = cancel_run(run.id)

    assert cancelled["status"] == "cancel_requested"
    assert run.status == "cancelled"
    assert run.id not in foundation._PAUSE_FLAGS
    assert run.id not in foundation._CANCEL_FLAGS


def test_cancel_run_paused_while_queued_finishes_immediately(monkeypatch):
    run = _seed_contract_run(monkeypatch, status="paused")
    run.parameters["pause_previous_status"] = "queued"
    foundation._PAUSE_FLAGS[run.id] = True

    cancelled = cancel_run(run.id)

    assert cancelled["status"] == "cancel_requested"
    assert run.status == "cancelled"
    assert "pause_previous_status" not in run.parameters
    assert run.id not in foundation._PAUSE_FLAGS
    assert run.id not in foundation._CANCEL_FLAGS


def test_resume_paused_running_without_active_process_marks_interrupted(monkeypatch):
    run = _seed_contract_run(monkeypatch, status="paused")
    run.parameters["pause_previous_status"] = "running"
    foundation._PAUSE_FLAGS[run.id] = True

    with pytest.raises(foundation.HTTPException) as exc:
        resume_run(run.id)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "active_process_missing_after_restart"
    assert run.status == "interrupted"
    assert "pause_previous_status" not in run.parameters
    assert run.id not in foundation._PAUSE_FLAGS


def test_cleanup_run_temp_storage_dry_run_and_delete(monkeypatch, tmp_path):
    run = Run(
        id="run_temp_cleanup",
        project_id="project_1",
        sample_id="sample_1",
        mode="full",
        status="interrupted",
        reference_id="GRCh38_standard",
    )
    sample = Sample(
        id="sample_1",
        project_id="project_1",
        sample_id="S1",
        reference_id="GRCh38_standard",
    )
    output_dir = tmp_path / "results" / run.id
    output_dir.mkdir(parents=True)
    temp_file = output_dir / "S1.name_sorted.bam.tmp.0000.bam"
    temp_file.write_bytes(b"x" * 10)
    keep_file = output_dir / "S1.sorted.markdup.bam"
    keep_file.write_bytes(b"keep")
    monkeypatch.setattr(foundation, "runs", [run])
    monkeypatch.setattr(foundation, "samples", [sample])
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(foundation, "_emit_run_event", lambda *args, **kwargs: None)

    dry = foundation.cleanup_run_temp_storage(run.id, dry_run=True)

    assert dry["deleted_count"] == 0
    assert dry["total_size_bytes"] == 10
    assert temp_file.exists()

    deleted = foundation.cleanup_run_temp_storage(run.id, dry_run=False)

    assert deleted["deleted_count"] == 1
    assert not temp_file.exists()
    assert keep_file.exists()


def test_cleanup_orphan_results_only_deletes_unknown_run_dirs(monkeypatch, tmp_path):
    known = Run(
        id="run_known",
        project_id="project_1",
        sample_id="sample_1",
        mode="full",
        status="done",
        reference_id="GRCh38_standard",
    )
    root = tmp_path / "results"
    known_dir = root / known.id
    orphan_dir = root / "run_orphan"
    other_dir = root / "reports"
    known_dir.mkdir(parents=True)
    orphan_dir.mkdir()
    other_dir.mkdir()
    (known_dir / "keep.txt").write_text("keep", encoding="utf-8")
    (orphan_dir / "delete.txt").write_text("delete", encoding="utf-8")
    (other_dir / "keep.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(foundation, "runs", [known])
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", root)

    dry = foundation.cleanup_orphan_results(dry_run=True)

    assert dry["deleted_count"] == 0
    assert dry["total_size_bytes"] == len("delete")
    assert orphan_dir.exists()

    deleted = foundation.cleanup_orphan_results(dry_run=False)

    assert deleted["deleted_count"] == 1
    assert not orphan_dir.exists()
    assert known_dir.exists()
    assert other_dir.exists()


def _stub_delete_dependencies(monkeypatch):
    for name in (
        "delete_runs_by_project",
        "delete_samples_by_project",
        "delete_variants_by_sample_ids",
        "delete_structural_variants_by_sample_ids",
        "delete_cnv_segments_by_sample_ids",
        "delete_mtdna_hits_by_sample_ids",
        "delete_prs_results_by_sample_ids",
        "delete_taxonomy_hits_by_sample_ids",
        "delete_interpretation_results_by_sample_ids",
        "delete_coverage_metrics_by_sample_ids",
        "delete_alignment_metrics_by_sample_ids",
        "delete_run_events_by_run_ids",
        "delete_run_logs_by_run_ids",
        "delete_run_steps_by_run_ids",
        "delete_qc_summaries_by_run_ids",
        "delete_coverage_metrics_by_run_ids",
        "delete_alignment_metrics_by_run_ids",
        "delete_reports_by_run_ids",
        "delete_interpretation_results_by_run_ids",
        "delete_variants_by_run",
        "delete_structural_variants_by_run",
        "delete_cnv_segments_by_run",
        "delete_mtdna_hits_by_run",
        "delete_prs_results_by_run",
        "delete_taxonomy_hits_by_run",
        "delete_interpretation_results_by_run",
        "delete_run_events_by_run",
        "delete_run_logs_by_run",
        "delete_run_steps_by_run",
        "delete_qc_summaries_by_run",
        "delete_coverage_metrics_by_run",
        "delete_alignment_metrics_by_run",
        "delete_reports_by_run",
    ):
        monkeypatch.setattr(foundation, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(foundation, "remove_project", lambda project_id: None)
    monkeypatch.setattr(foundation, "remove_run", lambda run_id: None)


def test_delete_run_removes_result_directory(monkeypatch, tmp_path):
    run = Run(
        id="run_delete_me",
        project_id="project_1",
        sample_id="sample_1",
        mode="full",
        status="failed",
        reference_id="GRCh38_standard",
    )
    result_dir = tmp_path / "results" / run.id
    result_dir.mkdir(parents=True)
    (result_dir / "large.tmp").write_bytes(b"x" * 11)
    monkeypatch.setattr(foundation, "runs", [run])
    monkeypatch.setattr(foundation, "samples", [])
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", tmp_path / "results")
    _stub_delete_dependencies(monkeypatch)

    deleted = delete_run(run.id)

    assert deleted["deleted"] == run.id
    assert deleted["deleted_result_dirs"][0]["size_bytes"] == 11
    assert not result_dir.exists()


def test_delete_project_removes_result_directories_and_blocks_active(monkeypatch, tmp_path):
    project = Project(id="project_1", name="Project")
    done_run = Run(
        id="run_done",
        project_id=project.id,
        sample_id="sample_1",
        mode="full",
        status="failed",
        reference_id="GRCh38_standard",
    )
    active_run = Run(
        id="run_active",
        project_id=project.id,
        sample_id="sample_1",
        mode="full",
        status="running",
        reference_id="GRCh38_standard",
    )
    result_root = tmp_path / "results"
    done_dir = result_root / done_run.id
    active_dir = result_root / active_run.id
    done_dir.mkdir(parents=True)
    active_dir.mkdir()
    (done_dir / "delete.txt").write_text("delete", encoding="utf-8")
    (active_dir / "keep.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(foundation, "projects", [project])
    monkeypatch.setattr(foundation, "runs", [done_run, active_run])
    monkeypatch.setattr(foundation, "samples", [])
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", result_root)
    _stub_delete_dependencies(monkeypatch)

    with pytest.raises(foundation.HTTPException) as exc:
        delete_project(project.id)

    assert exc.value.status_code == 409
    assert done_dir.exists()
    assert active_dir.exists()

    monkeypatch.setattr(foundation, "runs", [done_run])
    deleted = delete_project(project.id)

    assert deleted["deleted"] == project.id
    assert not done_dir.exists()
    assert active_dir.exists()


def test_resume_existing_blocks_when_alignment_checkpoint_is_missing(monkeypatch, tmp_path):
    r1 = tmp_path / "reads_R1.fastq.gz"
    r2 = tmp_path / "reads_R2.fastq.gz"
    r1.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")
    r2.write_text("@r1\nTGCA\n+\n!!!!\n", encoding="utf-8")
    run = Run(
        id="run_no_checkpoint",
        project_id="project_1",
        sample_id="sample_1",
        mode="full",
        status="failed",
        reference_id="GRCh38_standard",
    )
    sample = Sample(
        id="sample_1",
        project_id="project_1",
        sample_id="S1",
        reference_id="GRCh38_standard",
        r1_path=str(r1),
        r2_path=str(r2),
    )
    monkeypatch.setattr(foundation, "runs", [run])
    monkeypatch.setattr(foundation, "samples", [sample])
    monkeypatch.setattr(foundation, "run_steps", [])
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(foundation, "save_run", lambda run: run)
    monkeypatch.setattr(foundation, "_emit_run_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(foundation, "_check_stage_tools", lambda stage: (True, []))
    monkeypatch.setattr(foundation, "_validate_selected_backends", lambda stages: [])
    monkeypatch.setattr(foundation, "_reference_pipeline_preflight", lambda reference_id, stages: {"ready": True})
    monkeypatch.setattr(foundation, "_resolve_reference_fasta", lambda reference_id: tmp_path / "ref.fa")
    monkeypatch.setattr(foundation, "_resolve_pipeline_input", lambda path: path)

    with pytest.raises(foundation.HTTPException) as exc:
        start_pipeline(run.id, PipelineStartRequest(resume_existing=True))

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "no_restartable_alignment_checkpoint"


def test_alignment_checkpoint_status_reports_valid_existing_bam(monkeypatch, tmp_path):
    run = Run(
        id="run_with_checkpoint",
        project_id="project_1",
        sample_id="sample_1",
        mode="full",
        status="failed",
        reference_id="GRCh38_standard",
    )
    sample = Sample(
        id="sample_1",
        project_id="project_1",
        sample_id="S1",
        reference_id="GRCh38_standard",
    )
    checkpoint_dir = tmp_path / "results" / run.id
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "S1.name_sorted.bam").write_bytes(b"checkpoint")
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(foundation, "_valid_bam_checkpoint", lambda path: path.exists())

    status = foundation._alignment_checkpoint_status(run, sample)

    assert status["alignment"]["restartable"] is True
    assert status["alignment"]["best_checkpoint"]["kind"] == "name_sorted_bam"
