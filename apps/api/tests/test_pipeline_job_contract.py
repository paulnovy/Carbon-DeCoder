from pathlib import Path

import pytest
from fastapi import HTTPException

from app.pipeline_contract import PipelineJob, decode_pipeline_job, encode_pipeline_job, pipeline_job_runner_args
from app.routers import foundation
from app.db.models import Project, ReferenceGenome, Run, Sample
from app.store.memory_store import projects, run_events, run_logs, run_steps, runs, samples


def _reset_pipeline_stores():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()


def _seed_pipeline_run(tmp_path: Path) -> tuple[Sample, Run, Path]:
    _reset_pipeline_stores()
    input_path = tmp_path / "S1_R1.fastq.gz"
    input_path.write_bytes(b"fastq")
    sample = Sample(id="sample_1", project_id="p1", sample_id="S1", reference_id="GRCh38_standard")
    run = Run(id="run_1", project_id="p1", sample_id=sample.id, mode="full", reference_id="GRCh38_standard", status="queued", parameters={})
    samples.append(sample)
    runs.append(run)
    foundation._append_step(run.id, "input_validation", status="done")
    for stage in foundation.PIPELINE_STAGES:
        foundation._append_step(run.id, stage)
    return sample, run, input_path


def _patch_pipeline_runner(monkeypatch, tmp_path: Path, stage_results: dict[str, str]):
    calls = []
    reference = tmp_path / "ref.fa"
    reference.write_text(">chr1\nACGT\n", encoding="utf-8")

    monkeypatch.setattr(foundation, "_reference_pipeline_preflight", lambda _ref, _stages: {"ready": True})
    monkeypatch.setattr(foundation, "_resolve_reference_fasta", lambda _ref: reference)
    monkeypatch.setattr(foundation, "_resolve_pipeline_input", lambda path: path)
    monkeypatch.setattr(foundation, "_check_stage_tools", lambda _stage: (True, []))
    monkeypatch.setattr(foundation, "_optional_stage_preflight_skip", lambda _stage, _reference: None)
    monkeypatch.setattr(foundation, "_resource_plan", lambda: {"threads": 1, "effective_profile": "test"})
    monkeypatch.setattr(foundation, "_auto_ingest", lambda *_args, **_kwargs: None)

    def fake_run_stage(stage_name, *_args, **_kwargs):
        calls.append(stage_name)
        return {
            "stage": stage_name,
            "status": stage_results.get(stage_name, "done"),
            "reason": f"{stage_name}_simulated",
            "stdout": "",
            "stderr": "",
            "output_dir": str(tmp_path / "results"),
        }

    monkeypatch.setattr(foundation, "_run_stage_script", fake_run_stage)
    return calls


def test_pipeline_job_contract_round_trips_without_runtime_objects():
    job = PipelineJob(
        run_id="run_1",
        sample_id="S1",
        input_files=["/data/input/S1_R1.fastq.gz", "/data/input/S1_R2.fastq.gz"],
        reference_id="GRCh38_standard",
        stages=["alignment", "coverage", "variants"],
        allow_dev_fallback=True,
        stop_on_failure=False,
        required_stages=["alignment", "coverage", "variants"],
        profile_name="core_variants",
        optional_tools_missing=[{"stage": "cnv", "missing": ["cnvkit.py"]}],
        stage_plan={"from_stage": "coverage", "final_stages": ["coverage", "variants"]},
        stage_options={"taxonomy_database": "standard"},
    )

    payload = job.model_dump()
    assert payload["run_id"] == "run_1"
    assert payload["profile_name"] == "core_variants"
    assert payload["optional_tools_missing"][0]["stage"] == "cnv"
    assert payload["stage_plan"]["from_stage"] == "coverage"
    assert payload["stage_options"]["taxonomy_database"] == "standard"

    restored = PipelineJob(**payload)
    assert restored == job

    encoded = encode_pipeline_job(job)
    assert '"run_id":"run_1"' in encoded
    assert decode_pipeline_job(encoded) == job

    runner_args = pipeline_job_runner_args(job)
    assert runner_args[0] == "run_1"
    assert runner_args[7] == {"alignment", "coverage", "variants"}


