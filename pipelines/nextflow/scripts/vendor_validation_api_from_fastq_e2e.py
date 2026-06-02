#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def _post_json(base_url: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{_normalize_base_url(base_url)}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return json.loads(body) if body else {}


def _get_json(base_url: str, path: str) -> dict:
    with urllib.request.urlopen(f"{_normalize_base_url(base_url)}{path}", timeout=60) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return json.loads(body) if body else {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Run API-first vendor validation E2E from sample FASTQ")
    ap.add_argument("--api-base-url", required=True)
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--r1", required=True)
    ap.add_argument("--r2", required=True)
    ap.add_argument("--project-name", default="Vendor Validation API FASTQ E2E")
    ap.add_argument("--sample-id", default="S_vendor_api_fastq_e2e")
    ap.add_argument("--reference-id", default="GRCh38_standard")
    ap.add_argument("--method", default="proxy", choices=["proxy", "kmer", "exact"])
    ap.add_argument("--kmer-size", type=int, default=21)
    ap.add_argument("--pass-threshold", type=float, default=0.98)
    ap.add_argument("--max-reads", type=int, default=2000)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    project = _post_json(args.api_base_url, "/projects", {"name": args.project_name})
    project_id = project["id"]

    sample = _post_json(
        args.api_base_url,
        f"/projects/{project_id}/samples",
        {
            "sample_id": args.sample_id,
            "reference_id": args.reference_id,
            "r1_path": str(Path(args.r1).resolve()),
            "r2_path": str(Path(args.r2).resolve()),
        },
    )

    run = _post_json(
        args.api_base_url,
        f"/projects/{project_id}/run/full",
        {
            "sample_id": sample["id"],
            "reference_id": args.reference_id,
        },
    )
    run_id = run["id"]

    imported = _post_json(
        args.api_base_url,
        f"/runs/{run_id}/validation/vendor-assembly/import-from-fastq",
        {
            "vendor_assembly_path": str(Path(args.vendor).resolve()),
            "comparator_method": args.method,
            "kmer_size": args.kmer_size,
            "pass_threshold": args.pass_threshold,
            "max_reads": args.max_reads,
        },
    )

    bundle = _post_json(args.api_base_url, f"/runs/{run_id}/reports/generate-all", {})
    latest = _get_json(args.api_base_url, f"/runs/{run_id}/validation/vendor-assembly/latest")
    gate = _get_json(args.api_base_url, f"/runs/{run_id}/validation/vendor-assembly/gate")

    summary = {
        "project_id": project_id,
        "sample_id": sample["sample_id"],
        "sample_pk": sample["id"],
        "run_id": run_id,
        "import_result": imported,
        "latest_validation": latest,
        "run_gate": gate,
        "report_bundle": {
            "count": bundle.get("count"),
            "bundle_manifest_path": bundle.get("bundle_manifest_path"),
            "bundle_index_path": bundle.get("bundle_index_path"),
        },
    }

    summary_path = outdir / "vendor_validation.api_from_fastq_e2e.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "summary_path": str(summary_path), "run_id": run_id}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        print(json.dumps({"status": "http_error", "code": exc.code, "body": body}))
        raise
