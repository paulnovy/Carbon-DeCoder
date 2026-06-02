from pathlib import Path

from app.core.benchmark_parser import parse_benchmark_report


def test_parse_benchmark_report_key_values(tmp_path: Path):
    p = tmp_path / "benchmark.txt"
    p.write_text(
        "benchmark_id=giab-hg002\n"
        "precision=0.946\n"
        "recall=0.936\n"
        "f1=0.941\n"
        "stratified_snv_f1=0.972\n",
        encoding="utf-8",
    )

    data = parse_benchmark_report(p)
    assert data["benchmark_id"] == "giab-hg002"
    assert data["precision"] == 0.946
    assert data["stratified_metrics"]["snv_f1"] == 0.972


def test_parse_benchmark_report_tsv(tmp_path: Path):
    p = tmp_path / "benchmark.tsv"
    p.write_text(
        "benchmark_id\tprecision\trecall\tf1\tstratified_snv_f1\n"
        "giab-hg002\t0.95\t0.94\t0.945\t0.971\n",
        encoding="utf-8",
    )

    data = parse_benchmark_report(p)
    assert data["benchmark_id"] == "giab-hg002"
    assert data["f1"] == 0.945
    assert data["stratified_metrics"]["snv_f1"] == 0.971


def test_parse_benchmark_report_happy_multirow_csv(tmp_path: Path):
    p = tmp_path / "happy.summary.csv"
    p.write_text(
        "Type,TRUTH.TOTAL,QUERY.TOTAL,METRIC.Precision,METRIC.Recall,METRIC.F1_Score\n"
        "SNP,1000,990,0.970,0.960,0.965\n"
        "INDEL,500,480,0.910,0.890,0.900\n",
        encoding="utf-8",
    )

    data = parse_benchmark_report(p)
    assert data["precision"] == 0.97
    assert data["recall"] == 0.96
    assert data["f1"] == 0.965
    assert data["stratified_metrics"]["snp_f1"] == 0.965
    assert data["stratified_metrics"]["indel_f1"] == 0.9
