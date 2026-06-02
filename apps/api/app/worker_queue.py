"""Pipeline worker queue entrypoint.

This module intentionally runs inside the API image so the worker has the same
bioinformatics toolchain and Python app code as the API container. It is kept
feature-flagged by Compose/env until runtime validation is complete.
"""

from __future__ import annotations

import os
import time

from app.pipeline_contract import PipelineJob, decode_pipeline_job, pipeline_job_runner_args
from app.routers.foundation import (
    PIPELINE_JOB_QUEUE_DEFAULT,
    REDIS_URL_DEFAULT,
    _redis_command,
    _run_pipeline_background,
)
from app.store.memory_store import init_db


def _parse_brpop_response(response: bytes) -> tuple[str, str] | None:
    if response.startswith(b"*-1") or not response:
        return None
    parts = response.split(b"\r\n")
    if len(parts) >= 5 and parts[0] == b"*2":
        return parts[2].decode("utf-8", errors="replace"), parts[4].decode("utf-8", errors="replace")
    raise ValueError(f"unexpected_brpop_response:{response[:80]!r}")


def consume_pipeline_job_once(*, redis_url: str, queue_name: str, timeout_seconds: int = 5) -> tuple[bool, str]:
    response = _redis_command(
        "BRPOP",
        queue_name,
        str(timeout_seconds),
        redis_url=redis_url,
        timeout_seconds=timeout_seconds + 2,
    )
    item = _parse_brpop_response(response)
    if item is None:
        return True, "no_job"

    _, payload = item
    try:
        job = decode_pipeline_job(payload)
    except Exception as exc:
        return False, f"invalid_pipeline_job:{type(exc).__name__}"

    # Refresh DB-backed in-memory cache before each job. The worker is a long-running
    # process and jobs are usually created by the API after worker startup.
    init_db(recover_stale_running=False)

    print(f"pipeline worker: starting run_id={job.run_id} stages={job.stages}", flush=True)
    _run_pipeline_background(*pipeline_job_runner_args(job))
    return True, "pipeline_job_done"


def main() -> None:
    # Worker must not mark API-owned running jobs interrupted during startup.
    init_db(recover_stale_running=False)

    queue_name = os.getenv("WGS_PIPELINE_JOB_QUEUE", PIPELINE_JOB_QUEUE_DEFAULT).strip() or PIPELINE_JOB_QUEUE_DEFAULT
    redis_url = os.getenv("REDIS_URL", REDIS_URL_DEFAULT)
    interval_seconds = int(os.getenv("WGS_WORKER_INTERVAL_SECONDS", "5"))
    enabled = os.getenv("WGS_WORKER_PIPELINE_QUEUE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    if not enabled:
        print("pipeline worker disabled: set WGS_WORKER_PIPELINE_QUEUE_ENABLED=true", flush=True)

    while True:
        if enabled:
            ok, status = consume_pipeline_job_once(
                redis_url=redis_url,
                queue_name=queue_name,
                timeout_seconds=min(interval_seconds, 10),
            )
            print(f"pipeline worker result: ok={ok} status={status}", flush=True)
        else:
            print("pipeline worker heartbeat: disabled", flush=True)
            time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
