import gzip
from pathlib import Path


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return path.open("r", encoding="utf-8", errors="ignore")


def parse_mosdepth_regions(path: Path) -> list[dict]:
    """Parse mosdepth regions BED(.gz) rows: chrom start end depth."""
    if not path.exists():
        return []

    rows: list[dict] = []
    with _open_text(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            chrom = parts[0]
            try:
                start = int(parts[1])
                end = int(parts[2])
                depth = float(parts[3])
            except ValueError:
                continue
            if end <= start:
                continue
            rows.append({"contig": chrom, "start": start + 1, "end": end, "coverage": depth})

    return rows


def build_tiles_from_regions(*, rows: list[dict], level: str) -> list[dict]:
    level_key = level.strip().lower()
    bin_size = {"5mb": 5_000_000, "1mb": 1_000_000, "500kb": 500_000}.get(level_key, 1_000_000)

    buckets: dict[tuple[str, int], dict] = {}
    for row in rows:
        contig = str(row.get("contig", "")).strip()
        start = int(row.get("start", 1))
        end = int(row.get("end", start))
        cov = float(row.get("coverage", 0.0))

        if not contig or end < start:
            continue

        start_idx = max(0, (start - 1) // bin_size)
        end_idx = max(0, (end - 1) // bin_size)

        for idx in range(start_idx, end_idx + 1):
            key = (contig, idx)
            slot = buckets.get(key)
            if not slot:
                slot = {
                    "contig": contig,
                    "start": idx * bin_size + 1,
                    "end": (idx + 1) * bin_size,
                    "sum_coverage": 0.0,
                    "segments": 0,
                }
                buckets[key] = slot
            slot["sum_coverage"] += cov
            slot["segments"] += 1

    tiles = []
    for contig, idx in sorted(buckets.keys(), key=lambda x: (x[0], x[1])):
        slot = buckets[(contig, idx)]
        segments = slot["segments"] or 1
        tiles.append(
            {
                "contig": contig,
                "start": slot["start"],
                "end": slot["end"],
                "coverage": round(slot["sum_coverage"] / segments, 2),
            }
        )

    return tiles
