import json
import subprocess
from pathlib import Path


def test_vendor_validation_to_ingest_event_contract(tmp_path: Path):
    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTTCGT\n", encoding="utf-8")

    compare_script = Path(__file__).resolve().parents[3] / "pipelines/nextflow/scripts/vendor_validation_compare.py"
    report = tmp_path / "vendor_validation.report.json"
    subprocess.run(
        [
            "python3",
            str(compare_script),
            "--vendor",
            str(vendor),
            "--pipeline",
            str(pipeline),
            "--method",
            "kmer",
            "--kmer-size",
            "9",
            "--pass-threshold",
            "0.5",
            "--output",
            str(report),
        ],
        check=True,
    )

    contract_script = Path(__file__).resolve().parents[3] / "pipelines/nextflow/scripts/vendor_validation_to_ingest_event.py"
    contract = tmp_path / "vendor_validation.ingest.json"
    subprocess.run(
        [
            "python3",
            str(contract_script),
            "--run-id",
            "run_test_1",
            "--report",
            str(report),
            "--output",
            str(contract),
        ],
        check=True,
    )

    obj = json.loads(contract.read_text(encoding="utf-8"))
    assert obj["run_id"] == "run_test_1"
    assert obj["stage"] == "vendor_validation"
    assert obj["payload"]["vendor_validation_report_path"].endswith("vendor_validation.report.json")
    assert obj["payload"]["comparator_method"] == "kmer"
    assert obj["payload"]["kmer_size"] == 9
