import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "real_wgs_validation_gate.py"
spec = importlib.util.spec_from_file_location("real_wgs_validation_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(gate)


def test_real_wgs_gate_passes_complete_evidence():
    checks = gate.evaluate_run_gate(
        health={"ok": True},
        version={"database_schema": {"enabled": True, "ok": True}},
        settings={"executor_policy": {"effective_executor": "worker_queue"}},
        run={"id": "run_real", "status": "done"},
        steps={
            "items": [
                {"step_name": "alignment", "status": "done"},
                {"step_name": "coverage", "status": "done"},
                {"step_name": "variants", "status": "done"},
                {"step_name": "sv", "status": "skipped"},
                {"step_name": "cnv", "status": "done"},
                {"step_name": "mtdna", "status": "done"},
                {"step_name": "taxonomy", "status": "done"},
                {"step_name": "benchmark", "status": "skipped"},
            ]
        },
        events={
            "items": [
                {"event_type": "pipeline_paused"},
                {"event_type": "pipeline_resumed"},
                {"event_type": "pipeline_cancel_requested"},
            ]
        },
        taxonomy={
            "count": 2,
            "items": [
                {"organism": "Streptococcus vestibularis", "read_count": 280322},
                {"organism": "Rothia dentocariosa", "read_count": 175748},
            ],
            "provenance": {"event_type": "taxonomy.imported", "taxonomy_input_mode": "host_depleted_bam_unmapped_pairs"},
        },
        bundle_verify={"status": "ready"},
        require_worker_queue=True,
    )

    assert {item["status"] for item in checks} == {"pass"}


def test_real_wgs_gate_fails_missing_core_stage():
    checks = gate.evaluate_run_gate(
        health={"ok": True},
        version={"database_schema": {"enabled": True, "ok": True}},
        settings={"executor_policy": {"effective_executor": "api_thread"}},
        run={"id": "run_real", "status": "running"},
        steps={"items": [{"step_name": "alignment", "status": "done"}]},
        events={"items": []},
        taxonomy=None,
        bundle_verify={"status": "degraded"},
        require_worker_queue=True,
    )

    failures = {item["name"] for item in checks if item["status"] == "fail"}
    assert "worker_queue_executor" in failures
    assert "run_completed" in failures
    assert "core_stage_coverage" in failures
    assert "report_bundle_ready" in failures


def test_real_wgs_gate_fails_done_taxonomy_without_visible_import():
    checks = gate.evaluate_run_gate(
        health={"ok": True},
        version={"database_schema": {"enabled": True, "ok": True}},
        settings={"executor_policy": {"effective_executor": "api_thread"}},
        run={"id": "run_real", "status": "done"},
        steps={
            "items": [
                {"step_name": "alignment", "status": "done"},
                {"step_name": "coverage", "status": "done"},
                {"step_name": "variants", "status": "done"},
                {"step_name": "taxonomy", "status": "done"},
            ]
        },
        events={"items": [{"event_type": "pipeline_paused"}, {"event_type": "pipeline_cancel_requested"}]},
        taxonomy={"count": 0, "items": [], "provenance": None},
        bundle_verify={"status": "ready"},
        require_worker_queue=False,
    )

    failures = {item["name"] for item in checks if item["status"] == "fail"}
    assert "taxonomy_import_visible" in failures
    assert "taxonomy_import_provenance" in failures


def test_real_wgs_gate_fails_imported_taxonomy_with_stale_step_status():
    checks = gate.evaluate_run_gate(
        health={"ok": True},
        version={"database_schema": {"enabled": True, "ok": True}},
        settings={"executor_policy": {"effective_executor": "api_thread"}},
        run={"id": "run_real", "status": "done"},
        steps={
            "items": [
                {"step_name": "alignment", "status": "done"},
                {"step_name": "coverage", "status": "done"},
                {"step_name": "variants", "status": "done"},
                {"step_name": "taxonomy", "status": "running"},
            ]
        },
        events={"items": [{"event_type": "pipeline_paused"}, {"event_type": "pipeline_cancel_requested"}]},
        taxonomy={
            "count": 1,
            "items": [{"organism": "Rothia dentocariosa", "read_count": 175748}],
            "provenance": {"event_type": "taxonomy.imported"},
        },
        bundle_verify={"status": "ready"},
        require_worker_queue=False,
    )

    by_name = {item["name"]: item["status"] for item in checks}
    assert by_name["taxonomy_import_visible"] == "pass"
    assert by_name["taxonomy_import_provenance"] == "pass"
    assert by_name["taxonomy_step_matches_import"] == "fail"
