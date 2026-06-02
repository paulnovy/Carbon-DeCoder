import gzip
from pathlib import Path

from app.core.coverage_tiles_parser import build_tiles_from_regions, parse_mosdepth_regions
from app.core import reference_masks
from app.core.reference_masks import (
    annotate_coverage_interpretation_tracks,
    annotate_reference_masks,
    summarize_coverage_interpretation_tracks,
    summarize_reference_masks,
)


def test_parse_mosdepth_regions_reads_gz(tmp_path: Path):
    p = tmp_path / "sample.regions.bed.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write("chr1\t0\t1000000\t30.0\n")
        fh.write("chr1\t1000000\t2000000\t28.0\n")

    rows = parse_mosdepth_regions(p)
    assert len(rows) == 2
    assert rows[0]["contig"] == "chr1"
    assert rows[0]["start"] == 1
    assert rows[0]["end"] == 1000000


def test_build_tiles_from_regions_aggregates_bins():
    rows = [
        {"contig": "chr1", "start": 1, "end": 1000000, "coverage": 30.0},
        {"contig": "chr1", "start": 1000001, "end": 2000000, "coverage": 28.0},
        {"contig": "chr2", "start": 1, "end": 500000, "coverage": 42.0},
    ]

    tiles = build_tiles_from_regions(rows=rows, level="1mb")
    assert len(tiles) == 3
    assert tiles[0]["contig"] == "chr1"
    assert tiles[0]["coverage"] == 30.0


def test_annotate_reference_masks_marks_grch38_difficult_regions():
    tiles = [
        {"contig": "chr13", "start": 1, "end": 1_000_000, "coverage": 0.0},
        {"contig": "chr9", "start": 46_000_001, "end": 47_000_000, "coverage": 0.0},
        {"contig": "chr2", "start": 10_000_001, "end": 11_000_000, "coverage": 0.0},
    ]

    annotated = annotate_reference_masks(tiles, reference_id="GRCh38_standard")

    assert annotated[0]["reference_masked"] is True
    assert annotated[0]["reference_mask_kind"] == "acrocentric_p_arm"
    assert annotated[1]["reference_masked"] is True
    assert annotated[1]["reference_mask_kind"] == "heterochromatin"
    assert "reference_masked" not in annotated[2]

    summary = summarize_reference_masks(annotated)
    assert summary["masked_tile_count"] == 2
    assert summary["by_kind"] == {"acrocentric_p_arm": 1, "heterochromatin": 1}


def test_annotate_coverage_interpretation_tracks_from_reference_dir(tmp_path: Path, monkeypatch):
    track_dir = tmp_path / "GRCh38_standard"
    track_dir.mkdir()
    (track_dir / "giab_difficult.bed").write_text("chr2\t10000000\t11000000\tGIAB_low_confidence\n", encoding="utf-8")
    (track_dir / "gc_content.bedgraph").write_text("chr2\t10000000\t11000000\t82\n", encoding="utf-8")
    monkeypatch.setenv("WGS_COVERAGE_TRACKS_ROOT", str(tmp_path))
    reference_masks._load_external_tracks.cache_clear()

    tiles = [{"contig": "chr2", "start": 10_000_001, "end": 11_000_000, "coverage": 0.0}]
    annotated = annotate_coverage_interpretation_tracks(tiles, reference_id="GRCh38_standard")

    tracks = annotated[0]["coverage_interpretation_tracks"]
    assert annotated[0]["coverage_track_explained"] is True
    assert tracks["giab_difficult"]["fraction"] == 1.0
    assert tracks["gc_content"]["gc_pct"] == 82.0
    assert annotated[0]["gc_content_fraction"] == 0.82

    summary = summarize_coverage_interpretation_tracks(annotated)
    assert summary["tracks_loaded"] == ["gc_content", "giab_difficult"]
    assert summary["explained_low_tile_counts"]["giab_difficult"] == 1
