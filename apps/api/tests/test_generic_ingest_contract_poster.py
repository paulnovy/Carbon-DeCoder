import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "pipelines/nextflow/scripts/post_ingest_contract.py"


def test_post_ingest_contract_dry_run_injects_run_id(tmp_path: Path):
    contract = tmp_path / "alignment.ingest.json"
    out = tmp_path / "result.json"
    contract.write_text(
        json.dumps({"event_type": "run.ingest.request", "stage": "alignment", "payload": {"flagstat_txt": "x.flagstat.txt"}}),
        encoding="utf-8",
    )

    subprocess.run(
        [str(SCRIPT), "--contract", str(contract), "--run-id", "run_123", "--dry-run", "--output", str(out)],
        check=True,
    )

    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["url"].endswith("/runs/run_123/ingest")
    assert result["request"]["stage"] == "alignment"
    assert result["request"]["payload"]["flagstat_txt"] == "x.flagstat.txt"


def test_post_ingest_contract_rejects_unknown_stage(tmp_path: Path):
    contract = tmp_path / "bad.ingest.json"
    out = tmp_path / "bad.result.json"
    contract.write_text(json.dumps({"run_id": "run_123", "stage": "nope", "payload": {}}), encoding="utf-8")

    proc = subprocess.run(
        [str(SCRIPT), "--contract", str(contract), "--dry-run", "--output", str(out)],
        text=True,
        capture_output=True,
    )

    assert proc.returncode == 2
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "unsupported_stage" in result["error"]