def test_stage_plan_helpers_order_and_dedupe_stages():
    assert foundation._validate_stage_list(["coverage", "coverage", "variants"], "only_stages") == ["coverage", "variants"]
    assert foundation._ordered_stage_subset(["prs", "coverage", "alignment"]) == ["alignment", "coverage", "prs"]


def test_pipeline_executor_defaults_to_api_thread(monkeypatch):
    monkeypatch.delenv(foundation.PIPELINE_EXECUTOR_ENV, raising=False)
    assert foundation._pipeline_executor() == "api_thread"


def test_pipeline_executor_accepts_worker_queue(monkeypatch):
    monkeypatch.setenv(foundation.PIPELINE_EXECUTOR_ENV, "worker_queue")
    assert foundation._pipeline_executor() == "worker_queue"


def test_pipeline_executor_falls_back_for_unknown_value(monkeypatch):
    monkeypatch.setenv(foundation.PIPELINE_EXECUTOR_ENV, "oops")
    assert foundation._pipeline_executor() == "api_thread"


def test_taxonomy_subrun_inherits_parent_alignment_bam(tmp_path, monkeypatch):
    _reset_pipeline_stores()
    project = Project(id="p1", name="P1")
    sample = Sample(id="sample_1", project_id=project.id, sample_id="S1", reference_id="GRCh38_standard")
    parent = Run(id="run_parent", project_id=project.id, sample_id=sample.id, mode="full", reference_id="GRCh38_standard", status="done")
    projects.append(project)
    samples.append(sample)
    runs.append(parent)
    parent_out = tmp_path / "results" / parent.id
    parent_out.mkdir(parents=True)
    bam = parent_out / "S1.sorted.markdup.bam"
    bai = parent_out / "S1.sorted.markdup.bam.bai"
    bam.write_bytes(b"bam")
    bai.write_bytes(b"bai")
    reference = tmp_path / "ref.fa"
    reference.write_text(">chr1\nACGT\n", encoding="utf-8")

    dispatched = []
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(foundation, "_valid_bam_checkpoint", lambda _path: True)
    monkeypatch.setattr(foundation, "_bam_pipeline_preflight", lambda _path: {"ready": True})
    monkeypatch.setattr(foundation, "_resolve_taxonomy_database_path", lambda db: f"/data/databases/kraken2/{db}")
    monkeypatch.setattr(foundation, "_reference_pipeline_preflight", lambda _ref, _stages: {"ready": True})
    monkeypatch.setattr(foundation, "_resolve_reference_fasta", lambda _ref: reference)
    monkeypatch.setattr(foundation, "_resolve_pipeline_input", lambda path: path)
    monkeypatch.setattr(foundation, "_check_stage_tools", lambda _stage: (True, []))
    monkeypatch.setattr(foundation, "_validate_selected_backends", lambda _stages: [])
    monkeypatch.setattr(foundation, "_dispatch_pipeline_job", lambda job: dispatched.append(job))

    result = foundation.start_taxonomy_subrun(
        parent.id,
        foundation.TaxonomySubrunRequest(
            taxonomy_database="standard",
            taxonomy_route="human_wgs_host_depleted",
            taxonomy_low_mapq_threshold=10,
        ),
    )

    assert result["status"] == "started"
    assert result["parent_run_id"] == parent.id
    assert result["inherited_input"] == "parent_alignment_bam"
    subrun = next(run for run in runs if run.id == result["subrun_id"])
    assert subrun.mode == "taxonomy"
    assert subrun.parameters["parent_run_id"] == parent.id
    assert dispatched[0].input_files == [str(bam)]
    assert dispatched[0].stages == ["taxonomy"]
    assert dispatched[0].stage_options["taxonomy_database"] == "standard"
    parent_events = [event for event in run_events if event.run_id == parent.id]
    assert any(event.event_type == "taxonomy_subrun_created" for event in parent_events)


