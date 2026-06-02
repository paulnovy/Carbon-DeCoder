import json
import subprocess
from pathlib import Path

from app.core.vendor_validation_parser import parse_vendor_validation_report


def test_vendor_validation_compare_script_generates_parseable_report(tmp_path: Path):
    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGTTCGT\n", encoding="utf-8")
    out = tmp_path / "vendor_validation.report.json"

    script = Path(__file__).resolve().parents[3] / "pipelines/nextflow/scripts/vendor_validation_compare.py"
    subprocess.run(
        [
            "python3",
            str(script),
            "--vendor",
            str(vendor),
            "--pipeline",
            str(pipeline),
            "--method",
            "exact",
            "--pass-threshold",
            "0.5",
            "--output",
            str(out),
        ],
        check=True,
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["comparator_method"] == "exact"
    assert payload["status"] in {"passed", "failed"}

    parsed = parse_vendor_validation_report(out)
    assert parsed["vendor_assembly_path"] == str(vendor)
    assert parsed["pipeline_assembly_path"] == str(pipeline)
    assert parsed["comparator_method"] == "exact"
    assert parsed["similarity_score"] is not None
