"""Fast, bounded FASTQ read-count estimation.

Gzipped FASTQ does not carry an exact read count. Exact counts require reading
the full decompressed stream, so this module estimates from an initial sample
and caches by file metadata.
"""

from __future__ import annotations

import bz2
import gzip
import os
from pathlib import Path
from typing import Any, BinaryIO


FASTQ_EXTENSIONS = (".fastq", ".fq", ".fastq.gz", ".fq.gz", ".fastq.bz2", ".fq.bz2")
DEFAULT_INPUT_DIR = Path(os.getenv("WGS_INPUT_DIR", "/data/input"))
DEFAULT_SAMPLE_READS = int(os.getenv("WGS_FASTQ_ESTIMATE_SAMPLE_READS", "200000"))
_CACHE: dict[tuple[str, int, int, int], dict[str, Any]] = {}


def is_fastq_path(path: str | Path) -> bool:
    return str(path).lower().endswith(FASTQ_EXTENSIONS)


def resolve_input_path(path: str | Path, input_dir: Path | None = None) -> Path:
    base_dir = (input_dir or DEFAULT_INPUT_DIR).resolve()
    raw = Path(path)
    target = raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()
    if not target.is_relative_to(base_dir):
        raise ValueError("path escapes input directory")
    return target


def _open_maybe_compressed(path: Path) -> tuple[BinaryIO, BinaryIO]:
    raw = path.open("rb")
    lower = path.name.lower()
    if lower.endswith(".gz"):
        return raw, gzip.GzipFile(fileobj=raw)
    if lower.endswith(".bz2"):
        return raw, bz2.BZ2File(raw)
    return raw, raw


def estimate_fastq_reads(path: str | Path, sample_reads: int = DEFAULT_SAMPLE_READS) -> dict[str, Any]:
    """Estimate reads in one FASTQ file from a bounded initial sample.

    For gzip/bzip2 files, the estimate uses compressed bytes consumed by the
    decompressor while reading the sample. It is intentionally labeled as an
    estimate; compression ratio can drift across very large files.
    """

    target = Path(path)
    stat = target.stat()
    cache_key = (str(target), stat.st_size, stat.st_mtime_ns, sample_reads)
    if cache_key in _CACHE:
        return dict(_CACHE[cache_key])

    sampled_reads = 0
    sampled_uncompressed_bytes = 0
    sampled_container_bytes = 0
    eof = False

    raw, stream = _open_maybe_compressed(target)
    try:
        for _ in range(sample_reads):
            record_bytes = 0
            complete = True
            for _line_no in range(4):
                line = stream.readline()
                if not line:
                    complete = False
                    break
                record_bytes += len(line)
            if not complete:
                eof = True
                break
            sampled_reads += 1
            sampled_uncompressed_bytes += record_bytes
        try:
            sampled_container_bytes = raw.tell()
        except Exception:
            sampled_container_bytes = 0
    finally:
        try:
            stream.close()
        finally:
            if stream is not raw:
                raw.close()

    if sampled_reads == 0:
        result = {
            "path": str(target),
            "size_bytes": stat.st_size,
            "estimated_reads": 0,
            "exact": True,
            "confidence": "none",
            "method": "fastq_initial_sample",
            "sampled_reads": 0,
            "sampled_container_bytes": sampled_container_bytes,
            "sampled_uncompressed_bytes": sampled_uncompressed_bytes,
        }
    elif eof:
        result = {
            "path": str(target),
            "size_bytes": stat.st_size,
            "estimated_reads": sampled_reads,
            "exact": True,
            "confidence": "high",
            "method": "fastq_full_file_count",
            "sampled_reads": sampled_reads,
            "sampled_container_bytes": sampled_container_bytes,
            "sampled_uncompressed_bytes": sampled_uncompressed_bytes,
        }
    else:
        # raw.tell() can include some decompressor read-ahead, but with a large
        # sample this is stable enough for progress/ETA estimation.
        denominator = sampled_container_bytes or sampled_uncompressed_bytes or 1
        estimated = round(sampled_reads * stat.st_size / denominator)
        confidence = "medium" if sampled_reads >= 50_000 else "low"
        result = {
            "path": str(target),
            "size_bytes": stat.st_size,
            "estimated_reads": int(estimated),
            "exact": False,
            "confidence": confidence,
            "method": "fastq_initial_compressed_sample",
            "sampled_reads": sampled_reads,
            "sampled_container_bytes": sampled_container_bytes,
            "sampled_uncompressed_bytes": sampled_uncompressed_bytes,
        }

    _CACHE[cache_key] = dict(result)
    return result


def estimate_fastq_input_reads(input_files: list[str | Path], input_dir: Path | None = None) -> dict[str, Any]:
    """Estimate total primary SAM records expected from FASTQ inputs.

    For paired-end FASTQ, aligners emit one primary record per mate, so the
    total used for alignment progress is the sum of read estimates across mate
    files, not the number of read pairs.
    """

    estimates: list[dict[str, Any]] = []
    for item in input_files:
        if not is_fastq_path(item):
            continue
        path = resolve_input_path(item, input_dir=input_dir)
        if path.exists():
            estimates.append(estimate_fastq_reads(path))

    total = sum(int(entry.get("estimated_reads") or 0) for entry in estimates)
    exact = bool(estimates) and all(bool(entry.get("exact")) for entry in estimates)
    confidence = "none"
    if estimates:
        if exact:
            confidence = "high"
        elif any(entry.get("confidence") == "low" for entry in estimates):
            confidence = "low"
        else:
            confidence = "medium"

    return {
        "estimated_total_reads": total or None,
        "estimated_read_pairs": min((int(entry.get("estimated_reads") or 0) for entry in estimates), default=None)
        if len(estimates) >= 2
        else None,
        "files": estimates,
        "file_count": len(estimates),
        "exact": exact,
        "confidence": confidence,
        "method": "sum_fastq_file_estimates",
    }
