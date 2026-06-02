import json
from pathlib import Path

from scripts.post_local_pipeline_smoke_live import build_live_gate


def _summary(tmp_path: Path, *, batch_ok=True, coverage_status="imported", variants_count=1):
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"ok": batch_ok, "processed_count": 4}), encoding="utf-8")
    return {
        "batch_result_path": str(batch),
        "events": {
            "items": [
                {"event_type": "alignment.imported"},
                {"event_type": "coverage.imported"},
                {"event_type": "variants.imported"},
            ]
        },
        "steps": {
            "items": [
                {"step_name": "alignment", "status": "done"},
                {"step_name": "coverage", "status": "done"},
                {"step_name": "variant_calling", "status": "done"},
            ]
        },
        "coverage_summary": {"status": coverage_status, "mean_coverage": 30.0},
        "variants": {"count": variants_count, "items": [{}] * variants_count},
    }


def test_build_live_gate_accepts_successful_import_readbacks(tmp_path: Path):
    gate = build_live_gate(_summary(tmp_path))
    assert gate["ok"] is True
    assert gate["checks"]["batch_post_ok"] is True
    assert gate["checks"]["coverage_imported"] is True
    assert gate["checks"]["variants_imported"] is True


def test_build_live_gate_fails_when_variants_are_empty(tmp_path: Path):
    gate = build_live_gate(_summary(tmp_path, variants_count=0))
    assert gate["ok"] is False
    assert gate["checks"]["variants_imported"] is False


def test_build_live_gate_requires_imported_coverage_status(tmp_path: Path):
    gate = build_live_gate(_summary(tmp_path, coverage_status="missing"))
    assert gate["ok"] is False
    assert gate["checks"]["coverage_imported"] is False
