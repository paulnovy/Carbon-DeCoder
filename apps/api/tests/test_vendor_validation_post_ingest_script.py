import json
import subprocess
from pathlib import Path


def test_vendor_validation_post_ingest_script_dry_run(tmp_path: Path):
    contract = tmp_path / "vendor_validation.ingest.json"
    contract.write_text(
        json.dumps(
            {
                "run_id": "run_demo",
                "stage": "vendor_validation",
                "payload": {
                    "vendor_validation_report_path": "/tmp/vendor_validation.report.json",
                    "comparator_method": "kmer",
                    "kmer_size": 11,
                    "pass_threshold": 0.98,
                    "non_diagnostic": True,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[3] / "pipelines/nextflow/scripts/vendor_validation_post_ingest.py"
    output = tmp_path / "ingest.result.json"
    subprocess.run(
        [
            "python3",
            str(script),
            "--api-base-url",
            "http://127.0.0.1:9999",
            "--contract",
            str(contract),
            "--output",
            str(output),
            "--dry-run",
        ],
        check=True,
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "dry_run"
    assert result["request"]["stage"] == "vendor_validation"
    assert result["request"]["payload"]["comparator_method"] == "kmer"