def test_pipeline_settings_response_includes_resource_plan(monkeypatch):
    settings = {"backends": {"alignment": "auto"}, "disk_pressure": {}, "taxonomy": {}}
    monkeypatch.setattr(foundation, "_pipeline_settings", lambda: settings)
    monkeypatch.setattr(foundation, "_pipeline_backend_status", lambda current: {"alignment": {}})
    monkeypatch.setattr(foundation, "_resource_plan", lambda: {"effective_profile": "standard", "threads": 4})

    data = foundation.get_pipeline_settings()

    assert data["settings"] == settings
    assert data["resource_plan"] == {"effective_profile": "standard", "threads": 4}


def test_compute_profile_controls_pipeline_threads(monkeypatch):
    monkeypatch.delenv(foundation.PIPELINE_THREADS_ENV, raising=False)
    monkeypatch.setenv(foundation.COMPUTE_PROFILE_ENV, "lowmem")
    assert foundation._compute_profile() == "lowmem"
    assert foundation._pipeline_threads() == 2


def test_auto_compute_profile_uses_ram_and_cpu_shape():
    assert foundation._auto_compute_profile(cpu_threads=8, ram_bytes=32 * 1024 ** 3) == "lowmem"
    assert foundation._auto_compute_profile(cpu_threads=32, ram_bytes=256 * 1024 ** 3) == "highmem"
    assert foundation._auto_compute_profile(cpu_threads=8, ram_bytes=64 * 1024 ** 3) == "standard"


def test_pipeline_threads_override_compute_profile(monkeypatch):
    monkeypatch.setenv(foundation.COMPUTE_PROFILE_ENV, "lowmem")
    monkeypatch.setenv(foundation.PIPELINE_THREADS_ENV, "8")
    assert foundation._pipeline_threads() == 8


def test_resource_plan_records_full_backend_policy(monkeypatch):
    monkeypatch.setenv(foundation.COMPUTE_PROFILE_ENV, "standard")
    monkeypatch.delenv(foundation.PIPELINE_THREADS_ENV, raising=False)
    monkeypatch.setattr(foundation, "_host_ram_bytes", lambda: 64 * 1024**3)
    monkeypatch.setattr(foundation, "_gpu_available", lambda: False)
    monkeypatch.setattr(
        foundation,
        "_pipeline_settings",
        lambda: {
            "backends": {
                "alignment": "bwa-mem2",
                "coverage": "mosdepth",
                "variants": "deepvariant",
                "sv": "delly",
                "cnv": "cnvkit",
                "taxonomy": "kraken2",
                "mtdna": "gatk",
                "prs": "auto",
            },
            "disk_pressure": {"min_free_gb_before_markdup": 120},
        },
    )

    plan = foundation._resource_plan()

    assert plan["backend_policy"] == {
        "alignment": "bwa-mem2",
        "coverage": "mosdepth",
        "variants": "deepvariant",
        "sv": "delly",
        "cnv": "cnvkit",
        "taxonomy": "kraken2",
        "mtdna": "gatk",
        "prs": "auto",
    }
    assert plan["reference_index_policy"] == "classic_bwa_low_memory"
    assert plan["silent_gpu_fallback"] is False


def test_taxonomy_route_settings_validate_and_clamp(monkeypatch):
    monkeypatch.setattr(
        foundation,
        "_pipeline_settings",
        lambda: {
            "backends": {"alignment": "auto"},
            "disk_pressure": {},
            "taxonomy": {"default_route": "human_wgs_sensitive_low_mapq", "low_mapq_threshold": 99},
        },
    )

    assert foundation._resolve_taxonomy_route(None) == "human_wgs_sensitive_low_mapq"
    assert foundation._taxonomy_low_mapq_threshold(None) == 60


