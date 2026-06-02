#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run vendor validation E2E: compare -> ingest contract -> post ingest")
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--pipeline", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--api-base-url", required=True)
    ap.add_argument("--method", default="proxy", choices=["proxy", "kmer", "exact"])
    ap.add_argument("--kmer-size", type=int, default=21)
    ap.add_argument("--pass-threshold", type=float, default=0.98)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    base_dir = Path(__file__).resolve().parent
    compare_script = base_dir / "vendor_validation_compare.py"
    contract_script = base_dir / "vendor_validation_to_ingest_event.py"
    post_script = base_dir / "vendor_validation_post_ingest.py"

    report_path = outdir / "vendor_validation.report.json"
    contract_path = outdir / "vendor_validation.ingest.json"
    result_path = outdir / "vendor_validation.ingest.result.json"

    compare_cmd = [
        "python3",
        str(compare_script),
        "--vendor",
        args.vendor,
        "--pipeline",
        args.pipeline,
        "--method",
        args.method,
        "--kmer-size",
        str(args.kmer_size),
        "--pass-threshold",
        str(args.pass_threshold),
        "--output",
        str(report_path),
    ]
    _run(compare_cmd)

    contract_cmd = [
        "python3",
        str(contract_script),
        "--run-id",
        args.run_id,
        "--report",
        str(report_path),
        "--output",
        str(contract_path),
    ]
    _run(contract_cmd)

    post_cmd = [
        "python3",
        str(post_script),
        "--api-base-url",
        args.api_base_url,
        "--contract",
        str(contract_path),
        "--output",
        str(result_path),
    ]
    if args.dry_run:
        post_cmd.append("--dry-run")
    _run(post_cmd)

    summary = {
        "report_path": str(report_path),
        "contract_path": str(contract_path),
        "ingest_result_path": str(result_path),
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
