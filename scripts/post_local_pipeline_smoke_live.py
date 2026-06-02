#!/usr/bin/env python3
"""Bootstrap a local API run and post local pipeline smoke ingest contracts.

Expected use after `run_local_pipeline_smoke.sh` generated artifacts:
  python scripts/post_local_pipeline_smoke_live.py --outdir results/local-pipeline-smoke --api-base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REQUIRED_EVENT_TYPES = {"alignment.imported", "coverage.imported", "variants.imported"}
REQUIRED_DONE_STEPS = {"alignment", "coverage", "variant_calling"}


def _base(url: str) -> str:
    return url.rstrip("/")


def post_json(api_base_url: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{_base(api_base_url)}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def get_json(api_base_url: str, path: str) -> dict:
    with urllib.request.urlopen(f"{_base(api_base_url)}{path}", timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def _items(value: Any) -> list[Any]:
    if isinstance(value, dict):
        raw = value.get("items", [])
        return raw if isinstance(raw, list) else []
    return []


def _event_types(events: dict) -> set[str]:
    return {str(item.get("event_type")) for item in _items(events) if isinstance(item, dict)}


def _done_steps(steps: dict) -> set[str]:
    done: set[str] = set()
    for item in _items(steps):
        if isinstance(item, dict) and item.get("status") == "done":
            done.add(str(item.get("step_name")))
    return done


def build_live_gate(summary: dict) -> dict:
    """Build a hard smoke gate from API readbacks after batch ingest.

    The gate is intentionally technical: it asserts that API accepted core stage
    imports and exposes non-empty coverage/variant readbacks. It does not make
    biological or diagnostic claims.
    """
    batch_path = Path(summary["batch_result_path"])
    batch = json.loads(batch_path.read_text(encoding="utf-8")) if batch_path.exists() else {"ok": False}
    events = summary.get("events", {})
    steps = summary.get("steps", {})
    coverage = summary.get("coverage_summary", {})
    variants = summary.get("variants", {})

    event_types = _event_types(events)
    done_steps = _done_steps(steps)
    variants_count = int(variants.get("count", 0) or 0) if isinstance(variants, dict) else 0
    coverage_imported = isinstance(coverage, dict) and coverage.get("status") == "imported" and (
        coverage.get("mean_coverage") is not None or coverage.get("coverage") is not None
    )

    checks = {
        "batch_post_ok": bool(batch.get("ok")),
        "required_events_present": REQUIRED_EVENT_TYPES.issubset(event_types),
        "required_steps_done": REQUIRED_DONE_STEPS.issubset(done_steps),
        "coverage_imported": coverage_imported,
        "variants_imported": variants_count > 0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "observed": {
            "event_types": sorted(event_types),
            "done_steps": sorted(done_steps),
            "variants_count": variants_count,
            "coverage_status": coverage.get("status") if isinstance(coverage, dict) else None,
            "batch_processed_count": batch.get("processed_count"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", required=True, type=Path)
    ap.add_argument("--api-base-url", default="http://localhost:8000")
    ap.add_argument("--project-name", default="Local Pipeline Smoke")
    ap.add_argument("--sample-id", default="S_local_smoke")
    ap.add_argument("--reference-id", default="GRCh38_standard")
    ap.add_argument("--summary", type=Path, help="Output summary path; defaults to OUTDIR/smoke.live_api.summary.json")
    ap.add_argument("--no-fail-on-gate", action="store_true", help="Write gate result but return 0 even if assertions fail")
    args = ap.parse_args()

    outdir = args.outdir.resolve()
    if not outdir.exists():
        raise SystemExit(f"outdir_not_found: {outdir}")

    r1 = outdir / "S_smoke_R1.fastq"
    r2 = outdir / "S_smoke_R2.fastq"

    project = post_json(args.api_base_url, "/projects", {"name": args.project_name})
    project_id = project["id"]
    sample = post_json(
        args.api_base_url,
        f"/projects/{project_id}/samples",
        {
            "sample_id": args.sample_id,
            "reference_id": args.reference_id,
            "r1_path": str(r1),
            "r2_path": str(r2),
        },
    )
    run = post_json(
        args.api_base_url,
        f"/projects/{project_id}/run/full",
        {"sample_id": sample["id"], "reference_id": args.reference_id},
    )
    run_id = run["id"]

    batch_script = Path(__file__).resolve().parents[1] / "pipelines/nextflow/scripts/post_ingest_contracts_batch.py"
    batch_result_path = outdir / "smoke.ingest.batch.live_post.json"
    subprocess.run(
        [
            "python3",
            str(batch_script),
            "--root",
            str(outdir),
            "--run-id",
            run_id,
            "--api-base-url",
            args.api_base_url,
            "--absolutize-payload-paths",
            "--output",
            str(batch_result_path),
        ],
        check=True,
    )

    summary = {
        "ok": True,
        "api_base_url": args.api_base_url,
        "project_id": project_id,
        "sample_id": sample["sample_id"],
        "sample_pk": sample["id"],
        "run_id": run_id,
        "batch_result_path": str(batch_result_path),
        "run": get_json(args.api_base_url, f"/runs/{run_id}"),
        "steps": get_json(args.api_base_url, f"/runs/{run_id}/steps"),
        "events": get_json(args.api_base_url, f"/runs/{run_id}/events"),
        "coverage_summary": get_json(args.api_base_url, f"/samples/{sample['sample_id']}/coverage-summary"),
        "variants": get_json(args.api_base_url, f"/samples/{sample['sample_id']}/variants"),
    }
    summary["live_gate"] = build_live_gate(summary)
    summary["ok"] = bool(summary["live_gate"]["ok"])
    summary_path = args.summary or (outdir / "smoke.live_api.summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok" if summary["ok"] else "gate_failed", "run_id": run_id, "summary_path": str(summary_path), "gate": summary["live_gate"]}))
    return 0 if summary["ok"] or args.no_fail_on_gate else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        print(json.dumps({"status": "http_error", "code": exc.code, "body": body}))
        raise
