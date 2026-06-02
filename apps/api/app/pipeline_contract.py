"""Serializable pipeline runner contract shared by API dispatch and worker."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class PipelineJob(BaseModel):
    """Durable payload for API-thread and worker-queue pipeline execution."""

    run_id: str
    sample_id: str
    input_files: list[str] = Field(default_factory=list)
    reference_id: str
    stages: list[str] = Field(default_factory=list)
    allow_dev_fallback: bool = True
    stop_on_failure: bool = False
    required_stages: list[str] = Field(default_factory=list)
    profile_name: str | None = None
    optional_tools_missing: list[dict[str, Any]] = Field(default_factory=list)
    stage_plan: dict[str, Any] = Field(default_factory=dict)
    stage_options: dict[str, Any] = Field(default_factory=dict)


def encode_pipeline_job(job: PipelineJob) -> str:
    return json.dumps(job.model_dump(), ensure_ascii=False, separators=(",", ":"))


def decode_pipeline_job(payload: str) -> PipelineJob:
    return PipelineJob(**json.loads(payload))


def pipeline_job_runner_args(job: PipelineJob) -> tuple:
    """Return positional args for the current legacy runner function."""

    return (
        job.run_id,
        job.sample_id,
        job.input_files,
        job.reference_id,
        job.stages,
        job.allow_dev_fallback,
        job.stop_on_failure,
        set(job.required_stages),
        job.profile_name,
        job.optional_tools_missing,
        job.stage_options,
    )
