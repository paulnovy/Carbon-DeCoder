import re
import gzip
from pathlib import Path


def _parse_last_float(parts: list[str]) -> float | None:
    for token in reversed(parts):
        try:
            return float(token)
        except ValueError:
            continue
    return None


def parse_mosdepth_summary_txt(path: Path) -> dict:
    """Parse minimal technical metrics from mosdepth summary-like text.

    Supports common table row forms (tab or whitespace separated), including:
    - `total <len> <bases> <mean> ...`
    - optional lines containing coverage threshold hints (>=10x, >=20x, >=30x)
    - optional callable_fraction marker
    """
    if not path.exists():
        return {}

    metrics: dict = {}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = re.split(r"\s+", line)
        if not parts:
            continue

        key = parts[0].lower()

        if key == "total" and len(parts) >= 4:
            try:
                metrics["mean_coverage"] = float(parts[3])
            except ValueError:
                pass
            continue

        if "callable_fraction" in key or "callable_fraction" in line.lower():
            value = _parse_last_float(parts)
            if value is not None:
                metrics["callable_fraction"] = value
            continue

        compact = line.lower().replace(" ", "")
        value = _parse_last_float(parts)
        if value is None:
            continue

        if ">=10x" in compact or "ge_10x" in compact:
            metrics["coverage_ge_10x"] = value
        elif ">=20x" in compact or "ge_20x" in compact:
            metrics["coverage_ge_20x"] = value
        elif ">=30x" in compact or "ge_30x" in compact:
            metrics["coverage_ge_30x"] = value
        elif "median_coverage" in compact or "mediancoverage" in compact:
            metrics["median_coverage"] = value

    return metrics


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return path.open("r", encoding="utf-8", errors="ignore")


def _primary_nuclear_contig(contig: str) -> bool:
    name = str(contig or "")
    if name.startswith("chr"):
        name = name[3:]
    return name in {str(i) for i in range(1, 23)} | {"X", "Y"}


def summarize_mosdepth_regions_thresholds(path: Path) -> dict:
    """Compute weighted primary-contig coverage fractions from mosdepth regions."""
    if not path.exists():
        return {}

    totals = {"primary_bases": 0, "ge_10x": 0, "ge_20x": 0, "ge_30x": 0}
    with _open_text(path) as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"\s+", line)
            if len(parts) < 4 or not _primary_nuclear_contig(parts[0]):
                continue
            try:
                start = int(parts[1])
                end = int(parts[2])
                depth = float(parts[3])
            except ValueError:
                continue
            length = max(0, end - start)
            if length <= 0:
                continue
            totals["primary_bases"] += length
            if depth >= 10:
                totals["ge_10x"] += length
            if depth >= 20:
                totals["ge_20x"] += length
            if depth >= 30:
                totals["ge_30x"] += length

    denom = totals["primary_bases"]
    if not denom:
        return {}
    return {
        "coverage_ge_10x": round(totals["ge_10x"] / denom, 6),
        "coverage_ge_20x": round(totals["ge_20x"] / denom, 6),
        "coverage_ge_30x": round(totals["ge_30x"] / denom, 6),
        "callable_fraction": round(totals["ge_20x"] / denom, 6),
        "callable_fraction_method": "mosdepth_regions_primary_contigs_ge20x",
    }
