from __future__ import annotations

from collections import Counter
from functools import lru_cache
import os
from pathlib import Path
from typing import Any


# UCSC hg38 cytoBand rows with stains that often explain apparent short-read
# no-coverage/low-mappability blocks: acen, gvar, and stalk.
UCSC_HG38_CYTOBAND_MASK_SOURCE = "ucsc_hg38_cytoband_acen_gvar_stalk"
COVERAGE_TRACKS_ROOT_ENV = "WGS_COVERAGE_TRACKS_ROOT"
DEFAULT_COVERAGE_TRACKS_ROOT = "/data/references/coverage_tracks"

COVERAGE_INTERPRETATION_TRACKS = {
    "ucsc_gap": {
        "label": "UCSC gap / assembly gap",
        "filenames": ("ucsc_gap.bed", "gaps.bed"),
        "kind": "assembly_gap",
    },
    "giab_difficult": {
        "label": "GIAB difficult / low-confidence region",
        "filenames": ("giab_difficult.bed", "giab_low_confidence.bed", "giab_stratification.bed"),
        "kind": "giab_difficult",
    },
    "low_mappability": {
        "label": "Low mappability region",
        "filenames": ("low_mappability.bed", "low_mappability_regions.bed"),
        "kind": "low_mappability",
    },
    "gc_content": {
        "label": "GC content",
        "filenames": ("gc_content.bedgraph", "gc_content.tsv", "gc_content.bed"),
        "kind": "gc_content",
    },
}

_ACROCENTRIC = {"13", "14", "15", "21", "22"}

