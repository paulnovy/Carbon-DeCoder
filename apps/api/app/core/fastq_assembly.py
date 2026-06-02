from __future__ import annotations

import gzip
from pathlib import Path


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return path.open("r", encoding="utf-8", errors="ignore")


def _iter_fastq_sequences(path: Path):
    with _open_text(path) as f:
        block: list[str] = []
        for line in f:
            block.append(line.rstrip("\n"))
            if len(block) == 4:
                yield block[1].strip().upper()
                block = []


def build_stub_assembly_from_fastq(r1_path: Path, r2_path: Path, max_reads: int = 2000) -> str:
    chunks: list[str] = []
    count = 0

    for seq in _iter_fastq_sequences(r1_path):
        if seq:
            chunks.append(seq)
            count += 1
        if count >= max_reads:
            break

    if count < max_reads:
        for seq in _iter_fastq_sequences(r2_path):
            if seq:
                chunks.append(seq)
                count += 1
            if count >= max_reads:
                break

    return "".join(chunks)
