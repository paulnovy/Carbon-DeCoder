#!/usr/bin/env python3
"""Seed synthetic run data into Postgres from /data/results/ directories.

Run inside the API container:
  docker exec -it <api_container> python scripts/seed_synthetic.py

Or from the host:
  docker compose exec api python scripts/seed_synthetic.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "/app")

from app.db.database import SessionLocal, engine, init_db
from app.db import sql_models as sm

RESULTS_DIR = Path("/data/results")
PROJECT_ID = "proj_synthetic"
PROJECT_NAME = "Synthetic WGS Test Data"
SAMPLE_PREFIX = "SYN_chr20"
REFERENCE_ID = "GRCh38_chr20"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def discover_runs() -> list[dict]:
    """Scan /data/results/run_* directories and extract metadata."""
    runs = []
    if not RESULTS_DIR.is_dir():
        print(f"[seed] ERROR: {RESULTS_DIR} not found")
        return runs

    for d in sorted(RESULTS_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("run_"):
            continue

        run_id = d.name
        files = [f.name for f in d.iterdir() if f.is_file()]

        # Try to find ingest metadata
        ingest_meta = {}
        for meta_name in ("ingest.json", "manifest.json", "run_meta.json"):
            meta_path = d / meta_name
            if meta_path.exists():
                try:
                    ingest_meta = json.loads(meta_path.read_text())
                except Exception:
                    pass

        # Detect what outputs exist
        has_vcf = any(f.endswith((".vcf", ".vcf.gz")) for f in files)
        has_bam = any(f.endswith((".bam", ".bam.bai", ".cram")) for f in files)
        has_coverage = any("coverage" in f.lower() or "mosdepth" in f.lower() for f in files)
        has_qc = any("fastp" in f.lower() or "multiqc" in f.lower() for f in files)
        has_reports = any(f.endswith(".html") for f in files)

        status = "completed" if has_vcf else "partial"

        runs.append({
            "id": run_id,
            "dir": d,
            "files": files,
            "ingest_meta": ingest_meta,
            "has_vcf": has_vcf,
            "has_bam": has_bam,
            "has_coverage": has_coverage,
            "has_qc": has_qc,
            "has_reports": has_reports,
            "status": status,
        })

    return runs


def seed_database(run_infos: list[dict]) -> None:
    """Insert Project, Sample, Run records into Postgres."""
    if not engine or not SessionLocal:
        print("[seed] ERROR: no database engine — check DATABASE_URL / RUNNING_IN_DOCKER")
        sys.exit(1)

    init_db()

    with SessionLocal() as session:
        # --- Project ---
        existing_project = session.get(sm.Project, PROJECT_ID)
        if not existing_project:
            session.add(sm.Project(
                id=PROJECT_ID,
                name=PROJECT_NAME,
                description=f"Auto-seeded synthetic test data ({len(run_infos)} runs)",
                created_at=utc_now(),
            ))
            print(f"[seed] + project: {PROJECT_ID}")
        else:
            print(f"[seed] = project already exists: {PROJECT_ID}")

        # --- Reference genome ---
        existing_ref = session.get(sm.ReferenceGenome, REFERENCE_ID)
        if not existing_ref:
            session.add(sm.ReferenceGenome(
                id=REFERENCE_ID,
                version="GRCh38-chr20",
                source="UCSC chr20 (synthetic test reference)",
                contig_style="chr",
                status="available",
                aliases=["chr20", "hg38_chr20"],
                mitochondrial_contig="chrM",
            ))
            print(f"[seed] + reference: {REFERENCE_ID}")
        else:
            print(f"[seed] = reference already exists: {REFERENCE_ID}")

        # --- Samples + Runs ---
        for ri in run_infos:
            run_id = ri["id"]
            sample_id = f"{SAMPLE_PREFIX}_{run_id}"

            # Sample
            existing_sample = session.get(sm.Sample, sample_id)
            if not existing_sample:
                session.add(sm.Sample(
                    id=sample_id,
                    project_id=PROJECT_ID,
                    sample_id=sample_id,
                    reference_id=REFERENCE_ID,
                    r1_path=None,
                    r2_path=None,
                    created_at=utc_now(),
                ))
                print(f"[seed] + sample: {sample_id}")

            # Run
            existing_run = session.get(sm.Run, run_id)
            if not existing_run:
                now = utc_now()
                session.add(sm.Run(
                    id=run_id,
                    project_id=PROJECT_ID,
                    sample_id=sample_id,
                    mode="wgs",
                    status=ri["status"],
                    reference_id=REFERENCE_ID,
                    pipeline_version="0.4.0-synthetic",
                    parameters={"synthetic": True, "chr20_subset": True},
                    created_at=now,
                    updated_at=now,
                ))
                print(f"[seed] + run: {run_id} ({ri['status']})")
            else:
                print(f"[seed] = run already exists: {run_id}")

        session.commit()

    print(f"\n[seed] DONE: {len(run_infos)} runs seeded into project '{PROJECT_ID}'")
    print(f"[seed] Verify: GET /projects → should show {PROJECT_ID}")
    print(f"[seed] Verify: GET /samples → should show {len(run_infos)} samples")


def main():
    print(f"[seed] Scanning {RESULTS_DIR}...")
    run_infos = discover_runs()
    print(f"[seed] Found {len(run_infos)} run directories")

    if not run_infos:
        print("[seed] No runs to seed. Exiting.")
        return

    completed = sum(1 for r in run_infos if r["status"] == "completed")
    print(f"[seed] {completed} completed, {len(run_infos) - completed} partial")

    seed_database(run_infos)


if __name__ == "__main__":
    main()
