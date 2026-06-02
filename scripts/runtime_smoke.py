#!/usr/bin/env python3
"""Small runtime smoke gate for deployed WGS Cockpit services.

Checks only contract-level availability and persistence-safe read endpoints.
It intentionally does not start a pipeline or mutate data.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # nosec: operator-provided URL
        payload = res.read().decode("utf-8")
    return json.loads(payload)


def fetch_status(url: str, timeout: float = 10.0) -> int:
    req = urllib.request.Request(url, headers={"accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # nosec: operator-provided URL
        return int(res.status)


def fetch_frontend_page(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """Fetch a frontend page, return (status_code, body_snippet)."""
    req = urllib.request.Request(url, headers={"accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # nosec: operator-provided URL
        body = res.read(8192).decode("utf-8", errors="replace")
        return int(res.status), body


def main() -> int:
    parser = argparse.ArgumentParser(description="Runtime smoke gate for WGS Cockpit")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--frontend", default="http://localhost:3000", help="Frontend base URL")
    args = parser.parse_args()

    checks: list[tuple[str, bool, str]] = []

    try:
        health = fetch_json(f"{args.api.rstrip('/')}/health")
        checks.append(("api /health", bool(health.get("ok")), json.dumps(health, sort_keys=True)))
    except Exception as exc:  # noqa: BLE001 - smoke script should report all failures
        checks.append(("api /health", False, str(exc)))

    try:
        refs = fetch_json(f"{args.api.rstrip('/')}/references")
        items = refs.get("items", [])
        checks.append(("api /references", len(items) >= 1, f"{len(items)} references"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("api /references", False, str(exc)))

    try:
        profiles = fetch_json(f"{args.api.rstrip('/')}/pipelines/profiles")
        items = profiles.get("items", [])
        checks.append(("api /pipelines/profiles", len(items) >= 1, f"{len(items)} profiles"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("api /pipelines/profiles", False, str(exc)))

    try:
        status = fetch_status(args.frontend.rstrip("/"))
        checks.append(("frontend /", 200 <= status < 500, f"HTTP {status}"))
    except urllib.error.HTTPError as exc:
        checks.append(("frontend /", exc.code < 500, f"HTTP {exc.code}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("frontend /", False, str(exc)))

    # Frontend route smoke: verify pages return 200 and contain Next.js app shell
    frontend_routes = ["/runs", "/references", "/data-import", "/genome", "/insights", "/variants"]
    for route in frontend_routes:
        try:
            code, body = fetch_frontend_page(f"{args.frontend.rstrip('/')}{route}")
            has_shell = "__next" in body or "_next" in body or "<div" in body
            checks.append((f"frontend {route}", code == 200 and has_shell, f"HTTP {code}, has shell={has_shell}"))
        except urllib.error.HTTPError as exc:
            checks.append((f"frontend {route}", False, f"HTTP {exc.code}"))
        except Exception as exc:  # noqa: BLE001
            checks.append((f"frontend {route}", False, str(exc)))

    ok = True
    for name, passed, detail in checks:
        mark = "OK" if passed else "FAIL"
        print(f"[{mark}] {name}: {detail}")
        ok = ok and passed

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
