#!/usr/bin/env python3
"""Live SAM stream parser.

Sits between aligner stdout and samtools sort as a pipe filter:

    bwa-mem2 mem ... | python live_sam_parser.py --run-id X --metrics-file /path.json | samtools sort ...

Reads SAM lines from stdin, writes them unchanged to stdout, and
periodically updates a JSON metrics file with real-time alignment stats.

Metrics computed:
  - reads_processed (primary only, excluding secondary/supplementary)
  - reads_mapped / reads_unmapped
  - mapq histogram (buckets: 0, 1-9, 10-19, 20-29, 30-39, 40-49, 50-59, 60)
  - per-chromosome read counts
  - throughput (reads/sec over 10s window)
  - estimated ETA (if total reads known)
  - coverage bins (1Mb resolution)

Usage:
    python live_sam_parser.py --run-id run_abc --metrics-file /data/results/run_abc/live.json
    python live_sam_parser.py --run-id run_abc --metrics-file /data/results/run_abc/live.json --total-reads 500000000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path


def is_secondary(flag: int) -> bool:
    return (flag & 0x100) != 0


def is_supplementary(flag: int) -> bool:
    return (flag & 0x800) != 0


def is_primary(flag: int) -> bool:
    return not is_secondary(flag) and not is_supplementary(flag)


def is_unmapped(flag: int) -> bool:
    return (flag & 0x4) != 0


def is_reverse(flag: int) -> bool:
    return (flag & 0x10) != 0


def reference_span_from_cigar(cigar: str) -> int:
    """Calculate reference-consuming span from CIGAR string."""
    if cigar == "*":
        return 0
    span = 0
    i = 0
    while i < len(cigar):
        num_start = i
        while i < len(cigar) and cigar[i].isdigit():
            i += 1
        if i == num_start:
            break
        length = int(cigar[num_start:i])
        op = cigar[i]
        i += 1
        if op in ("M", "=", "X", "D", "N"):
            span += length
    return span


def mapq_bucket(mapq: int) -> str:
    if mapq == 0:
        return "0"
    elif mapq < 10:
        return "1-9"
    elif mapq < 20:
        return "10-19"
    elif mapq < 30:
        return "20-29"
    elif mapq < 40:
        return "30-39"
    elif mapq < 50:
        return "40-49"
    elif mapq < 60:
        return "50-59"
    else:
        return "60"


BUCKET_LABELS = ["0", "1-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60"]


def classify_cigar(cigar: str) -> str:
    """Classify CIGAR into a simple category."""
    if cigar == "*":
        return "unmapped"
    has_clip = "S" in cigar and cigar[0] != "S"  # trailing soft clip
    has_leading_clip = cigar[0] == "S" if cigar else False
    has_indel = "I" in cigar or "D" in cigar
    if has_leading_clip or has_clip:
        return "soft_clip"
    if has_indel:
        return "indel"
    return "clean"


class LiveMetrics:
    """Accumulates alignment metrics in real-time."""

    def __init__(
        self,
        run_id: str,
        metrics_file: str,
        total_reads: int | None = None,
        total_reads_estimated: bool = False,
        total_reads_source: str | None = None,
        bin_size: int = 1_000_000,
        sample_id: str | None = None,
        backend: str | None = None,
    ):
        self.run_id = run_id
        self.metrics_file = metrics_file
        self.total_reads = total_reads
        self.total_reads_estimated = total_reads_estimated
        self.total_reads_source = total_reads_source
        self.bin_size = bin_size
        self.sample_id = sample_id
        self.backend = backend

        self.start_time = time.time()
        self.last_write = 0.0
        self.write_interval = 1.0  # write metrics every 1 second

        # Counters
        self.primary_processed = 0
        self.primary_mapped = 0
        self.primary_unmapped = 0
        self.secondary_count = 0
        self.supplementary_count = 0
        self.total_records = 0

        # MAPQ histogram
        self.mapq_histogram: dict[str, int] = {b: 0 for b in BUCKET_LABELS}

        # Per-chromosome counts
        self.chr_counts: dict[str, int] = defaultdict(int)

        # Coverage bins: chr -> bin_index -> read_count
        self.coverage_bins: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

        # CIGAR classification
        self.cigar_classes: dict[str, int] = defaultdict(int)

        # Throughput tracking (sliding window)
        self._read_timestamps: list[float] = []

        # Paired-end tracking
        self.proper_pairs = 0
        self.total_pairs_seen = 0

    def process_line(self, line: str) -> None:
        """Parse one SAM record and update metrics."""
        if line.startswith("@"):
            return  # skip header

        fields = line.split("\t")
        if len(fields) < 11:
            return

        self.total_records += 1

        try:
            flag = int(fields[1])
        except (ValueError, IndexError):
            return

        rname = fields[2]
        try:
            pos = int(fields[3])
        except (ValueError, IndexError):
            pos = 0
        try:
            mapq = int(fields[4])
        except (ValueError, IndexError):
            mapq = 0
        cigar = fields[5]

        # Only count primary reads for progress
        if not is_primary(flag):
            if is_secondary(flag):
                self.secondary_count += 1
            if is_supplementary(flag):
                self.supplementary_count += 1
            return

        self.primary_processed += 1
        now = time.time()
        self._read_timestamps.append(now)

        # Trim sliding window to last 10 seconds
        cutoff = now - 10.0
        while self._read_timestamps and self._read_timestamps[0] < cutoff:
            self._read_timestamps.pop(0)

        if is_unmapped(flag):
            self.primary_unmapped += 1
            self.chr_counts["unmapped"] += 1
            return

        self.primary_mapped += 1
        self.mapq_histogram[mapq_bucket(mapq)] += 1
        self.chr_counts[rname] += 1

        # CIGAR classification
        cigar_class = classify_cigar(cigar)
        self.cigar_classes[cigar_class] += 1

        # Coverage bin
        span = reference_span_from_cigar(cigar)
        if span > 0 and rname != "*":
            bin_index = pos // self.bin_size
            self.coverage_bins[rname][bin_index] += 1

        # Paired-end
        if flag & 0x1:  # paired
            self.total_pairs_seen += 1
            if flag & 0x2:  # proper pair
                self.proper_pairs += 1

    def throughput_reads_per_sec(self) -> float:
        """Reads per second over the last 10s window."""
        if not self._read_timestamps:
            return 0.0
        window = self._read_timestamps[-1] - self._read_timestamps[0]
        if window <= 0:
            return float(len(self._read_timestamps))
        return len(self._read_timestamps) / window

    def average_reads_per_sec(self) -> float:
        """Reads per second across the whole observed alignment stream."""
        elapsed = time.time() - self.start_time
        if elapsed <= 0 or self.primary_processed == 0:
            return 0.0
        return self.primary_processed / elapsed

    def eta_seconds(self) -> float | None:
        """Estimate remaining seconds based on cumulative average throughput."""
        if not self.total_reads or self.primary_processed == 0:
            return None
        rps = self.average_reads_per_sec()
        if rps <= 0:
            return None
        remaining = self.total_reads - self.primary_processed
        if remaining <= 0:
            return 0.0
        return remaining / rps

    def progress_fraction(self) -> float | None:
        if not self.total_reads:
            return None
        return min(1.0, self.primary_processed / self.total_reads)

    def build_metrics_dict(self) -> dict:
        """Build the full metrics payload."""
        now = time.time()
        elapsed = now - self.start_time
        rps_10s = self.throughput_reads_per_sec()
        rps_avg = self.average_reads_per_sec()
        eta = self.eta_seconds()
        progress = self.progress_fraction()

        mapped_pct = (self.primary_mapped / self.primary_processed * 100) if self.primary_processed > 0 else 0
        mapq_ge30 = sum(self.mapq_histogram[b] for b in ["30-39", "40-49", "50-59", "60"])
        mapq_ge30_pct = (mapq_ge30 / self.primary_mapped * 100) if self.primary_mapped > 0 else 0
        mapq_60_pct = (self.mapq_histogram["60"] / self.primary_mapped * 100) if self.primary_mapped > 0 else 0

        # Build top chromosomes by read count
        chr_summary = []
        for chr_name, count in sorted(self.chr_counts.items(), key=lambda x: -x[1]):
            if chr_name == "unmapped":
                continue
            chr_summary.append({
                "chr": chr_name,
                "reads": count,
                "pct": round(count / self.primary_mapped * 100, 2) if self.primary_mapped > 0 else 0,
            })

        # Coverage summary: bins with coverage > threshold
        total_bins_with_coverage = 0
        for chr_bins in self.coverage_bins.values():
            total_bins_with_coverage += len(chr_bins)

        # ETA confidence is only meaningful when a total read count exists.
        eta_confidence = "unknown"
        if self.total_reads:
            if self.total_reads_estimated:
                eta_confidence = "estimated"
            else:
                eta_confidence = "low"
                if elapsed > 300:
                    eta_confidence = "high"
                elif elapsed > 60:
                    eta_confidence = "medium"

        total_reads_available = self.total_reads is not None

        return {
            "run_id": self.run_id,
            "sample_id": self.sample_id,
            "alignment_backend": self.backend,
            "metric_source": "sam_stdout",
            "progress_basis": "estimated_primary_sam_records" if self.total_reads_estimated else "primary_sam_records",
            "timestamp": now,
            "elapsed_sec": round(elapsed, 1),
            "status": "aligning",

            # Real progress (measured)
            "primary_reads_processed": self.primary_processed,
            "primary_reads_mapped": self.primary_mapped,
            "primary_reads_unmapped": self.primary_unmapped,
            "secondary_alignments": self.secondary_count,
            "supplementary_alignments": self.supplementary_count,
            "total_sam_records": self.total_records,

            # Progress
            "total_reads_available": total_reads_available,
            "total_reads_known": total_reads_available and not self.total_reads_estimated,
            "total_reads_estimated": self.total_reads_estimated,
            "total_reads_source": self.total_reads_source,
            "total_reads": self.total_reads,
            "progress_fraction": round(progress, 4) if progress is not None else None,
            "progress_pct": round(progress * 100, 1) if progress is not None else None,

            # Quality
            "mapped_pct": round(mapped_pct, 2),
            "mapq_ge30_pct": round(mapq_ge30_pct, 2),
            "mapq_60_pct": round(mapq_60_pct, 2),
            "mapq_histogram": self.mapq_histogram,

            # Throughput
            "reads_per_sec": round(rps_avg, 0),
            "reads_per_sec_10s": round(rps_10s, 0),
            "reads_per_sec_avg": round(rps_avg, 0),

            # ETA
            "eta_sec": round(eta, 0) if eta is not None else None,
            "eta_method": "cumulative_average_reads_per_sec" if eta is not None else None,
            "eta_confidence": eta_confidence,

            # Paired-end
            "proper_pair_pct": round(self.proper_pairs / self.total_pairs_seen * 100, 2) if self.total_pairs_seen > 0 else None,

            # Mapped-contig distribution. This is a read-share histogram, not
            # chromosome completion or coverage depth. Keep the full observed
            # list so the UI can render primary contigs in reference order and
            # independently sort the off-primary tail.
            "mapped_contigs_total": len(chr_summary),
            "chromosomes": chr_summary,

            # Coverage bins summary
            "coverage_bins_total": total_bins_with_coverage,
            "coverage_bin_size": self.bin_size,

            # CIGAR classification
            "cigar_classes": dict(self.cigar_classes),

            # Unmapped
            "unmapped_pct": round(self.primary_unmapped / self.primary_processed * 100, 2) if self.primary_processed > 0 else 0,
        }

    def write_metrics(self) -> None:
        """Write metrics to JSON file atomically."""
        now = time.time()
        if now - self.last_write < self.write_interval:
            return
        self.last_write = now

        metrics = self.build_metrics_dict()
        tmp_path = self.metrics_file + ".tmp"
        try:
            Path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w") as f:
                json.dump(metrics, f)
            os.replace(tmp_path, self.metrics_file)
        except Exception:
            pass  # don't crash the pipeline over metrics


def main():
    parser = argparse.ArgumentParser(description="Live SAM stream parser")
    parser.add_argument("--run-id", required=True, help="Run ID")
    parser.add_argument("--metrics-file", required=True, help="Path to output JSON metrics file")
    parser.add_argument("--total-reads", type=int, default=None, help="Total expected reads (for progress %)")
    parser.add_argument("--total-reads-estimated", action="store_true", help="Mark --total-reads as an estimate")
    parser.add_argument("--total-reads-source", default=None, help="Source/method used for --total-reads")
    parser.add_argument("--bin-size", type=int, default=1_000_000, help="Coverage bin size in bp")
    parser.add_argument("--sample-id", default=None, help="Sample ID, if distinct from run ID")
    parser.add_argument("--backend", default=None, help="Actual aligner backend producing the SAM stream")
    args = parser.parse_args()

    metrics = LiveMetrics(
        run_id=args.run_id,
        metrics_file=args.metrics_file,
        total_reads=args.total_reads,
        total_reads_estimated=args.total_reads_estimated,
        total_reads_source=args.total_reads_source,
        bin_size=args.bin_size,
        sample_id=args.sample_id,
        backend=args.backend,
    )

    # Read from stdin, write to stdout, parse in between
    for line in sys.stdin:
        sys.stdout.write(line)
        metrics.process_line(line.rstrip("\n"))
        metrics.write_metrics()

    # Final write
    metrics.write_metrics()


if __name__ == "__main__":
    main()
