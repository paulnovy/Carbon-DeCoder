import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/run_local_pipeline_smoke.sh"


def test_local_pipeline_smoke_dev_fallback_runs_end_to_end(tmp_path: Path):
    import os
    outdir = tmp_path / "smoke"
    env = os.environ.copy()
    env.update({"OUTDIR": str(outdir), "RUN_ID": "run_test_smoke", "STRICT": "false"})
    subprocess.run(
        [str(SCRIPT)],
        cwd=ROOT,
        env=env,
        check=True,
    )

    summary = json.loads((outdir / "smoke.summary.json").read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["run_id"] == "run_test_smoke"
    assert (outdir / summary["artifacts"]["alignment_contract"]).exists()
    assert (outdir / summary["artifacts"]["coverage_contract"]).exists()
    assert (outdir / summary["artifacts"]["variant_calling_contract"]).exists()
    assert (outdir / summary["artifacts"]["variant_normalization_contract"]).exists()

    batch = json.loads((outdir / "smoke.ingest.batch.dry_run.json").read_text(encoding="utf-8"))
    stages = [item["stage"] for item in batch["results"]]
    assert stages[:3] == ["alignment", "coverage", "variants"]
    assert all("/runs/run_test_smoke/ingest" in item["url"] for item in batch["results"])
