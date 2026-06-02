"""Live progress endpoint for real-time alignment visualization.

Serves metrics written by the live SAM parser during alignment.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.alignment_parser import parse_flagstat_text, parse_idxstats_text
from app.core.fastq_read_estimator import estimate_fastq_input_reads
from app.store.memory_store import get_run, get_sample

router = APIRouter()

RESULTS_ROOT = Path(os.getenv("PIPELINE_RESULTS_ROOT", "/data/results"))

ALIGNMENT_SUBSTAGES = [
    ("sam_stream", "Aligner / SAM stream"),
    ("name_sort", "Name sort checkpoint"),
    ("fixmate", "Fixmate"),
    ("coord_sort", "Coordinate sort"),
    ("markdup", "Mark duplicates"),
    ("bam_index", "BAM index"),
    ("flagstat_idxstats", "Flagstat / idxstats"),
    ("ingest", "Alignment ingest"),
]


def _run_fastq_inputs(run_id: str) -> list[str]:
    run = get_run(run_id)
    sample = get_sample(run.sample_id) if run else None
    inputs: list[str] = []
    if sample and sample.r1_path:
        inputs.append(sample.r1_path)
    if sample and sample.r2_path:
        inputs.append(sample.r2_path)
    return inputs


def _sample_name_for_run(run_id: str) -> str:
    run = get_run(run_id)
    sample = get_sample(run.sample_id) if run else None
    return sample.sample_id if sample else (run.sample_id if run else "")


def _checkpoint_path(output_dir: Path, sample_name: str, suffix: str) -> Path:
    return output_dir / f"{sample_name}{suffix}"


def _checkpoint_state(run_id: str, sample_name: str) -> dict:
    output_dir = RESULTS_ROOT / run_id
    paths = {
        "name_sort": _checkpoint_path(output_dir, sample_name, ".name_sorted.bam"),
        "fixmate": _checkpoint_path(output_dir, sample_name, ".fixmate.bam"),
        "coord_sort": _checkpoint_path(output_dir, sample_name, ".coord_sorted.bam"),
        "markdup": _checkpoint_path(output_dir, sample_name, ".sorted.markdup.bam"),
        "bam_index": _checkpoint_path(output_dir, sample_name, ".sorted.markdup.bam.bai"),
        "flagstat_idxstats": _checkpoint_path(output_dir, sample_name, ".flagstat.txt"),
        "idxstats": _checkpoint_path(output_dir, sample_name, ".idxstats.txt"),
        "ingest": _checkpoint_path(output_dir, sample_name, ".alignment.ingest.json"),
    }
    done = {
        "sam_stream": any(paths[key].exists() for key in ("name_sort", "fixmate", "coord_sort", "markdup")),
        "name_sort": paths["name_sort"].exists() or paths["fixmate"].exists() or paths["coord_sort"].exists() or paths["markdup"].exists(),
        "fixmate": paths["fixmate"].exists() or paths["coord_sort"].exists() or paths["markdup"].exists(),
        "coord_sort": paths["coord_sort"].exists() or paths["markdup"].exists(),
        "markdup": paths["markdup"].exists(),
        "bam_index": paths["bam_index"].exists(),
        "flagstat_idxstats": paths["flagstat_idxstats"].exists() and paths["idxstats"].exists(),
        "ingest": paths["ingest"].exists(),
    }
    active = None
    for key, _ in ALIGNMENT_SUBSTAGES:
        if not done.get(key):
            active = key
            break
    if active is None:
        active = "complete"

    best_checkpoint = None
    for key, kind in [
        ("markdup", "complete_markdup_bam"),
        ("coord_sort", "coordinate_sorted_bam"),
        ("fixmate", "fixmate_bam"),
        ("name_sort", "name_sorted_bam"),
    ]:
        path = paths[key]
        if path.exists():
            best_checkpoint = {"kind": kind, "path": str(path), "size_bytes": path.stat().st_size}
            break

    substages = []
    for key, label in ALIGNMENT_SUBSTAGES:
        status = "done" if done.get(key) else "pending"
        if key == active:
            status = "active"
        substages.append({"id": key, "label": label, "status": status})

    return {
        "current_substage": active,
        "current_label": "Complete" if active == "complete" else next(label for key, label in ALIGNMENT_SUBSTAGES if key == active),
        "best_checkpoint": best_checkpoint,
        "substage_plan": substages,
        "final_bam_path": str(paths["markdup"]) if paths["markdup"].exists() else None,
        "final_bam_size_bytes": paths["markdup"].stat().st_size if paths["markdup"].exists() else None,
        "final_bai_path": str(paths["bam_index"]) if paths["bam_index"].exists() else None,
        "flagstat_path": str(paths["flagstat_idxstats"]) if paths["flagstat_idxstats"].exists() else None,
        "idxstats_path": str(paths["idxstats"]) if paths["idxstats"].exists() else None,
        "ingest_path": str(paths["ingest"]) if paths["ingest"].exists() else None,
    }


def _final_alignment_progress(run_id: str, sample_name: str) -> dict | None:
    output_dir = RESULTS_ROOT / run_id
    flagstat = output_dir / f"{sample_name}.flagstat.txt"
    idxstats = output_dir / f"{sample_name}.idxstats.txt"
    if not flagstat.exists() or not idxstats.exists():
        return None

    flag = parse_flagstat_text(flagstat)
    idx = parse_idxstats_text(idxstats)
    primary_reads = flag.get("primary_reads") or flag.get("total_reads") or 0
    primary_mapped = flag.get("primary_mapped_reads") or flag.get("mapped_reads") or 0
    primary_unmapped = flag.get("primary_unmapped_reads")
    if primary_unmapped is None and primary_reads:
        primary_unmapped = max(0, int(primary_reads) - int(primary_mapped or 0))
    mapped_pct = flag.get("primary_mapped_pct") or flag.get("mapped_reads_pct") or 0
    unmapped_pct = round((float(primary_unmapped or 0) / float(primary_reads)) * 100.0, 3) if primary_reads else 0

    contigs = sorted(idx.get("contigs") or [], key=lambda item: item.get("reads", 0), reverse=True)

    return {
        "run_id": run_id,
        "sample_id": sample_name,
        "status": "complete",
        "metric_source": "final_flagstat_idxstats",
        "metric_quality": "final",
        "timestamp": time.time(),
        "primary_reads_processed": primary_reads,
        "primary_reads_mapped": primary_mapped,
        "primary_reads_unmapped": primary_unmapped or 0,
        "total_reads_available": True,
        "total_reads_known": True,
        "total_reads_estimated": False,
        "total_reads_source": "samtools_flagstat",
        "total_reads": primary_reads,
        "progress_basis": "final_primary_alignment_records",
        "progress_fraction": 1.0,
        "progress_pct": 100,
        "mapped_pct": mapped_pct,
        "unmapped_pct": unmapped_pct,
        "reads_per_sec": 0,
        "reads_per_sec_avg": 0,
        "reads_per_sec_10s": 0,
        "eta_sec": 0,
        "eta_confidence": "complete",
        "mapq_ge30_pct": None,
        "mapq_60_pct": None,
        "proper_pair_pct": flag.get("properly_paired_pct"),
        "duplicates_pct": flag.get("duplicates_pct"),
        "singletons": flag.get("singletons"),
        "singletons_pct": flag.get("singletons_pct"),
        "secondary_alignments": flag.get("secondary_alignments", 0),
        "supplementary_alignments": flag.get("supplementary_alignments", 0),
        "mapped_contigs_total": idx.get("mapped_contigs", 0),
        "chromosomes": contigs,
        "alignment_summary": flag,
        "idxstats_summary": {
            "mapped_contigs": idx.get("mapped_contigs", 0),
            "total_mapped_reads": idx.get("total_mapped_reads", 0),
            "total_unmapped_reads": idx.get("total_unmapped_reads", 0),
        },
        "checkpoint_state": _checkpoint_state(run_id, sample_name),
    }


def _enrich_with_fastq_estimate(run_id: str, data: dict) -> dict:
    if data.get("status") == "no_data":
        return data

    estimate = data.get("fastq_read_estimate") if isinstance(data.get("fastq_read_estimate"), dict) else None
    total = data.get("total_reads")
    if not total:
        inputs = _run_fastq_inputs(run_id)
        if not inputs:
            return data
        try:
            estimate = estimate_fastq_input_reads(inputs)
        except Exception as exc:
            data["fastq_read_estimate_error"] = str(exc)
            return data
        total = estimate.get("estimated_total_reads")

    if not total:
        return data

    processed = int(data.get("primary_reads_processed") or 0)
    avg_rps = float(data.get("reads_per_sec_avg") or 0)
    if avg_rps <= 0 and processed and data.get("elapsed_sec"):
        avg_rps = processed / float(data["elapsed_sec"])
    ten_sec_rps = float(data.get("reads_per_sec_10s") or 0)

    remaining = max(0, int(total) - processed)
    progress = min(1.0, processed / int(total)) if total else None

    data["total_reads_available"] = True
    if estimate:
        data["total_reads_known"] = bool(estimate.get("exact"))
        data["total_reads_estimated"] = not bool(estimate.get("exact"))
        data["total_reads_source"] = estimate.get("method")
        data["fastq_read_estimate"] = estimate
    else:
        data["total_reads_known"] = bool(data.get("total_reads_known"))
        data["total_reads_estimated"] = bool(data.get("total_reads_estimated"))
        data["total_reads_source"] = data.get("total_reads_source")
    data["total_reads"] = int(total)
    data["progress_basis"] = "estimated_primary_sam_records" if data["total_reads_estimated"] else "primary_sam_records"
    data["progress_fraction"] = round(progress, 4) if progress is not None else None
    data["progress_pct"] = round(progress * 100, 1) if progress is not None else None
    if avg_rps > 0:
        if ten_sec_rps > 0:
            data["eta_sec_10s"] = round(remaining / ten_sec_rps, 0)
        data["eta_sec"] = round(remaining / avg_rps, 0)
        data["eta_method"] = "cumulative_average_reads_per_sec"
        data["eta_confidence"] = "estimated" if data["total_reads_estimated"] else data.get("eta_confidence") or "medium"
    return data


@router.get("/runs/{run_id}/live-progress")
def get_live_progress(run_id: str):
    """Return real-time alignment metrics written by the live SAM parser."""
    sample_name = _sample_name_for_run(run_id)
    final_progress = _final_alignment_progress(run_id, sample_name)
    if final_progress:
        return final_progress

    metrics_file = RESULTS_ROOT / run_id / "live_metrics.json"
    checkpoint_state = _checkpoint_state(run_id, sample_name)
    if not metrics_file.exists():
        return {
            "run_id": run_id,
            "sample_id": sample_name,
            "status": "checkpoint_resume" if checkpoint_state.get("best_checkpoint") else "no_data",
            "metric_source": "checkpoint_metadata" if checkpoint_state.get("best_checkpoint") else "none",
            "metric_quality": "recovered" if checkpoint_state.get("best_checkpoint") else "none",
            "checkpoint_state": checkpoint_state,
            "message": (
                "No live SAM stream is active; showing recovered alignment checkpoint state until final flagstat/idxstats exists."
                if checkpoint_state.get("best_checkpoint")
                else "No live metrics available. Alignment may not have started or live parser is not active."
            ),
        }
    try:
        data = json.loads(metrics_file.read_text())
        data["checkpoint_state"] = checkpoint_state
        if data.get("timestamp") and time.time() - float(data["timestamp"]) > 60:
            data["metric_quality"] = "stale_live"
            data["metric_source"] = data.get("metric_source") or "stale_live_metrics"
        return _enrich_with_fastq_estimate(run_id, data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read live metrics: {exc}")


@router.get("/runs/{run_id}/live-coverage")
def get_live_coverage(run_id: str, chr: str | None = None, resolution: int = 1_000_000):
    """Return live coverage bins for genome visualization."""
    metrics_file = RESULTS_ROOT / run_id / "live_metrics.json"
    if not metrics_file.exists():
        return {"bins": [], "status": "no_data"}
    try:
        data = json.loads(metrics_file.read_text())
        coverage_raw = data.get("coverage_bins", {})
        if not coverage_raw:
            # Reconstruct from chromosomes if coverage_bins not present
            return {"bins": [], "status": "no_coverage_data", "chromosomes": data.get("chromosomes", [])}

        bins = []
        for chr_name, chr_bins in coverage_raw.items():
            if chr and chr_name != chr:
                continue
            for bin_idx, count in sorted(chr_bins.items()):
                bins.append({
                    "chr": chr_name,
                    "bin_index": int(bin_idx),
                    "start_bp": int(bin_idx) * resolution,
                    "end_bp": (int(bin_idx) + 1) * resolution,
                    "read_count": count,
                })
        return {"bins": bins, "resolution": resolution, "status": "live"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read coverage: {exc}")