def test_pipeline_settings_accept_all_configurable_stage_backends(tmp_path, monkeypatch):
    monkeypatch.setattr(foundation, "PIPELINE_SETTINGS_PATH", tmp_path / "pipeline_settings.json")

    saved = foundation._save_pipeline_settings(
        {
            "backends": {
                "alignment": "bwa-mem2",
                "coverage": "mosdepth",
                "variants": "deepvariant",
                "sv": "delly",
                "cnv": "cnvkit",
                "taxonomy": "kraken2",
                "mtdna": "gatk",
                "prs": "auto",
            }
        }
    )

    assert saved["backends"]["alignment"] == "bwa-mem2"
    assert saved["backends"]["variants"] == "deepvariant"
    assert saved["backends"]["mtdna"] == "gatk"
    assert saved["backends"]["prs"] == "auto"

    saved_gatk = foundation._save_pipeline_settings({"backends": {"variants": "gatk"}})
    assert saved_gatk["backends"]["variants"] == "gatk"


def test_variant_backend_selection_routes_api_stage_scripts(monkeypatch):
    monkeypatch.setattr(foundation, "_pipeline_settings", lambda: {"backends": {"variants": "bcftools"}})
    assert foundation._stage_script_name("variants") == "run_bcftools_variant_calling_stage.sh"

    monkeypatch.setattr(foundation, "_pipeline_settings", lambda: {"backends": {"variants": "gatk"}})
    assert foundation._stage_script_name("variants") == "run_gatk_variant_calling_stage.sh"

    monkeypatch.setattr(foundation, "_pipeline_settings", lambda: {"backends": {"variants": "deepvariant"}})
    assert foundation._stage_script_name("variants") == "run_deepvariant_stage.sh"
    assert foundation._stage_script_name("variants", {"variant_caller": "bcftools"}) == "run_bcftools_variant_calling_stage.sh"


def test_variant_stage_tool_check_follows_selected_backend(monkeypatch):
    monkeypatch.setattr(foundation, "_pipeline_settings", lambda: {"backends": {"variants": "deepvariant"}})
    monkeypatch.setattr(foundation.shutil, "which", lambda name: "/usr/bin/run_deepvariant" if name == "run_deepvariant" else None)

    ok, missing = foundation._check_stage_tools("variants")

    assert ok is True
    assert missing == []


def test_pipeline_disk_preflight_reports_warning_when_estimate_exceeds_free(tmp_path, monkeypatch):
    fastq = tmp_path / "S1_R1.fastq.gz"
    fastq.write_bytes(b"x" * 1024)
    monkeypatch.setattr(
        foundation,
        "_pipeline_settings",
        lambda: {
            "backends": {"alignment": "auto"},
            "disk_pressure": {
                "alignment_peak_multiplier": 5.0,
                "min_free_gb_before_markdup": 10**9,
                "block_start_when_estimate_exceeds_free": False,
                "scratch_root": "",
            },
            "taxonomy": {"default_route": "human_wgs_host_depleted", "low_mapq_threshold": 10},
        },
    )

    result = foundation._pipeline_disk_preflight([str(fastq)], ["alignment"], tmp_path / "results" / "run_1")

    assert result["status"] == "warning"
    assert result["estimated_peak_bytes"] >= 240 * 1024 ** 3
    assert result["min_free_gb_before_markdup"] == 10**9


def test_taxonomy_stage_plan_requires_host_bam_when_alignment_not_planned(tmp_path, monkeypatch):
    monkeypatch.setattr(foundation, "PIPELINE_RESULTS_ROOT", tmp_path)
    sample = Sample(id="sample_1", project_id="p1", sample_id="S1", reference_id="GRCh38_standard")
    run = Run(id="run_1", project_id="p1", sample_id=sample.id, mode="full", reference_id="GRCh38_standard")

    with pytest.raises(HTTPException) as exc:
        foundation._validate_stage_dependencies(run, sample, ["taxonomy"], [])

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "stage_plan_missing_final_bam"


