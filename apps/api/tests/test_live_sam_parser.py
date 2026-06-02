import gzip

from app.core import live_sam_parser
from app.core.fastq_read_estimator import estimate_fastq_input_reads
from app.core.live_sam_parser import LiveMetrics
from app.routers.live_progress import _enrich_with_fastq_estimate


def test_live_metrics_marks_eta_unknown_without_total_reads(monkeypatch, tmp_path):
    monkeypatch.setattr(live_sam_parser.time, "time", lambda: 110.0)

    metrics = LiveMetrics(run_id="run_1", metrics_file=str(tmp_path / "live.json"))
    metrics.start_time = 100.0
    metrics.primary_processed = 1000
    metrics.primary_mapped = 900
    metrics.primary_unmapped = 100
    metrics.mapq_histogram["30-39"] = 450
    metrics.mapq_histogram["60"] = 450

    payload = metrics.build_metrics_dict()

    assert payload["total_reads_known"] is False
    assert payload["progress_pct"] is None
    assert payload["eta_sec"] is None
    assert payload["eta_confidence"] == "unknown"
    assert payload["reads_per_sec_avg"] == 100
    assert payload["mapped_pct"] == 90
    assert payload["mapq_ge30_pct"] == 100
    assert payload["mapq_60_pct"] == 50


def test_live_metrics_uses_estimated_total_reads(monkeypatch, tmp_path):
    monkeypatch.setattr(live_sam_parser.time, "time", lambda: 120.0)

    metrics = LiveMetrics(
        run_id="run_1",
        metrics_file=str(tmp_path / "live.json"),
        total_reads=10_000,
        total_reads_estimated=True,
        total_reads_source="sum_fastq_file_estimates",
    )
    metrics.start_time = 100.0
    metrics.primary_processed = 1000
    metrics.primary_mapped = 900
    metrics.primary_unmapped = 100

    payload = metrics.build_metrics_dict()

    assert payload["total_reads_available"] is True
    assert payload["total_reads_known"] is False
    assert payload["total_reads_estimated"] is True
    assert payload["total_reads_source"] == "sum_fastq_file_estimates"
    assert payload["progress_basis"] == "estimated_primary_sam_records"
    assert payload["progress_pct"] == 10.0
    assert payload["reads_per_sec"] == 50
    assert payload["eta_sec"] == 180
    assert payload["eta_method"] == "cumulative_average_reads_per_sec"
    assert payload["eta_confidence"] == "estimated"


def test_live_metrics_keeps_full_observed_contig_list(monkeypatch, tmp_path):
    monkeypatch.setattr(live_sam_parser.time, "time", lambda: 120.0)

    metrics = LiveMetrics(run_id="run_1", metrics_file=str(tmp_path / "live.json"))
    metrics.start_time = 100.0
    metrics.primary_processed = 40
    metrics.primary_mapped = 40
    for idx in range(40):
        metrics.chr_counts[f"chrUn_KI270{idx:03d}v1"] = 1

    payload = metrics.build_metrics_dict()

    assert payload["mapped_contigs_total"] == 40
    assert len(payload["chromosomes"]) == 40


def test_fastq_input_estimator_counts_small_gzip_pair(tmp_path):
    for name in ("S1_R1.fastq.gz", "S1_R2.fastq.gz"):
        with gzip.open(tmp_path / name, "wt", encoding="utf-8") as fh:
            for i in range(3):
                fh.write(f"@r{i}\nACGT\n+\n!!!!\n")

    estimate = estimate_fastq_input_reads(
        ["S1_R1.fastq.gz", "S1_R2.fastq.gz"],
        input_dir=tmp_path,
    )

    assert estimate["estimated_total_reads"] == 6
    assert estimate["estimated_read_pairs"] == 3
    assert estimate["exact"] is True


def test_live_progress_enrichment_overrides_bursty_eta():
    data = {
        "run_id": "run_1",
        "status": "aligning",
        "primary_reads_processed": 100,
        "elapsed_sec": 10,
        "reads_per_sec_avg": 10,
        "reads_per_sec_10s": 100,
        "total_reads": 1000,
        "total_reads_estimated": True,
        "total_reads_known": False,
        "eta_sec": 9,
    }

    enriched = _enrich_with_fastq_estimate("run_1", data)

    assert enriched["progress_pct"] == 10.0
    assert enriched["eta_sec_10s"] == 9
    assert enriched["eta_sec"] == 90
    assert enriched["eta_method"] == "cumulative_average_reads_per_sec"
