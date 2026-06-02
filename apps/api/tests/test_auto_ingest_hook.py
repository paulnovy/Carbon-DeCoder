from app.routers.foundation import (
    AutoIngestRequest,
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    auto_ingest_run_stage,
    create_project,
    create_run_full,
    create_sample,
)
from app.store.memory_store import (
    alignment_metrics,
    benchmark_records,
    cnv_segments,
    coverage_metrics,
    mtdna_results,
    prs_results,
    projects,
    reports,
    run_events,
    run_logs,
    run_steps,
    runs,
    samples,
    structural_variants,
    taxonomy_hits,
    variants,
    vendor_assembly_validations,
)


def _reset_stores():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()
    reports.clear()
    variants.clear()
    structural_variants.clear()
    cnv_segments.clear()
    mtdna_results.clear()
    prs_results.clear()
    taxonomy_hits.clear()
    benchmark_records.clear()
    alignment_metrics.clear()
    coverage_metrics.clear()
    vendor_assembly_validations.clear()


def test_auto_ingest_routes_alignment_and_coverage():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pingest"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_ingest", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    _ = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="alignment",
            payload={
                "mapped_reads_pct": 97.1,
                "properly_paired_pct": 95.2,
                "duplicates_pct": 12.0,
            },
        ),
    )

    _ = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="coverage",
            payload={
                "mean_coverage": 31.8,
                "median_coverage": 30.1,
                "callable_fraction": 0.946,
                "coverage_ge_20x": 0.919,
            },
        ),
    )

    assert len(alignment_metrics) == 1
    assert len(coverage_metrics) == 1
    assert alignment_metrics[0].mapped_reads_pct == 97.1
    assert coverage_metrics[0].mean_coverage == 31.8


def test_auto_ingest_routes_vendor_validation(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pingest-vendor"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_ingest_vendor", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fasta"
    vendor.write_text(">chr1\nACGT\n", encoding="utf-8")

    resp = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="vendor_validation",
            payload={
                "vendor_assembly_path": str(vendor),
                "similarity_score": 0.991,
                "comparator_method": "kmer",
                "kmer_size": 11,
                "pass_threshold": 0.98,
            },
        ),
    )

    assert resp["stage"] == "vendor_validation"
    assert len(vendor_assembly_validations) == 1
    assert vendor_assembly_validations[0].status == "passed"
    assert vendor_assembly_validations[0].comparator_method == "kmer"
    assert vendor_assembly_validations[0].kmer_size == 11
    step = next((s for s in run_steps if s.run_id == run.id and s.step_name == "vendor_validation"), None)
    assert step is not None
    assert step.status == "done"