def test_failed_alignment_blocks_dependent_stages_even_without_stop_on_failure(tmp_path, monkeypatch):
    sample, run, input_path = _seed_pipeline_run(tmp_path)
    calls = _patch_pipeline_runner(monkeypatch, tmp_path, {"alignment": "failed"})
    stages = ["alignment", "coverage", "variants", "prs"]

    foundation._run_pipeline_background(
        run.id,
        sample.sample_id,
        [str(input_path)],
        run.reference_id,
        stages,
        allow_dev_fallback=True,
        stop_on_failure=False,
        required_stages=set(stages),
    )

    statuses = {step.step_name: step.status for step in run_steps if step.run_id == run.id}
    assert calls == ["alignment"]
    assert statuses["alignment"] == "failed"
    assert statuses["coverage"] == "blocked"
    assert statuses["variants"] == "blocked"
    assert statuses["prs"] == "blocked"
    assert run.status == "failed"
    assert any(event.event_type == "coverage_blocked" for event in run_events)


def test_stop_on_failure_distinguishes_policy_skip_from_dependency_block(tmp_path, monkeypatch):
    sample, run, input_path = _seed_pipeline_run(tmp_path)
    calls = _patch_pipeline_runner(monkeypatch, tmp_path, {"coverage": "failed"})
    stages = ["alignment", "coverage", "variants", "prs"]

    foundation._run_pipeline_background(
        run.id,
        sample.sample_id,
        [str(input_path)],
        run.reference_id,
        stages,
        allow_dev_fallback=True,
        stop_on_failure=True,
        required_stages=set(stages),
    )

    statuses = {step.step_name: step.status for step in run_steps if step.run_id == run.id}
    assert calls == ["alignment", "coverage"]
    assert statuses["alignment"] == "done"
    assert statuses["coverage"] == "failed"
    assert statuses["variants"] == "skipped"
    assert statuses["prs"] == "blocked"
    assert run.status == "failed"
    finished = next(event for event in run_events if event.event_type == "pipeline_aborted")
    assert {item["stage"]: item["status"] for item in finished.payload["skipped"]} == {
        "variants": "skipped",
        "prs": "blocked",
    }


def test_parse_redis_url_defaults_and_custom_values():
    assert foundation._parse_redis_url("redis://redis:6379/0") == ("redis", 6379)
    assert foundation._parse_redis_url("redis://localhost:6380/2") == ("localhost", 6380)
    assert foundation._parse_redis_url("redis://:secret@cache:6379/0") == ("cache", 6379)


def test_enqueue_pipeline_job_uses_lpush(monkeypatch):
    captured = {}

    def fake_redis_command(*parts, **kwargs):
        captured["parts"] = parts
        return b":1\r\n"

    monkeypatch.setenv(foundation.PIPELINE_JOB_QUEUE_ENV, "test:pipeline")
    monkeypatch.setattr(foundation, "_redis_command", fake_redis_command)
    job = PipelineJob(run_id="run_1", sample_id="S1", reference_id="GRCh38_chr20")

    info = foundation._enqueue_pipeline_job(job)

    assert info["queue"] == "test:pipeline"
    assert captured["parts"][:2] == ("LPUSH", "test:pipeline")
    assert '"run_id":"run_1"' in captured["parts"][2]


