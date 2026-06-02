from pathlib import Path

import gzip

from app.core.coverage_parser import parse_mosdepth_summary_txt, summarize_mosdepth_regions_thresholds


def test_parse_mosdepth_summary_txt_extracts_mean_and_thresholds(tmp_path: Path):
    f = tmp_path / "mosdepth.summary.txt"
    f.write_text(
        """
chrom length bases mean min max
chr1 248956422 7600000000 30.52 0 118
total 3099734149 94600000000 30.49 0 122
coverage>=10x 0.971
coverage>=20x 0.924
coverage>=30x 0.872
callable_fraction 0.949
median_coverage 30.1
        """.strip(),
        encoding="utf-8",
    )

    metrics = parse_mosdepth_summary_txt(f)
    assert metrics["mean_coverage"] == 30.49
    assert metrics["coverage_ge_10x"] == 0.971
    assert metrics["coverage_ge_20x"] == 0.924
    assert metrics["coverage_ge_30x"] == 0.872
    assert metrics["callable_fraction"] == 0.949
    assert metrics["median_coverage"] == 30.1


def test_parse_mosdepth_summary_txt_missing_file_returns_empty(tmp_path: Path):
    missing = tmp_path / "missing.txt"
    assert parse_mosdepth_summary_txt(missing) == {}


def test_summarize_mosdepth_regions_thresholds_primary_contigs(tmp_path: Path):
    regions = tmp_path / "regions.bed.gz"
    with gzip.open(regions, "wt", encoding="utf-8") as handle:
        handle.write("chr1\t0\t100\t42\n")
        handle.write("chr1\t100\t200\t8\n")
        handle.write("chr2\t0\t100\t25\n")
        handle.write("chrM\t0\t100\t10000\n")
        handle.write("chrUn_KI270442v1\t0\t100\t80\n")

    metrics = summarize_mosdepth_regions_thresholds(regions)

    assert metrics["coverage_ge_10x"] == 0.666667
    assert metrics["coverage_ge_20x"] == 0.666667
    assert metrics["coverage_ge_30x"] == 0.333333
    assert metrics["callable_fraction"] == 0.666667
    assert metrics["callable_fraction_method"] == "mosdepth_regions_primary_contigs_ge20x"
