from app.routers.foundation import (
    BenchmarkImportRequest,
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    create_project,
    create_run_benchmark,
    create_sample,
    get_benchmark,
    get_sample_benchmark_history,
    import_benchmark_metrics,
)
from app.store.memory_store import (
    benchmark_records,
    cnv_segments,
    mtdna_results,
    projects,
    prs_results,
    reports,
    run_events,
    run_logs,
    run_steps,
    runs,
    samples,
    structural_variants,
    taxonomy_hits,
    variants,
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


def test_benchmark_history_and_regression_alert_scaffold():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pbench"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_bench", reference_id="GRCh38_standard"))

    run1 = create_run_benchmark(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    _ = import_benchmark_metrics(
        run1.id,
        BenchmarkImportRequest(
            benchmark_id="giab-s_bench",
            precision=0.95,
            recall=0.94,
            f1=0.945,
            stratified_metrics={"snv_f1": 0.97},
        ),
    )

    run2 = create_run_benchmark(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    second = import_benchmark_metrics(
        run2.id,
        BenchmarkImportRequest(
            benchmark_id="giab-s_bench",
            precision=0.94,
            recall=0.90,
            f1=0.92,
            stratified_metrics={"snv_f1": 0.95},
        ),
    )

    assert second.regression_alert is not None

    detail = get_benchmark("giab-s_bench")
    assert len(detail["history"]) >= 2

    history = get_sample_benchmark_history("S_bench")
    assert history["count"] >= 2


def test_benchmark_import_supports_report_file(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pbench-file"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_bench_file", reference_id="GRCh38_standard"))
    run = create_run_benchmark(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    report = tmp_path / "benchmark.txt"
    report.write_text(
        "benchmark_id=giab-s_bench_file\n"
        "precision=0.951\n"
        "recall=0.939\n"
        "f1=0.945\n"
        "stratified_snv_f1=0.973\n",
        encoding="utf-8",
    )

    rec = import_benchmark_metrics(run.id, BenchmarkImportRequest(benchmark_report_path=str(report)))
    assert rec.benchmark_id == "giab-s_bench_file"
    assert rec.f1 == 0.945