def test_reference_pipeline_preflight_requires_aligner_index_for_alignment(tmp_path, monkeypatch):
    fasta = tmp_path / "GRCh38.fa"
    fasta.write_text(">chr1\nACGT\n", encoding="utf-8")
    Path(str(fasta) + ".fai").write_text("chr1\t4\t6\t4\t5\n", encoding="utf-8")
    monkeypatch.setattr(foundation, "_pipeline_settings", lambda: {"backends": {"alignment": "bwa"}})
    monkeypatch.setattr(foundation, "_backend_tool_available", lambda backend: backend == "bwa")
    monkeypatch.setattr(
        foundation,
        "references",
        [ReferenceGenome(id="GRCh38_test", version="test", source="test", contig_style="chr", fasta_path=str(fasta))],
    )

    result = foundation._reference_pipeline_preflight("GRCh38_test", ["alignment", "coverage"])

    assert result["ready"] is False
    assert result["code"] == "reference_bwa_index_missing"
    assert str(fasta) + ".bwt" in result["missing"]


def test_reference_pipeline_preflight_accepts_complete_bwa_mem2_index(tmp_path, monkeypatch):
    fasta = tmp_path / "GRCh38.fa"
    fasta.write_text(">chr1\nACGT\n", encoding="utf-8")
    for suffix in [".fai", ".0123", ".amb", ".ann", ".bwt.2bit.64", ".pac"]:
        Path(str(fasta) + suffix).write_text("index\n", encoding="utf-8")
    monkeypatch.setattr(foundation, "_pipeline_settings", lambda: {"backends": {"alignment": "bwa-mem2"}})
    monkeypatch.setattr(foundation, "_backend_tool_available", lambda backend: backend == "bwa-mem2")
    monkeypatch.setattr(
        foundation,
        "references",
        [ReferenceGenome(id="GRCh38_test", version="test", source="test", contig_style="chr", fasta_path=str(fasta))],
    )

    result = foundation._reference_pipeline_preflight("GRCh38_test", ["alignment", "coverage"])

    assert result["ready"] is True


def test_reference_pipeline_preflight_accepts_complete_classic_bwa_index(tmp_path, monkeypatch):
    fasta = tmp_path / "GRCh38.fa"
    fasta.write_text(">chr1\nACGT\n", encoding="utf-8")
    for suffix in [".fai", ".amb", ".ann", ".bwt", ".pac", ".sa"]:
        Path(str(fasta) + suffix).write_text("index\n", encoding="utf-8")
    monkeypatch.setattr(foundation, "_pipeline_settings", lambda: {"backends": {"alignment": "bwa"}})
    monkeypatch.setattr(foundation, "_backend_tool_available", lambda backend: backend == "bwa")
    monkeypatch.setattr(
        foundation,
        "references",
        [ReferenceGenome(id="GRCh38_test", version="test", source="test", contig_style="chr", fasta_path=str(fasta))],
    )

    result = foundation._reference_pipeline_preflight("GRCh38_test", ["alignment", "coverage"])

    assert result["ready"] is True


def test_reference_pipeline_preflight_rejects_selected_bwa_mem2_without_mem2_index(tmp_path, monkeypatch):
    fasta = tmp_path / "GRCh38.fa"
    fasta.write_text(">chr1\nACGT\n", encoding="utf-8")
    for suffix in [".fai", ".amb", ".ann", ".bwt", ".pac", ".sa"]:
        Path(str(fasta) + suffix).write_text("classic index\n", encoding="utf-8")
    monkeypatch.setattr(foundation, "_pipeline_settings", lambda: {"backends": {"alignment": "bwa-mem2"}})
    monkeypatch.setattr(foundation, "_backend_tool_available", lambda backend: backend == "bwa-mem2")
    monkeypatch.setattr(
        foundation,
        "references",
        [ReferenceGenome(id="GRCh38_test", version="test", source="test", contig_style="chr", fasta_path=str(fasta))],
    )

    result = foundation._reference_pipeline_preflight("GRCh38_test", ["alignment", "coverage"])

    assert result["ready"] is False
    assert result["code"] == "reference_bwa_mem2_index_missing"
    assert str(fasta) + ".bwt.2bit.64" in result["missing"]
