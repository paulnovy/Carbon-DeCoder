#!/usr/bin/env python3
"""Operator gate for a real full-WGS validation run.

This script is intentionally read-only. It does not start, stop, pause, or
delete runs. Use it after a real run has been executed on a deployment to
produce one JSON evidence file for the remaining "needs real data" backlog.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


CORE_STAGES = ("alignment", "coverage", "variants")
OPTIONAL_REAL_VALIDATION_STAGES = ("sv", "cnv", "mtdna", "taxonomy", "benchmark")
FRONTEND_ROUTES = ("/", "/runs", "/genome", "/reports", "/taxonomy", "/sv-cnv", "/mtdna")
PAUSE_EVENT_HINTS = ("pause", "paused", "resume", "resumed")
CANCEL_EVENT_HINTS = ("cancel", "cancelling", "cancelled")


def fetch_json(base: str, path: str, timeout: float = 15.0) -> dict[str, Any]:
    url = f"{base.rstrip('/')}{path}"
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # nosec: operator-provided deployment URL
        return json.loads(res.read().decode("utf-8"))


def fetch_text(base: str, path: str, timeout: float = 15.0) -> tuple[int, str]:
    url = f"{base.rstrip('/')}{path}"
    req = urllib.request.Request(url, headers={"accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # nosec: operator-provided deployment URL
        return int(res.status), res.read(8192).decode("utf-8", errors="replace")


def check(name: str, passed: bool, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "detail": detail,
        "evidence": evidence or {},
    }


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "steps", "events", "reports", "files"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def evaluate_run_gate(
    *,
    health: dict[str, Any],
    version: dict[str, Any],
    settings: dict[str, Any],
    run: dict[str, Any] | None,
    steps: dict[str, Any] | list[dict[str, Any]] | None,
    events: dict[str, Any] | list[dict[str, Any]] | None,
    taxonomy: dict[str, Any] | None = None,
    bundle_verify: dict[str, Any] | None,
    require_worker_queue: bool,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.append(check("api_health", bool(health.get("ok")), json.dumps(health, sort_keys=True)))

    schema = version.get("database_schema") if isinstance(version, dict) else None
    schema_ok = not isinstance(schema, dict) or schema.get("enabled") is False or schema.get("ok") is True
    checks.append(check("database_schema", schema_ok, json.dumps(schema or {}, sort_keys=True), schema or {}))

    policy = (settings.get("executor_policy") or {}) if isinstance(settings, dict) else {}
    effective_executor = policy.get("effective_executor")
    if require_worker_queue:
        checks.append(
            check(
                "worker_queue_executor",
                effective_executor == "worker_queue",
                f"effective_executor={effective_executor!r}",
                policy,
            )
        )
    else:
        checks.append(check("executor_policy_visible", bool(policy), json.dumps(policy, sort_keys=True), policy))

    if run is None:
        checks.append(check("run_supplied", False, "Provide --run-id for real WGS validation evidence."))
        return checks

    run_status = str(run.get("status") or "")
    checks.append(check("run_completed", run_status in {"done", "completed", "success"}, f"run status={run_status}", run))

    step_items = _items(steps)
    step_by_name = {str(item.get("step_name") or item.get("name") or ""): item for item in step_items}
    for stage in CORE_STAGES:
        item = step_by_name.get(stage) or {}
        status = str(item.get("status") or "")
        checks.append(check(f"core_stage_{stage}", status == "done", f"status={status or 'missing'}", item))

    for stage in OPTIONAL_REAL_VALIDATION_STAGES:
        item = step_by_name.get(stage) or {}
        status = str(item.get("status") or "")
        passed = status in {"done", "skipped"}
        detail = f"status={status or 'missing'}"
        checks.append(check(f"optional_stage_{stage}_accounted", passed, detail, item))

    taxonomy_step = step_by_name.get("taxonomy") or {}
    taxonomy_step_status = str(taxonomy_step.get("status") or "")
    taxonomy_count = 0
    taxonomy_items: list[dict[str, Any]] = []
    if taxonomy is not None:
        taxonomy_count = int(taxonomy.get("count") or 0)
        taxonomy_items = _items(taxonomy)
    if taxonomy_step_status == "done" or taxonomy_count > 0:
        if taxonomy is None:
            checks.append(check("taxonomy_import_visible", False, "Taxonomy endpoint was not checked."))
        else:
            provenance = taxonomy.get("provenance") if isinstance(taxonomy, dict) else None
            event_type = provenance.get("event_type") if isinstance(provenance, dict) else None
            checks.append(
                check(
                    "taxonomy_import_visible",
                    taxonomy_count > 0 and len(taxonomy_items) > 0,
                    f"count={taxonomy_count}, items={len(taxonomy_items)}",
                    taxonomy,
                )
            )
            checks.append(
                check(
                    "taxonomy_import_provenance",
                    event_type == "taxonomy.imported",
                    f"event_type={event_type or 'missing'}",
                    provenance if isinstance(provenance, dict) else {},
                )
            )
            checks.append(
                check(
                    "taxonomy_step_matches_import",
                    taxonomy_count == 0 or taxonomy_step_status == "done",
                    f"taxonomy_step_status={taxonomy_step_status or 'missing'}, count={taxonomy_count}",
                    {"taxonomy_step": taxonomy_step, "taxonomy_count": taxonomy_count},
                )
            )

    event_items = _items(events)
    event_names = [str(item.get("event_type") or item.get("type") or "") for item in event_items]
    has_pause_resume = any(any(hint in name for hint in PAUSE_EVENT_HINTS) for name in event_names)
    has_cancel_observation = any(any(hint in name for hint in CANCEL_EVENT_HINTS) for name in event_names)
    checks.append(check("pause_resume_evidence", has_pause_resume, ", ".join(event_names[-12:]), {"events": event_names[-25:]}))
    checks.append(check("cancel_evidence", has_cancel_observation, ", ".join(event_names[-12:]), {"events": event_names[-25:]}))

    if bundle_verify is not None:
        status = str(bundle_verify.get("status") or "")
        checks.append(check("report_bundle_ready", status == "ready", f"bundle status={status}", bundle_verify))
    else:
        checks.append(check("report_bundle_ready", False, "Bundle verification endpoint was not checked."))

    return checks


def collect(api: str, run_id: str | None, require_worker_queue: bool) -> dict[str, Any]:
    collected: dict[str, Any] = {
        "created_at_epoch": time.time(),
        "api": api.rstrip("/"),
        "run_id": run_id,
        "require_worker_queue": require_worker_queue,
        "fetch_errors": {},
        "payloads": {},
    }
    for name, path in (
        ("health", "/health"),
        ("version", "/version"),
        ("settings", "/pipeline/settings"),
    ):
        try:
            collected["payloads"][name] = fetch_json(api, path)
        except Exception as exc:  # noqa: BLE001 - gate should keep collecting evidence
            collected["fetch_errors"][name] = str(exc)
            collected["payloads"][name] = {}

    if run_id:
        quoted = urllib.parse.quote(run_id, safe="")
        for name, path in (
            ("run", f"/runs/{quoted}"),
            ("steps", f"/runs/{quoted}/steps"),
            ("events", f"/runs/{quoted}/events"),
            ("bundle_verify", f"/runs/{quoted}/reports/bundle/verify"),
        ):
            try:
                collected["payloads"][name] = fetch_json(api, path)
            except urllib.error.HTTPError as exc:
                collected["fetch_errors"][name] = f"HTTP {exc.code}: {exc.reason}"
                collected["payloads"][name] = None
            except Exception as exc:  # noqa: BLE001
                collected["fetch_errors"][name] = str(exc)
                collected["payloads"][name] = None

        run_payload = collected["payloads"].get("run")
        sample_endpoint_id = _resolve_taxonomy_sample_endpoint_id(api, run_payload)
        collected["payloads"]["taxonomy_sample_id"] = sample_endpoint_id
        if sample_endpoint_id:
            sample_q = urllib.parse.quote(sample_endpoint_id, safe="")
            try:
                collected["payloads"]["taxonomy"] = fetch_json(api, f"/samples/{sample_q}/taxonomy?run_id={quoted}")
            except urllib.error.HTTPError as exc:
                collected["fetch_errors"]["taxonomy"] = f"HTTP {exc.code}: {exc.reason}"
                collected["payloads"]["taxonomy"] = None
            except Exception as exc:  # noqa: BLE001
                collected["fetch_errors"]["taxonomy"] = str(exc)
                collected["payloads"]["taxonomy"] = None

    payloads = collected["payloads"]
    checks = evaluate_run_gate(
        health=payloads.get("health") or {},
        version=payloads.get("version") or {},
        settings=payloads.get("settings") or {},
        run=payloads.get("run"),
        steps=payloads.get("steps"),
        events=payloads.get("events"),
        taxonomy=payloads.get("taxonomy"),
        bundle_verify=payloads.get("bundle_verify"),
        require_worker_queue=require_worker_queue,
    )
    collected["checks"] = checks
    collected["summary"] = {
        "status": "pass" if all(item["status"] == "pass" for item in checks) else "fail",
        "passed": sum(1 for item in checks if item["status"] == "pass"),
        "failed": sum(1 for item in checks if item["status"] == "fail"),
    }
    return collected


def collect_frontend(frontend: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for route in FRONTEND_ROUTES:
        try:
            status, body = fetch_text(frontend, route)
            has_shell = "__next" in body or "_next" in body or "<main" in body or "<div" in body
            checks.append(check(f"frontend{route}", status == 200 and has_shell, f"HTTP {status}, shell={has_shell}"))
        except urllib.error.HTTPError as exc:
            checks.append(check(f"frontend{route}", False, f"HTTP {exc.code}: {exc.reason}"))
        except Exception as exc:  # noqa: BLE001
            checks.append(check(f"frontend{route}", False, str(exc)))
    return checks


def _resolve_taxonomy_sample_endpoint_id(api: str, run: dict[str, Any] | None) -> str | None:
    """Resolve the sample identifier expected by /samples/{sample}/taxonomy.

    Runs store the internal sample primary key, while taxonomy endpoints accept
    either the human sample id or the primary key. Prefer the human id when it
    is discoverable so the collected evidence mirrors what operators see in UI.
    """
    if not isinstance(run, dict):
        return None
    sample_pk = str(run.get("sample_id") or "").strip()
    project_id = str(run.get("project_id") or "").strip()
    if project_id:
        try:
            samples_payload = fetch_json(api, f"/projects/{urllib.parse.quote(project_id, safe='')}/samples")
            for sample in _items(samples_payload):
                if str(sample.get("id") or "") == sample_pk:
                    return str(sample.get("sample_id") or sample_pk)
        except Exception:  # noqa: BLE001 - caller records taxonomy fetch separately
            pass
    return sample_pk or None


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only real full-WGS validation gate")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--frontend", default=None, help="Optional frontend base URL for route checks")
    parser.add_argument("--run-id", default=None, help="Completed full-WGS run id to validate")
    parser.add_argument("--require-worker-queue", action="store_true", help="Fail unless /pipeline/settings reports worker_queue")
    parser.add_argument("--out", default=None, help="Optional JSON output path")
    args = parser.parse_args()

    report = collect(args.api, args.run_id, args.require_worker_queue)
    if args.frontend:
        frontend_checks = collect_frontend(args.frontend)
        report["checks"].extend(frontend_checks)
        report["summary"] = {
            "status": "pass" if all(item["status"] == "pass" for item in report["checks"]) else "fail",
            "passed": sum(1 for item in report["checks"] if item["status"] == "pass"),
            "failed": sum(1 for item in report["checks"] if item["status"] == "fail"),
        }
    for item in report["checks"]:
        mark = "OK" if item["status"] == "pass" else "FAIL"
        print(f"[{mark}] {item['name']}: {item['detail']}")

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True))
        print(f"Wrote {path}")

    return 0 if report["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