# Coordinates below are 0-based half-open in the source table and converted to
# 1-based inclusive when applied to coverage tiles.
_UCSC_HG38_MASKS: tuple[tuple[str, int, int, str, str], ...] = (
    ("chr1", 121700000, 123400000, "p11.1", "acen"),
    ("chr1", 123400000, 125100000, "q11", "acen"),
    ("chr1", 125100000, 143200000, "q12", "gvar"),
    ("chr2", 91800000, 93900000, "p11.1", "acen"),
    ("chr2", 93900000, 96000000, "q11.1", "acen"),
    ("chr3", 87800000, 90900000, "p11.1", "acen"),
    ("chr3", 90900000, 94000000, "q11.1", "acen"),
    ("chr3", 94000000, 98600000, "q11.2", "gvar"),
    ("chr4", 48200000, 50000000, "p11", "acen"),
    ("chr4", 50000000, 51800000, "q11", "acen"),
    ("chr5", 46100000, 48800000, "p11", "acen"),
    ("chr5", 48800000, 51400000, "q11.1", "acen"),
    ("chr6", 58500000, 59800000, "p11.1", "acen"),
    ("chr6", 59800000, 62600000, "q11.1", "acen"),
    ("chr7", 58100000, 60100000, "p11.1", "acen"),
    ("chr7", 60100000, 62100000, "q11.1", "acen"),
    ("chr8", 43200000, 45200000, "p11.1", "acen"),
    ("chr8", 45200000, 47200000, "q11.1", "acen"),
    ("chr9", 42200000, 43000000, "p11.1", "acen"),
    ("chr9", 43000000, 45500000, "q11", "acen"),
    ("chr9", 45500000, 61500000, "q12", "gvar"),
    ("chr10", 38000000, 39800000, "p11.1", "acen"),
    ("chr10", 39800000, 41600000, "q11.1", "acen"),
    ("chr11", 51000000, 53400000, "p11.11", "acen"),
    ("chr11", 53400000, 55800000, "q11", "acen"),
    ("chr12", 33200000, 35500000, "p11.1", "acen"),
    ("chr12", 35500000, 37800000, "q11", "acen"),
    ("chr13", 0, 4600000, "p13", "gvar"),
    ("chr13", 4600000, 10100000, "p12", "stalk"),
    ("chr13", 10100000, 16500000, "p11.2", "gvar"),
    ("chr13", 16500000, 17700000, "p11.1", "acen"),
    ("chr13", 17700000, 18900000, "q11", "acen"),
    ("chr14", 0, 3600000, "p13", "gvar"),
    ("chr14", 3600000, 8000000, "p12", "stalk"),
    ("chr14", 8000000, 16100000, "p11.2", "gvar"),
    ("chr14", 16100000, 17200000, "p11.1", "acen"),
    ("chr14", 17200000, 18200000, "q11.1", "acen"),
    ("chr15", 0, 4200000, "p13", "gvar"),
    ("chr15", 4200000, 9700000, "p12", "stalk"),
    ("chr15", 9700000, 17500000, "p11.2", "gvar"),
    ("chr15", 17500000, 19000000, "p11.1", "acen"),
    ("chr15", 19000000, 20500000, "q11.1", "acen"),
    ("chr16", 35300000, 36800000, "p11.1", "acen"),
    ("chr16", 36800000, 38400000, "q11.1", "acen"),
    ("chr16", 38400000, 47000000, "q11.2", "gvar"),
    ("chr17", 22700000, 25100000, "p11.1", "acen"),
    ("chr17", 25100000, 27400000, "q11.1", "acen"),
    ("chr18", 15400000, 18500000, "p11.1", "acen"),
    ("chr18", 18500000, 21500000, "q11.1", "acen"),
    ("chr19", 19900000, 24200000, "p12", "gvar"),
    ("chr19", 24200000, 26200000, "p11", "acen"),
    ("chr19", 26200000, 28100000, "q11", "acen"),
    ("chr19", 28100000, 31900000, "q12", "gvar"),
    ("chr20", 25700000, 28100000, "p11.1", "acen"),
    ("chr20", 28100000, 30400000, "q11.1", "acen"),
    ("chr21", 0, 3100000, "p13", "gvar"),
    ("chr21", 3100000, 7000000, "p12", "stalk"),
    ("chr21", 7000000, 10900000, "p11.2", "gvar"),
    ("chr21", 10900000, 12000000, "p11.1", "acen"),
    ("chr21", 12000000, 13000000, "q11.1", "acen"),
    ("chr22", 0, 4300000, "p13", "gvar"),
    ("chr22", 4300000, 9400000, "p12", "stalk"),
    ("chr22", 9400000, 13700000, "p11.2", "gvar"),
    ("chr22", 13700000, 15000000, "p11.1", "acen"),
    ("chr22", 15000000, 17400000, "q11.1", "acen"),
    ("chrX", 58100000, 61000000, "p11.1", "acen"),
    ("chrX", 61000000, 63800000, "q11.1", "acen"),
    ("chrY", 10300000, 10400000, "p11.1", "acen"),
    ("chrY", 10400000, 10600000, "q11.1", "acen"),
    ("chrY", 26600000, 57227415, "q12", "gvar"),
)


def _normalize_contig(contig: str) -> str:
    raw = str(contig or "").strip()
    if not raw:
        return ""
    key = raw[3:] if raw.lower().startswith("chr") else raw
    if key.upper() in {"M", "MT"}:
        return "chrM"
    return f"chr{key.upper()}" if key.upper() in {"X", "Y"} else f"chr{key}"


def _is_grch38(reference_id: str | None) -> bool:
    ref = str(reference_id or "").lower()
    return not ref or "grch38" in ref or "hg38" in ref


def _reference_track_dir(reference_id: str | None, root: str | None = None) -> Path:
    safe_ref = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(reference_id or "unknown"))
    base = Path(root or os.getenv(COVERAGE_TRACKS_ROOT_ENV, DEFAULT_COVERAGE_TRACKS_ROOT))
    return base / safe_ref


def _mask_kind(chrom: str, start_0: int, stain: str) -> tuple[str, str]:
    key = chrom.replace("chr", "")
    if key in _ACROCENTRIC and start_0 < 20_500_000 and stain in {"gvar", "stalk"}:
        return "acrocentric_p_arm", "acrocentric p-arm / rDNA-stalk difficult region"
    if stain == "acen":
        return "centromere", "centromere"
    if stain == "stalk":
        return "stalk", "rDNA stalk / low-mappability region"
    return "heterochromatin", "heterochromatin / variable region"


