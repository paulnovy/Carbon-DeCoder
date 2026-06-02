from pathlib import Path

from app.core.mtdna_parser import parse_mtdna_report
from app.core.prs_parser import parse_prs_result


def test_parse_mtdna_report_key_values(tmp_path: Path):
    p = tmp_path / "mtdna.report.txt"
    p.write_text(
        "haplogroup=H1\n"
        "heteroplasmy_mean_vaf=0.12\n"
        "num_variants=18\n"
        "numts_warning=true\n"
        "trust_score=61\n",
        encoding="utf-8",
    )

    data = parse_mtdna_report(p)
    assert data["haplogroup"] == "H1"
    assert data["num_variants"] == 18
    assert data["numts_warning"] is True


def test_parse_prs_result_key_values(tmp_path: Path):
    p = tmp_path / "prs.result.txt"
    p.write_text(
        "trait=CAD\n"
        "score_value=0.63\n"
        "overlap_pct=87.0\n"
        "variant_count_total=120000\n"
        "variant_count_matched=105000\n"
        "quality_label=medium\n",
        encoding="utf-8",
    )

    data = parse_prs_result(p)
    assert data["trait"] == "CAD"
    assert data["score_value"] == 0.63
    assert data["variant_count_total"] == 120000
