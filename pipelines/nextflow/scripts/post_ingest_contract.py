#!/usr/bin/env python3
"""Post a WGS Cockpit ingest contract to the API.

Contract shape:
{
  "event_type": "run.ingest.request",
  "run_id": "optional-if-cli---run-id-provided",
  "stage": "alignment|coverage|variants|...",
  "payload": {...}
}

This is intentionally generic so all Nextflow-emitted ingest artifacts can use
one uploader instead of stage-specific glue scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib import error, request

ALLOWED_STAGES = {
    "qc",
    "alignment",
    "coverage",
    "variants",
    "sv",
    "cnv",
    "mtdna",
    "prs",
    "taxonomy",
    "benchmark",
    "vendor_validation",
}


def load_contract(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid_json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("contract_must_be_object")
    return data


def normalize_contract(contract: dict, *, run_id_override: str | None = None) -> dict:
    stage = str(contract.get("stage") or "").strip().lower()
    if stage not in ALLOWED_STAGES:
        raise ValueError(f"unsupported_stage: {stage or '<missing>'}")

    run_id = run_id_override or contract.get("run_id")
    if not run_id or not isinstance(run_id, str):
        raise ValueError("missing_run_id")

    payload = contract.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("payload_must_be_object")

    return {"run_id": run_id, "stage": stage, "payload": payload}


def post_contract(api_base_url: str, normalized: dict, timeout_seconds: float) -> tuple[int, str]:
    url = f"{api_base_url.rstrip('/')}/runs/{normalized['run_id']}/ingest"
    body = json.dumps({"stage": normalized["stage"], "payload": normalized["payload"]}).encode("utf-8")
    req = request.Request(url=url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            return getattr(resp, "status", 200), resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contract", required=True, type=Path)
    ap.add_argument("--api-base-url", default="http://api:8000")
    ap.add_argument("--run-id", help="Override/run_id injection when contract was emitted without run_id")
    ap.add_argument("--output", type=Path, help="Write result JSON here")
    ap.add_argument("--dry-run", action="store_true", help="Validate and render request without POSTing")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args(argv)

    try:
        contract = load_contract(args.contract)
        normalized = normalize_contract(contract, run_id_override=args.run_id)
    except ValueError as exc:
        result = {"ok": False, "error": str(exc), "contract": str(args.contract)}
        if args.output:
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 2

    if args.dry_run:
        result = {
            "ok": True,
            "dry_run": True,
            "url": f"{args.api_base_url.rstrip('/')}/runs/{normalized['run_id']}/ingest",
            "request": {"stage": normalized["stage"], "payload": normalized["payload"]},
        }
    else:
        status, response_text = post_contract(args.api_base_url, normalized, args.timeout)
        result = {
            "ok": 200 <= status < 300,
            "dry_run": False,
            "status": status,
            "response": response_text,
            "url": f"{args.api_base_url.rstrip('/')}/runs/{normalized['run_id']}/ingest",
        }

    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
