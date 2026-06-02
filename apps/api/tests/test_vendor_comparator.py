from pathlib import Path

from app.core.vendor_comparator import compare_vendor_assemblies


def test_compare_vendor_assemblies_returns_scores(tmp_path: Path):
    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGTACGTNN\n", encoding="utf-8")

    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGTACGA\n", encoding="utf-8")

    out = compare_vendor_assemblies(vendor, pipeline)
    assert 0.0 <= out["similarity_score"] <= 1.0
    assert 0.0 <= out["snv_concordance"] <= 1.0
    assert 0.0 <= out["indel_concordance"] <= 1.0
    assert 0.0 <= out["structural_concordance"] <= 1.0
    assert "stats" in out
    assert "vendor" in out["stats"]


def test_compare_vendor_assemblies_kmer_mode(tmp_path: Path):
    vendor = tmp_path / "vendor_k.fa"
    vendor.write_text(">chr1\nACGTACGTACGTACGT\n", encoding="utf-8")

    pipeline = tmp_path / "pipeline_k.fa"
    pipeline.write_text(">chr1\nACGTACGTACGTTCGT\n", encoding="utf-8")

    out = compare_vendor_assemblies(vendor, pipeline, method="kmer", kmer_size=7)
    assert 0.0 <= out["similarity_score"] <= 1.0
    assert out["stats"]["comparator_method"] == "kmer"
    assert out["stats"]["kmer_k"] == 7


def test_compare_vendor_assemblies_exact_mode(tmp_path: Path):
    vendor = tmp_path / "vendor_exact.fa"
    vendor.write_text(">chr1\nACGTACGT\n", encoding="utf-8")

    pipeline = tmp_path / "pipeline_exact.fa"
    pipeline.write_text(">chr1\nACGTTCGT\n", encoding="utf-8")

    out = compare_vendor_assemblies(vendor, pipeline, method="exact")
    assert 0.0 <= out["similarity_score"] <= 1.0
    assert out["stats"]["comparator_method"] == "exact"
    assert out["stats"]["matches"] == 7