_MASKS_BY_CONTIG: dict[str, list[dict[str, Any]]] = {}
for chrom, start_0, end_0, band, stain in _UCSC_HG38_MASKS:
    kind, label = _mask_kind(chrom, start_0, stain)
    _MASKS_BY_CONTIG.setdefault(chrom, []).append(
        {
            "contig": chrom,
            "start": start_0 + 1,
            "end": end_0,
            "band": band,
            "stain": stain,
            "kind": kind,
            "label": label,
            "source": UCSC_HG38_CYTOBAND_MASK_SOURCE,
        }
    )


def annotate_reference_masks(tiles: list[dict], reference_id: str | None = None) -> list[dict]:
    """Annotate coverage tiles that overlap known GRCh38 difficult cytobands."""
    if not _is_grch38(reference_id):
        return tiles

    for tile in tiles:
        contig = _normalize_contig(str(tile.get("contig", "")))
        masks = _MASKS_BY_CONTIG.get(contig, [])
        if not masks:
            continue

        start = int(tile.get("start", 1) or 1)
        end = int(tile.get("end", start) or start)
        if end < start:
            continue

        tile_len = max(1, end - start + 1)
        overlaps = []
        total_overlap = 0
        for mask in masks:
            overlap = max(0, min(end, mask["end"]) - max(start, mask["start"]) + 1)
            if overlap <= 0:
                continue
            total_overlap += overlap
            overlaps.append({**mask, "overlap_bp": overlap, "fraction": round(overlap / tile_len, 4)})

        if not overlaps:
            continue

        primary = max(overlaps, key=lambda item: item["overlap_bp"])
        fraction = min(1.0, total_overlap / tile_len)
        tile["reference_masked"] = True
        tile["reference_mask_kind"] = primary["kind"]
        tile["reference_mask_label"] = primary["label"]
        tile["reference_mask_fraction"] = round(fraction, 4)
        tile["reference_mask_source"] = UCSC_HG38_CYTOBAND_MASK_SOURCE
        tile["reference_masks"] = [
            {
                "kind": item["kind"],
                "label": item["label"],
                "band": item["band"],
                "stain": item["stain"],
                "start": item["start"],
                "end": item["end"],
                "fraction": item["fraction"],
            }
            for item in overlaps
        ]

    return tiles


