from pathlib import Path

from app.core.alignment_parser import parse_flagstat_text, parse_idxstats_text


def test_parse_flagstat_text_extracts_percentages(tmp_path: Path):
    p = tmp_path / "flagstat.txt"
    p.write_text(
        "1000 + 0 in total (QC-passed reads + QC-failed reads)\n"
        "950 + 0 primary\n"
        "20 + 0 secondary\n"
        "30 + 0 supplementary\n"
        "900 + 0 mapped (90.00% : N/A)\n"
        "875 + 0 primary mapped (92.11% : N/A)\n"
        "850 + 0 properly paired (85.00% : N/A)\n"
        "100 + 0 duplicates\n",
        encoding="utf-8",
    )

    data = parse_flagstat_text(p)
    assert data["mapped_reads_pct"] == 90.0
    assert data["primary_reads"] == 950
    assert data["primary_mapped_reads"] == 875
    assert data["primary_mapped_pct"] == 92.11
    assert data["secondary_alignments"] == 20
    assert data["supplementary_alignments"] == 30
    assert data["properly_paired_pct"] == 85.0
    assert data["duplicates_pct"] == 10.0
    assert data["unmapped_reads"] == 100


def test_parse_flagstat_does_not_confuse_primary_with_primary_duplicates(tmp_path: Path):
    p = tmp_path / "flagstat.txt"
    p.write_text(
        "1000 + 0 in total (QC-passed reads + QC-failed reads)\n"
        "950 + 0 primary\n"
        "42 + 0 primary duplicates\n",
        encoding="utf-8",
    )

    data = parse_flagstat_text(p)
    assert data["primary_reads"] == 950
    assert data["primary_duplicates"] == 42


def test_parse_idxstats_text_extracts_mapped_contigs(tmp_path: Path):
    p = tmp_path / "idxstats.txt"
    p.write_text(
        "chr1\t248956422\t100\t0\n"
        "chr2\t242193529\t0\t0\n"
        "chr3\t198295559\t12\t0\n"
        "*\t0\t0\t50\n",
        encoding="utf-8",
    )

    data = parse_idxstats_text(p)
    assert data["mapped_contigs"] == 2
    assert data["total_mapped_reads"] == 112
    assert data["total_unmapped_reads"] == 50
    assert data["contigs"][0]["chr"] == "chr1"
    assert data["contigs"][0]["pct"] == 89.286
