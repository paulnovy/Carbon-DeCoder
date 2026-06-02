import json
import subprocess
from pathlib import Path


def test_vendor_validation_e2e_script_dry_run(tmp_path: Path):
    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGTTCGT\n", encoding="utf-8")

    outdir = tmp_path / "out"
    script = Path(__file__).resolve().parents[3] / "pipelines/nextflow/scripts/vendor_validation_e2e.py"

    subprocess.run(
        [
            "python3",
            str(script),
            "--vendor",
            str(vendor),
            "--pipeline",
            str(pipeline),
            "--run-id",
            "run_demo",
            "--api-base-url",
            "http://127.0.0.1:9999",
            "--method",
            "kmer",
            "--kmer-size",
            "9",
            "--pass-threshold",
            "0.5",
            "--outdir",
            str(outdir),
            "--dry-run",
        ],
        check=True,
    )

    report = json.loads((outdir / "vendor_validation.report.json").read_text(encoding="utf-8"))
    contract = json.loads((outdir / "vendor_validation.ingest.json").read_text(encoding="utf-8"))
    result = json.loads((outdir / "vendor_validation.ingest.result.json").read_text(encoding="utf-8"))

    assert report["comparator_method"] == "kmer"
    assert contract["stage"] == "vendor_validation"
    assert result["status"] == "dry_run"