def _parse_track_file(path: Path, track_id: str) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    try:
        with path.open("rt", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if not line.strip() or line.startswith("#") or line.startswith("track "):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    contig = _normalize_contig(parts[0])
                    start = int(float(parts[1])) + 1
                    end = int(float(parts[2]))
                except (TypeError, ValueError):
                    continue
                if end < start:
                    continue
                value = None
                label = None
                if track_id == "gc_content" and len(parts) >= 4:
                    try:
                        raw = float(parts[3])
                        value = raw / 100.0 if raw > 1.0 else raw
                    except (TypeError, ValueError):
                        value = None
                elif len(parts) >= 4:
                    label = parts[3]
                intervals.append({"contig": contig, "start": start, "end": end, "value": value, "label": label})
    except FileNotFoundError:
        return []
    return intervals


@lru_cache(maxsize=32)
def _load_external_tracks(reference_id: str | None, root: str) -> dict[str, dict[str, Any]]:
    track_dir = _reference_track_dir(reference_id, root)
    loaded: dict[str, dict[str, Any]] = {}
    for track_id, config in COVERAGE_INTERPRETATION_TRACKS.items():
        source_path = next((track_dir / name for name in config["filenames"] if (track_dir / name).exists()), None)
        if not source_path:
            continue
        by_contig: dict[str, list[dict[str, Any]]] = {}
        for interval in _parse_track_file(source_path, track_id):
            by_contig.setdefault(interval["contig"], []).append(interval)
        loaded[track_id] = {
            "track_id": track_id,
            "label": config["label"],
            "kind": config["kind"],
            "source": str(source_path),
            "interval_count": sum(len(items) for items in by_contig.values()),
            "by_contig": by_contig,
        }
    return loaded


def annotate_coverage_interpretation_tracks(tiles: list[dict], reference_id: str | None = None) -> list[dict]:
    """Annotate optional per-reference coverage interpretation BED/bedGraph tracks."""
    root = os.getenv(COVERAGE_TRACKS_ROOT_ENV, DEFAULT_COVERAGE_TRACKS_ROOT)
    tracks = _load_external_tracks(reference_id, root)
    if not tracks:
        return tiles

    for tile in tiles:
        contig = _normalize_contig(str(tile.get("contig", "")))
        start = int(tile.get("start", 1) or 1)
        end = int(tile.get("end", start) or start)
        if end < start:
            continue
        tile_len = max(1, end - start + 1)
        tile_tracks: dict[str, dict[str, Any]] = {}
        explanatory = False

        for track_id, track in tracks.items():
            intervals = track["by_contig"].get(contig, [])
            if not intervals:
                continue
            total_overlap = 0
            weighted_value = 0.0
            labels: list[str] = []
            for interval in intervals:
                overlap = max(0, min(end, interval["end"]) - max(start, interval["start"]) + 1)
                if overlap <= 0:
                    continue
                total_overlap += overlap
                if interval.get("value") is not None:
                    weighted_value += float(interval["value"]) * overlap
                if interval.get("label"):
                    labels.append(str(interval["label"]))

            if total_overlap <= 0:
                continue

            fraction = min(1.0, total_overlap / tile_len)
            item = {
                "track_id": track_id,
                "kind": track["kind"],
                "label": track["label"],
                "source": track["source"],
                "fraction": round(fraction, 4),
            }
            if labels:
                item["features"] = sorted(set(labels))[:5]
            if track_id == "gc_content":
                gc_fraction = weighted_value / total_overlap if total_overlap else None
                if gc_fraction is not None:
                    item["gc_fraction"] = round(max(0.0, min(1.0, gc_fraction)), 4)
                    item["gc_pct"] = round(item["gc_fraction"] * 100.0, 2)
                    tile["gc_content_fraction"] = item["gc_fraction"]
                    tile["gc_content_pct"] = item["gc_pct"]
                    if item["gc_fraction"] < 0.25 or item["gc_fraction"] > 0.75:
                        explanatory = True
                        item["extreme_gc"] = True
            else:
                explanatory = explanatory or fraction >= 0.1
            tile_tracks[track_id] = item

        if tile_tracks:
            tile["coverage_interpretation_tracks"] = tile_tracks
            tile["coverage_track_explained"] = explanatory

    return tiles


def summarize_reference_masks(tiles: list[dict]) -> dict:
    masked = [t for t in tiles if t.get("reference_masked")]
    by_kind = Counter(str(t.get("reference_mask_kind") or "reference_mask") for t in masked)
    masked_low = [
        t
        for t in masked
        if str(t.get("anomaly") or "") == "reference_masked" or float(t.get("coverage") or 0.0) <= 0.05
    ]
    return {
        "source": UCSC_HG38_CYTOBAND_MASK_SOURCE,
        "masked_tile_count": len(masked),
        "masked_low_tile_count": len(masked_low),
        "by_kind": dict(sorted(by_kind.items())),
    }


def summarize_coverage_interpretation_tracks(tiles: list[dict]) -> dict:
    counts: Counter[str] = Counter()
    explained_low: Counter[str] = Counter()
    gc_values: list[float] = []
    sources: dict[str, str] = {}

    for tile in tiles:
        tracks = tile.get("coverage_interpretation_tracks") or {}
        for track_id, item in tracks.items():
            counts[track_id] += 1
            if item.get("source"):
                sources[track_id] = item["source"]
            if track_id == "gc_content" and item.get("gc_fraction") is not None:
                gc_values.append(float(item["gc_fraction"]))
            if tile.get("coverage_track_explained") and (str(tile.get("anomaly") or "") == "reference_masked" or float(tile.get("coverage") or 0.0) <= 0.05):
                explained_low[track_id] += 1

    return {
        "tracks_loaded": sorted(counts),
        "tile_counts": dict(sorted(counts.items())),
        "explained_low_tile_counts": dict(sorted(explained_low.items())),
        "sources": sources,
        "gc_content": {
            "tile_count": len(gc_values),
            "mean_gc_fraction": round(sum(gc_values) / len(gc_values), 4) if gc_values else None,
        },
    }
