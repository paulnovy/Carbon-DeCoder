#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def main() -> int:
    ap = argparse.ArgumentParser(description="Post vendor validation ingest contract to API")
    ap.add_argument("--api-base-url", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout-seconds", type=float, default=30.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    contract_path = Path(args.contract)
    if not contract_path.exists():
        raise SystemExit(f"contract_not_found: {contract_path}")

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    run_id = contract.get("run_id")
    stage = contract.get("stage")
    payload = contract.get("payload")

    if not isinstance(run_id, str) or not run_id:
        raise SystemExit("invalid_contract: missing run_id")
    if stage != "vendor_validation":
        raise SystemExit("invalid_contract: stage must be vendor_validation")
    if not isinstance(payload, dict):
        raise SystemExit("invalid_contract: payload must be object")

    endpoint = f"{_normalize_base_url(args.api_base_url)}/runs/{run_id}/ingest"
    request_payload = {"stage": stage, "payload": payload}

    result = {
        "contract_path": str(contract_path.resolve()),
        "endpoint": endpoint,
        "request": request_payload,
        "status": "dry_run" if args.dry_run else "pending",
        "response": None,
        "http_status": None,
    }

    if not args.dry_run:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=args.timeout_seconds) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                parsed = json.loads(body) if body else None
                result["status"] = "ok"
                result["http_status"] = int(resp.status)
                result["response"] = parsed
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
            result["status"] = "http_error"
            result["http_status"] = int(exc.code)
            try:
                result["response"] = json.loads(body) if body else {"error": str(exc)}
            except Exception:
                result["response"] = {"error": str(exc), "body": body}
        except Exception as exc:
            result["status"] = "error"
            result["response"] = {"error": str(exc)}

    out_path = Path(args.output)
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(out_path)}))

    if result["status"] in {"ok", "dry_run"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
