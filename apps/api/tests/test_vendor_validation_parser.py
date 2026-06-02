from pathlib import Path

from app.core.vendor_validation_parser import parse_vendor_validation_report


def test_parse_vendor_validation_report_key_value(tmp_path: Path):
    p = tmp_path / "vendor_validation.txt"
    p.write_text(
        "vendor_assembly_path=/tmp/vendor.fa\n"
        "pipeline_assembly_path=/tmp/pipeline.fa\n"
        "similarity_score=0.991\n"
        "snv_concordance=0.989\n"
        "indel_concordance=0.982\n"
        "structural_concordance=0.971\n"
        "comparator_method=kmer\n"
        "kmer_size=17\n"
        "pass_threshold=0.98\n"
        "summary_n50=51000000\n",
        encoding="utf-8",
    )

    out = parse_vendor_validation_report(p)
    assert out["vendor_assembly_path"] == "/tmp/vendor.fa"
    assert out["similarity_score"] == 0.991
    assert out["comparator_method"] == "kmer"
    assert out["kmer_size"] == 17
    assert out["summary"]["n50"] == 51000000.0


def test_parse_vendor_validation_report_csv(tmp_path: Path):
    p = tmp_path / "vendor_validation.csv"
    p.write_text(
        "vendor_assembly_path,pipeline_assembly_path,similarity_score,snv_concordance,summary_n50\n"
        "/tmp/vendor.fa,/tmp/pipeline.fa,0.994,0.993,52000000\n",
        encoding="utf-8",
    )

    out = parse_vendor_validation_report(p)
    assert out["vendor_assembly_path"] == "/tmp/vendor.fa"
    assert out["pipeline_assembly_path"] == "/tmp/pipeline.fa"
    assert out["snv_concordance"] == 0.993
    assert out["summary"]["n50"] == 52000000.0


def test_parse_vendor_validation_report_json(tmp_path: Path):
    p = tmp_path / "vendor_validation.json"
    p.write_text(
        '{"vendor_assembly_path":"/tmp/vendor.fa","pipeline_assembly_path":"/tmp/pipeline.fa","similarity_score":0.996,"summary":{"n50":53000000}}',
        encoding="utf-8",
    )

    out = parse_vendor_validation_report(p)
    assert out["vendor_assembly_path"] == "/tmp/vendor.fa"
    assert out["pipeline_assembly_path"] == "/tmp/pipeline.fa"
    assert out["similarity_score"] == 0.996
    assert out["summary"]["n50"] == 53000000


def test_parse_vendor_validation_report_accepts_exact_method(tmp_path: Path):
    p = tmp_path / "vendor_validation_exact.txt"
    p.write_text(
        "vendor_assembly_path=/tmp/vendor.fa\n"
        "pipeline_assembly_path=/tmp/pipeline.fa\n"
        "comparator_method=exact\n",
        encoding="utf-8",
    )

    out = parse_vendor_validation_report(p)
    assert out["comparator_method"] == "exact"
