import gzip

import pytest
from fastapi import HTTPException

from app.core import reference_masks
from app.routers.foundation import (
    AlignmentImportRequest,
    CoverageImportRequest,
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    create_project,
    create_run_full,
    create_sample,
    generate_run_report,
    import_alignment_metrics,
    import_coverage_metrics,
    get_coverage_terrain,
    get_coverage_summary,
    get_coverage_tiles,
    ReportGenerateRequest,
)
from app.store.memory_store import (
    alignment_metrics,
    benchmark_records,
    cnv_segments,
    coverage_metrics,
    mtdna_results,
    projects,
    prs_results,
    reports,
    run_events,
    run_logs,
    run_steps,
    runs,
    samples,
    structural_variants,
    taxonomy_hits,
    variants,
)


def _reset_stores():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()
    reports.clear()
    variants.clear()
    structural_variants.clear()
    cnv_segments.clear()
    mtdna_results.clear()
    prs_results.clear()
    taxonomy_hits.clear()
    benchmark_records.clear()
    alignment_metrics.clear()
    coverage_metrics.clear()


def test_import_alignment_coverage_and_report_summary_uses_values():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Paln"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_aln", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    _ = import_alignment_metrics(
        run.id,
        AlignmentImportRequest(
            mapped_reads_pct=97.5,
            properly_paired_pct=95.9,
            duplicates_pct=11.2,
            mapped_contigs=25,
            unmapped_reads=101001,
            insert_size_median=341,
            insert_size_mad=33,
            source_files=["results/alignment/flagstat.txt"],
        ),
    )

    _ = import_coverage_metrics(
        run.id,
        CoverageImportRequest(
            mean_coverage=32.6,
            median_coverage=30.7,
            callable_fraction=0.951,
            coverage_ge_10x=0.972,
            coverage_ge_20x=0.927,
            coverage_ge_30x=0.873,
            source_files=["results/coverage/mosdepth.summary.txt"],
        ),
    )

    alignment_report = generate_run_report(
        run.id,
        ReportGenerateRequest(report_type="alignment", include_html=True, include_json=True, include_parquet=False),
    )
    coverage_report = generate_run_report(
        run.id,
        ReportGenerateRequest(report_type="coverage", include_html=True, include_json=True, include_parquet=False),
    )

    assert alignment_report.summary["flagstat"]["mapped_reads_pct"] == 97.5
    assert coverage_report.summary["mosdepth"]["mean_coverage"] == 32.6

    cov_summary = get_coverage_summary("S_aln")
    assert cov_summary["status"] == "imported"
    assert cov_summary["coverage_ge_20x"] == 0.927

    cov_tiles = get_coverage_tiles("S_aln", level="1mb")
    assert cov_tiles["status"] == "imported"
    assert cov_tiles["mode"] == "summary_only"
    assert cov_tiles["tiles"] == []
    assert "not synthesized" in cov_tiles["note"]

    terrain = get_coverage_terrain("S_aln", level="1mb")
    assert terrain["status"] == "imported"
    assert terrain["summary"]["tile_count"] == 0
    assert terrain["summary"]["low_count"] == 0
    assert terrain["summary"]["high_count"] == 0


