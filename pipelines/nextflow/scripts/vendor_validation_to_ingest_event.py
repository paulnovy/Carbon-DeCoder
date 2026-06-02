#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Build worker ingest contract from vendor validation report")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        raise SystemExit(f"report_not_found: {report_path}")

    report = json.loads(report_path.read_text(encoding="utf-8"))

    payload = {
        "vendor_validation_report_path": str(report_path.resolve()),
        "comparator_method": report.get("comparator_method", "proxy"),
        "kmer_size": report.get("kmer_size"),
        "pass_threshold": report.get("pass_threshold", 0.98),
        "non_diagnostic": bool(report.get("non_diagnostic", True)),
    }

    contract = {
        "run_id": args.run_id,
        "stage": "vendor_validation",
        "payload": payload,
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out_path), "stage": "vendor_validation"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
