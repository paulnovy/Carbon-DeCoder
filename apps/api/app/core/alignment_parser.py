import re
from pathlib import Path


def _pct(raw: str | None) -> float | None:
    if not raw:
        return None
    value = raw.split("%", 1)[0].strip()
    try:
        return round(float(value), 3)
    except ValueError:
        return None


def _count_line(label: str, text: str) -> int | None:
    match = re.search(rf"^(\d+)\s+\+\s+\d+\s+{re.escape(label)}(?:\s+\(|$)", text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def _count_pct_line(label: str, text: str) -> tuple[int | None, float | None]:
    match = re.search(rf"^(\d+)\s+\+\s+\d+\s+{re.escape(label)}\s+\(([^)]+)\)", text, flags=re.MULTILINE)
    if not match:
        return None, None
    return int(match.group(1)), _pct(match.group(2))


def parse_flagstat_text(path: Path) -> dict:
    """Parse useful metrics from samtools flagstat-like output."""
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8", errors="ignore")
    out: dict = {}

    total_reads = _count_line("in total", text)
    primary_reads = _count_line("primary", text)
    secondary_reads = _count_line("secondary", text)
    supplementary_reads = _count_line("supplementary", text)
    duplicates_reads = _count_line("duplicates", text)
    primary_duplicates = _count_line("primary duplicates", text)
    mapped_reads, mapped_pct = _count_pct_line("mapped", text)
    primary_mapped_reads, primary_mapped_pct = _count_pct_line("primary mapped", text)
    paired_reads = _count_line("paired in sequencing", text)
    read1 = _count_line("read1", text)
    read2 = _count_line("read2", text)
    properly_paired_reads, properly_paired_pct = _count_pct_line("properly paired", text)
    singletons, singletons_pct = _count_pct_line("singletons", text)
    mate_diff_chr = _count_line("with mate mapped to a different chr", text)
    mate_diff_chr_mapq5 = _count_line("with mate mapped to a different chr (mapQ>=5)", text)

    raw_values = {
        "total_reads": total_reads,
        "primary_reads": primary_reads,
        "secondary_alignments": secondary_reads,
        "supplementary_alignments": supplementary_reads,
        "duplicates": duplicates_reads,
        "primary_duplicates": primary_duplicates,
        "mapped_reads": mapped_reads,
        "primary_mapped_reads": primary_mapped_reads,
        "paired_reads": paired_reads,
        "read1": read1,
        "read2": read2,
        "properly_paired_reads": properly_paired_reads,
        "singletons": singletons,
        "mate_mapped_different_chr": mate_diff_chr,
        "mate_mapped_different_chr_mapq_ge5": mate_diff_chr_mapq5,
    }
    out.update({key: value for key, value in raw_values.items() if value is not None})

    if total_reads and mapped_reads is not None:
        out["mapped_reads_pct"] = mapped_pct if mapped_pct is not None else round((mapped_reads / total_reads) * 100.0, 3)
        out["unmapped_reads"] = max(0, total_reads - mapped_reads)
    if total_reads and properly_paired_reads is not None:
        out["properly_paired_pct"] = (
            properly_paired_pct if properly_paired_pct is not None else round((properly_paired_reads / total_reads) * 100.0, 3)
        )
    if total_reads and duplicates_reads is not None:
        out["duplicates_pct"] = round((duplicates_reads / total_reads) * 100.0, 3)
    if primary_reads and primary_mapped_reads is not None:
        out["primary_mapped_pct"] = (
            primary_mapped_pct if primary_mapped_pct is not None else round((primary_mapped_reads / primary_reads) * 100.0, 3)
        )
        out["primary_unmapped_reads"] = max(0, primary_reads - primary_mapped_reads)
    if primary_reads and singletons is not None:
        out["singletons_pct"] = singletons_pct if singletons_pct is not None else round((singletons / primary_reads) * 100.0, 3)

    return out


def parse_idxstats_text(path: Path) -> dict:
    """Parse contig-level metrics from samtools idxstats-like output."""
    if not path.exists():
        return {}

    mapped_contigs = 0
    total_mapped = 0
    total_unmapped = 0
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = line.split("\t") if "\t" in line else line.split()
            if len(parts) < 4:
                continue
            contig = parts[0]
            try:
                length = int(parts[1])
                mapped = int(parts[2])
                unmapped = int(parts[3])
            except ValueError:
                continue
            if contig == "*":
                total_unmapped += unmapped
                continue
            total_mapped += mapped
            total_unmapped += unmapped
            if mapped > 0:
                mapped_contigs += 1
            rows.append({"chr": contig, "length": length, "reads": mapped, "unmapped": unmapped})

    for row in rows:
        row["pct"] = round((row["reads"] / total_mapped) * 100.0, 3) if total_mapped else 0.0

    return {
        "mapped_contigs": mapped_contigs,
        "total_mapped_reads": total_mapped,
        "total_unmapped_reads": total_unmapped,
        "contigs": rows,
    }