def test_import_coverage_from_mosdepth_summary_file(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcovfile"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_cov_file", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    summary = tmp_path / "mosdepth.summary.txt"
    summary.write_text(
        """
chrom length bases mean min max
total 3099734149 94600000000 30.49 0 122
coverage>=10x 0.971
coverage>=20x 0.924
coverage>=30x 0.872
callable_fraction 0.949
        """.strip(),
        encoding="utf-8",
    )

    rec = import_coverage_metrics(run.id, CoverageImportRequest(mosdepth_summary_txt=str(summary)))
    assert rec.mean_coverage == 30.49
    assert rec.coverage_ge_20x == 0.924
    assert rec.callable_fraction == 0.949
    assert str(summary) in rec.source_files


def test_import_coverage_derives_callable_fraction_from_regions(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcovregions"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_cov_regions", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    summary = tmp_path / "mosdepth.summary.txt"
    summary.write_text(
        """
chrom length bases mean min max
total 300 9000 30 0 90
        """.strip(),
        encoding="utf-8",
    )
    regions = tmp_path / "regions.bed"
    regions.write_text("chr1\t0\t100\t35\nchr1\t100\t200\t12\nchr2\t0\t100\t21\n", encoding="utf-8")

    rec = import_coverage_metrics(
        run.id,
        CoverageImportRequest(mosdepth_summary_txt=str(summary), mosdepth_regions_bed_gz=str(regions)),
    )

    assert rec.callable_fraction == 0.666667
    assert rec.coverage_ge_20x == 0.666667
    assert rec.coverage_ge_10x == 1.0


def test_import_coverage_from_bad_summary_fails_strict(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcovbad"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_cov_bad", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    summary = tmp_path / "bad.summary.txt"
    summary.write_text("not_a_mosdepth_summary", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        import_coverage_metrics(run.id, CoverageImportRequest(mosdepth_summary_txt=str(summary)))

    assert exc.value.status_code == 400
    assert exc.value.detail == "mosdepth_summary_parse_failed"


def test_import_alignment_from_flagstat_idxstats_files(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Paln-file"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_aln_file", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    flagstat = tmp_path / "flagstat.txt"
    flagstat.write_text(
        "1000 + 0 in total (QC-passed reads + QC-failed reads)\n"
        "900 + 0 mapped (90.00% : N/A)\n"
        "850 + 0 properly paired (85.00% : N/A)\n"
        "100 + 0 duplicates\n",
        encoding="utf-8",
    )

    idxstats = tmp_path / "idxstats.txt"
    idxstats.write_text(
        "chr1\t248956422\t100\t0\n"
        "chr2\t242193529\t0\t0\n"
        "chr3\t198295559\t12\t0\n",
        encoding="utf-8",
    )

    rec = import_alignment_metrics(
        run.id,
        AlignmentImportRequest(flagstat_txt=str(flagstat), idxstats_txt=str(idxstats), source_files=[]),
    )

    assert rec.mapped_reads_pct == 90.0
    assert rec.properly_paired_pct == 85.0
    assert rec.duplicates_pct == 10.0
    assert rec.mapped_contigs == 2


def test_coverage_tiles_uses_materialized_regions_when_available(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcovtiles"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_cov_tiles", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    summary = tmp_path / "mosdepth.summary.txt"
    summary.write_text("total 3099734149 94600000000 31.0 0 100", encoding="utf-8")
    idxstats = tmp_path / "sample.idxstats.txt"
    idxstats.write_text(
        "chr1\t248956422\t1000\t0\n"
        "chrUn_KI270442v1\t392061\t75\t0\n"
        "chrEBV\t171823\t12\t0\n",
        encoding="utf-8",
    )

    regions = tmp_path / "sample.regions.bed.gz"
    with gzip.open(regions, "wt", encoding="utf-8") as fh:
        fh.write("chr1\t0\t1000000\t30.0\n")
        fh.write("chr1\t1000000\t2000000\t28.0\n")
        fh.write("chr2\t0\t1000000\t44.0\n")
        fh.write("chrUn_KI270442v1\t0\t1000000\t5.0\n")

    _ = import_alignment_metrics(run.id, AlignmentImportRequest(idxstats_txt=str(idxstats)))
    _ = import_coverage_metrics(
        run.id,
        CoverageImportRequest(
            mosdepth_summary_txt=str(summary),
            mosdepth_regions_bed_gz=str(regions),
        ),
    )

    tiles = get_coverage_tiles("S_cov_tiles", level="1mb")
    assert tiles["status"] == "imported"
    assert tiles["mode"] == "materialized"
    assert len(tiles["tiles"]) == 4
    assert tiles["primary_tile_count"] == 3
    assert tiles["other_contigs"][0]["contig"] == "chrUn_KI270442v1"
    assert tiles["other_contigs"][0]["reads"] == 75


def test_coverage_tiles_separates_reference_masked_zero_from_diagnostic_low(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcovmask"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_cov_mask", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    summary = tmp_path / "mosdepth.summary.txt"
    summary.write_text("total 3099734149 93000000000 30.0 0 100", encoding="utf-8")

    regions = tmp_path / "sample.regions.bed.gz"
    with gzip.open(regions, "wt", encoding="utf-8") as fh:
        fh.write("chr13\t0\t1000000\t0.0\n")
        fh.write("chr2\t10000000\t11000000\t0.0\n")
        fh.write("chr2\t11000000\t12000000\t31.0\n")

    _ = import_coverage_metrics(
        run.id,
        CoverageImportRequest(
            mosdepth_summary_txt=str(summary),
            mosdepth_regions_bed_gz=str(regions),
        ),
    )

    payload = get_coverage_tiles("S_cov_mask", level="1mb")
    by_start = {(t["contig"], t["start"]): t for t in payload["tiles"]}

    assert by_start[("chr13", 1)]["reference_mask_kind"] == "acrocentric_p_arm"
    assert by_start[("chr13", 1)]["anomaly"] == "reference_masked"
    assert by_start[("chr2", 10000001)]["anomaly"] == "low"
    assert payload["reference_mask_summary"]["masked_tile_count"] == 1


def test_coverage_tiles_includes_external_reference_tracks(tmp_path, monkeypatch):
    _reset_stores()
    track_dir = tmp_path / "tracks" / "GRCh38_standard"
    track_dir.mkdir(parents=True)
    (track_dir / "low_mappability.bed").write_text("chr2\t10000000\t11000000\tlowmap\n", encoding="utf-8")
    (track_dir / "gc_content.bedgraph").write_text("chr2\t10000000\t11000000\t18\n", encoding="utf-8")
    monkeypatch.setenv("WGS_COVERAGE_TRACKS_ROOT", str(tmp_path / "tracks"))
    reference_masks._load_external_tracks.cache_clear()

    project = create_project(ProjectCreateRequest(name="Pcovtracks"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_cov_tracks", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    summary = tmp_path / "mosdepth.summary.txt"
    summary.write_text("total 3099734149 93000000000 30.0 0 100", encoding="utf-8")
    regions = tmp_path / "sample.regions.bed.gz"
    with gzip.open(regions, "wt", encoding="utf-8") as fh:
        fh.write("chr2\t10000000\t11000000\t0.0\n")

    import_coverage_metrics(
        run.id,
        CoverageImportRequest(mosdepth_summary_txt=str(summary), mosdepth_regions_bed_gz=str(regions)),
    )

    payload = get_coverage_tiles("S_cov_tracks", level="1mb")
    tile = payload["tiles"][0]
    assert tile["anomaly"] == "reference_masked"
    assert tile["coverage_track_explained"] is True
    assert tile["coverage_interpretation_tracks"]["low_mappability"]["fraction"] == 1.0
    assert tile["coverage_interpretation_tracks"]["gc_content"]["gc_pct"] == 18.0
    assert payload["reference_track_summary"]["tracks_loaded"] == ["gc_content", "low_mappability"]
