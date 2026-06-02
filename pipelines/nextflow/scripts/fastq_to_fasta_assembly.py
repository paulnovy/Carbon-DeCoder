#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
from pathlib import Path


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return path.open("r", encoding="utf-8", errors="ignore")


def _iter_fastq_sequences(path: Path):
    with _open_text(path) as f:
        i = 0
        rec: list[str] = []
        for line in f:
            rec.append(line.rstrip("\n"))
            i += 1
            if i == 4:
                if len(rec) == 4:
                    yield rec[1].strip().upper()
                rec = []
                i = 0


def build_stub_assembly(r1: Path, r2: Path, max_reads: int = 2000) -> str:
    chunks: list[str] = []
    count = 0

    for seq in _iter_fastq_sequences(r1):
        if seq:
            chunks.append(seq)
            count += 1
        if count >= max_reads:
            break

    if count < max_reads:
        for seq in _iter_fastq_sequences(r2):
            if seq:
                chunks.append(seq)
                count += 1
            if count >= max_reads:
                break

    return "".join(chunks)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build simple pipeline assembly FASTA from paired FASTQ")
    ap.add_argument("--r1", required=True)
    ap.add_argument("--r2", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-reads", type=int, default=2000)
    args = ap.parse_args()

    r1 = Path(args.r1)
    r2 = Path(args.r2)
    if not r1.exists():
        raise SystemExit(f"r1_not_found: {r1}")
    if not r2.exists():
        raise SystemExit(f"r2_not_found: {r2}")

    seq = build_stub_assembly(r1, r2, max_reads=max(1, args.max_reads))
    if not seq:
        raise SystemExit("empty_assembly_sequence")

    out = Path(args.output)
    out.write_text(f">pipeline_assembly\n{seq}\n", encoding="utf-8")
    print(f"wrote {out} len={len(seq)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
