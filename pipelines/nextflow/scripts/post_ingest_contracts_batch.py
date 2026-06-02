#!/usr/bin/env python3
"""Find, validate and post many WGS Cockpit ingest contracts.

This is the operational companion to `post_ingest_contract.py`: a Nextflow run
can emit multiple `*.ingest.json` files for alignment/coverage/variants/etc.;
this script discovers them, validates stage/run_id/payload, optionally injects a
run id, and posts them in deterministic pipeline order.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

STAGE_ORDER = {
    "qc": 10,
    "alignment": 20,
    "coverage": 30,
    "variants": 40,
    "sv": 50,
    "cnv": 60,
    "mtdna": 70,
    "prs": 80,
    "taxonomy": 90,
    "benchmark": 100,
    "vendor_validation": 110,
}


def _load_single_module():
    sibling = Path(__file__).with_name("post_ingest_contract.py")
    spec = importlib.util.spec_from_file_location("post_ingest_contract", sibling)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot_load_post_ingest_contract_module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


single = _load_single_module()


def discover_contracts(root: Path, pattern: str) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob(pattern) if p.is_file())


PATH_LIKE_KEYS = {
    "flagstat_txt",
    "idxstats_txt",
    "mosdepth_summary_txt",
    "mosdepth_regions_bed_gz",
    "variants_vcf_path",
    "sv_vcf_path",
    "cnv_segments_tsv_path",
    "cnv_vcf_path",
    "mtdna_report_path",
    "prs_result_path",
    "taxonomy_report_path",
    "benchmark_report_path",
    "vendor_validation_report_path",
    "vendor_assembly_path",
    "pipeline_assembly_path",
}


def _absolutize_value(value: str, *, base_dir: Path) -> str:
    p = Path(value)
    if p.is_absolute() or not value or value.startswith(("http://", "https://")):
        return value
    return str((base_dir / p).resolve())


def absolutize_payload_paths(payload: dict[str, Any], *, base_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in PATH_LIKE_KEYS and isinstance(value, str):
            out[key] = _absolutize_value(value, base_dir=base_dir)
        elif key == "source_files" and isinstance(value, list):
            out[key] = [_absolutize_value(v, base_dir=base_dir) if isinstance(v, str) else v for v in value]
        else:
            out[key] = value
    return out


def validate_contract_path(path: Path, *, run_id: str | None, absolutize_paths: bool = False) -> dict[str, Any]:
    contract = single.load_contract(path)
    normalized = single.normalize_contract(contract, run_id_override=run_id)
    if absolutize_paths:
        normalized["payload"] = absolutize_payload_paths(normalized["payload"], base_dir=path.parent)
    return {"path": path, "normalized": normalized}


def sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    normalized = item["normalized"]
    path = item["path"]
    return (STAGE_ORDER.get(normalized["stage"], 999), normalized["stage"], str(path))


def result_for_validation_error(path: Path, exc: Exception) -> dict[str, Any]:
    return {"ok": False, "contract": str(path), "error": str(exc), "phase": "validation"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, type=Path, help="Directory to scan or a single contract file")
    ap.add_argument("--pattern", default="*.ingest.json")
    ap.add_argument("--api-base-url", default="http://api:8000")
    ap.add_argument("--run-id", help="Override/inject run_id for contracts emitted without one")
    ap.add_argument("--stage", action="append", help="Only include this stage; may be repeated")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--continue-on-error", action="store_true")
    ap.add_argument("--output", type=Path, help="Write batch result JSON here")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument(
        "--absolutize-payload-paths",
        action="store_true",
        help="Rewrite known relative file paths in payload/source_files relative to each contract directory",
    )
    args = ap.parse_args(argv)

    wanted_stages = {s.strip().lower() for s in args.stage or [] if s.strip()}
    paths = discover_contracts(args.root, args.pattern)

    results: list[dict[str, Any]] = []
    validated: list[dict[str, Any]] = []
    for path in paths:
        try:
            item = validate_contract_path(path, run_id=args.run_id, absolutize_paths=args.absolutize_payload_paths)
            if wanted_stages and item["normalized"]["stage"] not in wanted_stages:
                continue
            validated.append(item)
        except Exception as exc:  # validation should report all bad contracts in batch mode
            err = result_for_validation_error(path, exc)
            results.append(err)
            if not args.continue_on_error:
                break

    if not results or args.continue_on_error:
        for item in sorted(validated, key=sort_key):
            normalized = item["normalized"]
            contract_path = item["path"]
            url = f"{args.api_base_url.rstrip('/')}/runs/{normalized['run_id']}/ingest"
            if args.dry_run:
                results.append(
                    {
                        "ok": True,
                        "dry_run": True,
                        "contract": str(contract_path),
                        "stage": normalized["stage"],
                        "url": url,
                        "request": {"stage": normalized["stage"], "payload": normalized["payload"]},
                    }
                )
                continue

            status, response_text = single.post_contract(args.api_base_url, normalized, args.timeout)
            ok = 200 <= status < 300
            results.append(
                {
                    "ok": ok,
                    "dry_run": False,
                    "contract": str(contract_path),
                    "stage": normalized["stage"],
                    "status": status,
                    "response": response_text,
                    "url": url,
                }
            )
            if not ok and not args.continue_on_error:
                break

    summary = {
        "ok": bool(paths) and all(r.get("ok") for r in results),
        "dry_run": args.dry_run,
        "root": str(args.root),
        "pattern": args.pattern,
        "discovered_count": len(paths),
        "processed_count": len(results),
        "results": results,
    }
    if not paths:
        summary["ok"] = False
        summary["error"] = "no_contracts_found"

    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
