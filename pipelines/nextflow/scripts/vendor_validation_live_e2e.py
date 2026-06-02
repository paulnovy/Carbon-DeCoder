#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return json.loads(body) if body else {}


def _get_json(base_url: str, path: str) -> dict:
    with urllib.request.urlopen(f"{_normalize_base_url(base_url)}{path}", timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return json.loads(body) if body else {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Run vendor validation full live E2E against API")
    ap.add_argument("--api-base-url", required=True)
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--pipeline", default=None)
    ap.add_argument("--r1", default=None)
    ap.add_argument("--r2", default=None)
    ap.add_argument("--max-reads", type=int, default=2000)
    ap.add_argument("--project-name", default="Vendor Validation E2E")
    ap.add_argument("--sample-id", default="S_vendor_e2e_live")
    ap.add_argument("--reference-id", default="GRCh38_standard")
    ap.add_argument("--method", default="proxy", choices=["proxy", "kmer", "exact"])
    ap.add_argument("--kmer-size", type=int, default=21)
    ap.add_argument("--pass-threshold", type=float, default=0.98)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    pipeline_assembly = args.pipeline
    if not pipeline_assembly:
        if not args.r1 or not args.r2:
            raise SystemExit("missing_pipeline_input: provide --pipeline or both --r1 and --r2")
        assembly_script = Path(__file__).resolve().parent / "fastq_to_fasta_assembly.py"
        built = outdir / "pipeline_assembly.from_fastq.fasta"
        subprocess.run(
            [
                "python3",
                str(assembly_script),
                "--r1",
                args.r1,
                "--r2",
                args.r2,
                "--max-reads",
                str(args.max_reads),
                "--output",
                str(built),
            ],
            check=True,
        )
        pipeline_assembly = str(built)

    project = _post_json(args.api_base_url, "/projects", {"name": args.project_name})
    project_id = project["id"]

    sample = _post_json(
        args.api_base_url,
        f"/projects/{project_id}/samples",
        {
            "sample_id": args.sample_id,
            "reference_id": args.reference_id,
        },
    )
    sample_pk = sample["id"]

    run = _post_json(
        args.api_base_url,
        f"/projects/{project_id}/run/full",
        {
            "sample_id": sample_pk,
            "reference_id": args.reference_id,
        },
    )
    run_id = run["id"]

    e2e_script = Path(__file__).resolve().parent / "vendor_validation_e2e.py"
    e2e_outdir = outdir / "e2e_artifacts"
    e2e_outdir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "python3",
            str(e2e_script),
            "--vendor",
            args.vendor,
            "--pipeline",
            pipeline_assembly,
            "--run-id",
            run_id,
            "--api-base-url",
            args.api_base_url,
            "--method",
            args.method,
            "--kmer-size",
            str(args.kmer_size),
            "--pass-threshold",
            str(args.pass_threshold),
            "--outdir",
            str(e2e_outdir),
        ],
        check=True,
    )

    latest = _get_json(args.api_base_url, f"/runs/{run_id}/validation/vendor-assembly/latest")
    gate = _get_json(args.api_base_url, f"/runs/{run_id}/validation/vendor-assembly/gate")

    summary = {
        "project_id": project_id,
        "sample_id": sample["sample_id"],
        "sample_pk": sample_pk,
        "run_id": run_id,
        "vendor_assembly_path": str(Path(args.vendor).resolve()),
        "pipeline_assembly_path": str(Path(pipeline_assembly).resolve()),
        "latest_validation": latest,
        "run_gate": gate,
        "artifacts_dir": str(e2e_outdir),
    }

    summary_path = outdir / "vendor_validation.live_e2e.summary.json"
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
