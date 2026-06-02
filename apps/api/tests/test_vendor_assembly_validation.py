from pathlib import Path

from app.routers.foundation import (
    VendorAssemblyKmerSweepRequest,
    VendorAssemblyCompareRequest,
    VendorAssemblyValidationFromFastqRequest,
    VendorAssemblyFastqE2ERequest,
    VendorAssemblyGlobalFastqE2ERequest,
    VendorAssemblyRecommendationRequest,
    VendorVcfCompareRequest,
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    VendorAssemblyValidationImportRequest,
    compare_vendor_assembly_validation,
    compare_vendor_assembly_validation_kmer_sweep,
    compare_vendor_vcf_validation,
    recommend_vendor_assembly_validation_method,
    create_project,
    create_run_full,
    create_sample,
    get_run_vendor_assembly_validation_history,
    get_run_vendor_assembly_validation_gate,
    get_run_vendor_assembly_validation_latest,
    get_sample_vendor_assembly_validation_gate,
    get_sample_vendor_assembly_validation_summary,
    get_sample_vendor_assembly_validations,
    import_vendor_assembly_validation,
    import_vendor_assembly_validation_from_fastq,
    run_vendor_assembly_validation_e2e_from_fastq,
    run_vendor_assembly_global_e2e_from_fastq,
)
from fastapi import HTTPException
from app.store.memory_store import (
    benchmark_records,
    cnv_segments,
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
    vendor_assembly_validations.clear()


def test_vendor_assembly_validation_import_and_history(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor_assembly.fasta"
    vendor.write_text(">chr1\nACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline_assembly.fasta"
    pipeline.write_text(">chr1\nACGT\n", encoding="utf-8")

    rec = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(
            vendor_assembly_path=str(vendor),
            pipeline_assembly_path=str(pipeline),
            similarity_score=0.991,
            snv_concordance=0.989,
            indel_concordance=0.982,
            structural_concordance=0.971,
            pass_threshold=0.98,
            summary={"note": "acceptance check"},
        ),
    )

    assert rec.status == "passed"
    assert rec.non_diagnostic is True
    assert rec.comparator_method == "proxy"
    assert rec.kmer_size is None

    hist = get_sample_vendor_assembly_validations("S_vendor")
    assert hist["count"] == 1
    assert hist["items"][0].id == rec.id


def test_vendor_assembly_validation_import_supports_report_file(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-report"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_report", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor_assembly.fasta"
    vendor.write_text(">chr1\nACGT\n", encoding="utf-8")

    report = tmp_path / "vendor_validation.txt"
    report.write_text(
        f"vendor_assembly_path={vendor}\n"
        "similarity_score=0.975\n"
        "snv_concordance=0.981\n"
        "indel_concordance=0.972\n"
        "pass_threshold=0.98\n",
        encoding="utf-8",
    )

    rec = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_validation_report_path=str(report)),
    )

    assert rec.status == "failed"
    assert rec.vendor_assembly_path == str(vendor)
    assert rec.comparator_method == "proxy"
    assert rec.kmer_size is None


def test_vendor_assembly_validation_import_auto_computes_when_pipeline_path_present(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-auto"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_auto", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGTACGA\n", encoding="utf-8")

    rec = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(
            vendor_assembly_path=str(vendor),
            pipeline_assembly_path=str(pipeline),
            pass_threshold=0.5,
        ),
    )

    assert rec.similarity_score is not None
    assert rec.snv_concordance is not None
    assert rec.status == "passed"


def test_vendor_assembly_validation_import_auto_computes_with_kmer_method(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-auto-kmer"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_auto_kmer", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor_kmer.fa"
    vendor.write_text(">chr1\nACGTACGTACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline_kmer.fa"
    pipeline.write_text(">chr1\nACGTACGTACGTTCGT\n", encoding="utf-8")

    rec = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(
            vendor_assembly_path=str(vendor),
            pipeline_assembly_path=str(pipeline),
            comparator_method="kmer",
            kmer_size=9,
            pass_threshold=0.1,
        ),
    )

    assert rec.similarity_score is not None
    assert rec.summary.get("comparator_method") == "kmer"
    assert rec.comparator_method == "kmer"
    assert rec.kmer_size == 9


def test_vendor_assembly_compare_rejects_unsupported_method(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-compare-method-bad"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_compare_method_bad", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGTACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGTACGTTCGT\n", encoding="utf-8")

    try:
        _ = compare_vendor_assembly_validation(
            run.id,
            VendorAssemblyCompareRequest(
                vendor_assembly_path=str(vendor),
                pipeline_assembly_path=str(pipeline),
                comparator_method="minimap2",
            ),
        )
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.detail == "unsupported_comparator_method"


def test_vendor_assembly_compare_rejects_invalid_kmer_size(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-compare-kmer-size-bad"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_compare_kmer_size_bad", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGA\n", encoding="utf-8")

    try:
        _ = compare_vendor_assembly_validation(
            run.id,
            VendorAssemblyCompareRequest(
                vendor_assembly_path=str(vendor),
                pipeline_assembly_path=str(pipeline),
                comparator_method="kmer",
                kmer_size=2,
            ),
        )
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.detail == "invalid_kmer_size"


def test_vendor_assembly_compare_endpoint_returns_status(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-compare"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_compare", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGA\n", encoding="utf-8")

    out = compare_vendor_assembly_validation(
        run.id,
        VendorAssemblyCompareRequest(
            vendor_assembly_path=str(vendor),
            pipeline_assembly_path=str(pipeline),
            pass_threshold=0.5,
        ),
    )

    assert out["status"] == "passed"
    assert out["non_diagnostic"] is True
    assert out["similarity_score"] is not None


def test_vendor_assembly_compare_exact_mode(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-compare-exact"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_compare_exact", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTTCGT\n", encoding="utf-8")

    out = compare_vendor_assembly_validation(
        run.id,
        VendorAssemblyCompareRequest(
            vendor_assembly_path=str(vendor),
            pipeline_assembly_path=str(pipeline),
            comparator_method="exact",
            pass_threshold=0.1,
        ),
    )

    assert out["comparator_method"] == "exact"
    assert out["status"] == "passed"


def test_vendor_vcf_compare_imports_validation_record(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-vcf"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_vcf", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.vcf"
    vendor.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t50\tPASS\t.\n"
        "chr1\t200\t.\tAT\tA\t50\tPASS\t.\n",
        encoding="utf-8",
    )
    pipeline = tmp_path / "pipeline.vcf"
    pipeline.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t100\t.\tA\tG\t50\tPASS\t.\n"
        "1\t250\t.\tC\tT\t50\tPASS\t.\n",
        encoding="utf-8",
    )

    out = compare_vendor_vcf_validation(
        run.id,
        VendorVcfCompareRequest(
            vendor_vcf_path=str(vendor),
            pipeline_vcf_path=str(pipeline),
            pass_threshold=0.4,
            import_result=True,
        ),
    )
    history = get_run_vendor_assembly_validation_history(run.id)

    assert out["comparator_method"] == "vcf_exact"
    assert out["similarity_score"] == 0.5
    assert out["snv_concordance"] == 0.666667
    assert out["indel_concordance"] == 0.0
    assert out["status"] == "passed"
    assert out["imported_validation_id"]
    assert history["count"] == 1
    assert history["items"][0].comparator_method == "vcf_exact"


def test_vendor_assembly_compare_endpoint_accepts_report_path(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-compare-report"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_compare_report", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGA\n", encoding="utf-8")
    report = tmp_path / "vendor_validation.json"
    report.write_text(
        '{"vendor_assembly_path":"'
        + str(vendor)
        + '","pipeline_assembly_path":"'
        + str(pipeline)
        + '","pass_threshold":0.5,"comparator_method":"kmer","kmer_size":7}',
        encoding="utf-8",
    )

    out = compare_vendor_assembly_validation(
        run.id,
        VendorAssemblyCompareRequest(vendor_validation_report_path=str(report)),
    )

    assert out["status"] == "passed"
    assert out["pass_threshold"] == 0.5
    assert out["comparator_method"] == "kmer"
    assert out["kmer_size"] == 7


def test_vendor_assembly_compare_kmer_sweep(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-kmer-sweep"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_kmer_sweep", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGTACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGTACGTTCGT\n", encoding="utf-8")

    out = compare_vendor_assembly_validation_kmer_sweep(
        run.id,
        VendorAssemblyKmerSweepRequest(
            vendor_assembly_path=str(vendor),
            pipeline_assembly_path=str(pipeline),
            kmer_sizes=[7, 11],
            pass_threshold=0.1,
        ),
    )

    assert out["count"] == 2
    assert out["kmer_sizes"] == [7, 11]
    assert len(out["results"]) == 2
    assert out["summary"]["similarity_score_avg"] is not None
    assert out["summary"]["pass_rate"] == 1.0
    assert out["summary"]["all_passed"] is True
    assert out["summary"]["recommended_kmer_size"] in [7, 11]
    assert out["summary"]["best_result"]["kmer_size"] in [7, 11]


def test_vendor_assembly_recommendation_endpoint(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-recommend"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_recommend", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTACGTACGTACGT\n", encoding="utf-8")
    pipeline = tmp_path / "pipeline.fa"
    pipeline.write_text(">chr1\nACGTACGTACGTTCGT\n", encoding="utf-8")

    out = recommend_vendor_assembly_validation_method(
        run.id,
        VendorAssemblyRecommendationRequest(
            vendor_assembly_path=str(vendor),
            pipeline_assembly_path=str(pipeline),
            kmer_sizes=[7, 11],
            pass_threshold=0.1,
        ),
    )

    assert out["non_diagnostic"] is True
    assert len(out["candidates"]) == 4
    assert out["recommendation"]["method"] in {"proxy", "kmer", "exact"}


def test_get_run_vendor_assembly_validation_latest(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-latest"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_latest", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGT\n", encoding="utf-8")

    rec = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_assembly_path=str(vendor), similarity_score=0.99),
    )

    latest = get_run_vendor_assembly_validation_latest(run.id)
    assert latest.id == rec.id


def test_get_sample_vendor_assembly_validation_summary(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-summary"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_summary", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGT\n", encoding="utf-8")

    _ = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_assembly_path=str(vendor), similarity_score=0.99),
    )
    _ = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_assembly_path=str(vendor), similarity_score=0.95),
    )

    summary = get_sample_vendor_assembly_validation_summary("S_vendor_summary")
    assert summary["count"] == 2
    assert summary["status_counts"]["passed"] == 1
    assert summary["status_counts"]["failed"] == 1
    assert summary["similarity_score_avg"] == 0.97


def test_get_sample_vendor_assembly_validation_gate(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-gate"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_gate", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGT\n", encoding="utf-8")

    _ = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_assembly_path=str(vendor), similarity_score=0.99),
    )
    _ = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_assembly_path=str(vendor), similarity_score=0.95),
    )

    gate = get_sample_vendor_assembly_validation_gate("S_vendor_gate", min_pass_rate=0.4)
    assert gate["gate_status"] == "failed"
    assert gate["latest_status"] == "failed"
    assert gate["pass_rate"] == 0.5

    gate_relaxed = get_sample_vendor_assembly_validation_gate("S_vendor_gate", min_pass_rate=0.3)
    assert gate_relaxed["gate_status"] == "failed"

    _ = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_assembly_path=str(vendor), similarity_score=0.995),
    )
    gate_pass = get_sample_vendor_assembly_validation_gate("S_vendor_gate", min_pass_rate=0.5)
    assert gate_pass["gate_status"] == "passed"


def test_get_sample_vendor_assembly_validation_gate_no_data():
    _reset_stores()

    gate = get_sample_vendor_assembly_validation_gate("S_none", min_pass_rate=0.8)
    assert gate["gate_status"] == "no_data"
    assert gate["pass_rate"] is None


def test_get_run_vendor_assembly_validation_gate(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-run-gate"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_run_gate", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGT\n", encoding="utf-8")

    _ = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_assembly_path=str(vendor), similarity_score=0.99),
    )

    gate = get_run_vendor_assembly_validation_gate(run.id, min_similarity=0.98)
    assert gate["gate_status"] == "passed"
    assert gate["latest_status"] == "passed"
    assert gate["similarity_score"] == 0.99

    gate_strict = get_run_vendor_assembly_validation_gate(run.id, min_similarity=0.995)
    assert gate_strict["gate_status"] == "failed"


def test_get_run_vendor_assembly_validation_history(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-run-history"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vendor_run_history", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGT\n", encoding="utf-8")

    _ = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_assembly_path=str(vendor), similarity_score=0.99),
    )
    _ = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(vendor_assembly_path=str(vendor), similarity_score=0.95),
    )

    out = get_run_vendor_assembly_validation_history(run.id)
    assert out["run_id"] == run.id
    assert out["sample_id"] == sample.id
    assert out["count"] == 2
    assert len(out["items"]) == 2


def test_import_vendor_assembly_validation_from_fastq(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-from-fastq"))
    r1 = tmp_path / "S1_R1.fastq"
    r2 = tmp_path / "S1_R2.fastq"
    r1.write_text("@r1\nACGT\n+\n####\n", encoding="utf-8")
    r2.write_text("@r2\nTTAA\n+\n####\n", encoding="utf-8")

    sample = create_sample(
        project.id,
        SampleCreateRequest(
            sample_id="S_vendor_from_fastq",
            reference_id="GRCh38_standard",
            r1_path=str(r1),
            r2_path=str(r2),
        ),
    )
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTTTAA\n", encoding="utf-8")

    out = import_vendor_assembly_validation_from_fastq(
        run.id,
        VendorAssemblyValidationFromFastqRequest(
            vendor_assembly_path=str(vendor),
            comparator_method="exact",
            pass_threshold=0.1,
            max_reads=2,
        ),
    )

    assert out["validation"].comparator_method == "exact"
    assert Path(out["pipeline_assembly_path"]).exists()


def test_run_vendor_assembly_validation_e2e_from_fastq(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-e2e-fastq"))
    r1 = tmp_path / "S1_R1.fastq"
    r2 = tmp_path / "S1_R2.fastq"
    r1.write_text("@r1\nACGT\n+\n####\n", encoding="utf-8")
    r2.write_text("@r2\nTTAA\n+\n####\n", encoding="utf-8")

    sample = create_sample(
        project.id,
        SampleCreateRequest(
            sample_id="S_vendor_e2e_fastq",
            reference_id="GRCh38_standard",
            r1_path=str(r1),
            r2_path=str(r2),
        ),
    )
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTTTAA\n", encoding="utf-8")

    out = run_vendor_assembly_validation_e2e_from_fastq(
        run.id,
        VendorAssemblyFastqE2ERequest(
            vendor_assembly_path=str(vendor),
            comparator_method="kmer",
            kmer_size=9,
            pass_threshold=0.1,
            max_reads=2,
            generate_reports=True,
        ),
    )

    assert out["validation"].comparator_method == "kmer"
    assert out["gate"]["gate_status"] in {"passed", "failed", "no_data"}
    assert out["report_bundle"] is not None


def test_run_vendor_assembly_global_e2e_from_fastq(tmp_path):
    _reset_stores()

    r1 = tmp_path / "S1_R1.fastq"
    r2 = tmp_path / "S1_R2.fastq"
    r1.write_text("@r1\nACGT\n+\n####\n", encoding="utf-8")
    r2.write_text("@r2\nTTAA\n+\n####\n", encoding="utf-8")
    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTTTAA\n", encoding="utf-8")

    out = run_vendor_assembly_global_e2e_from_fastq(
        VendorAssemblyGlobalFastqE2ERequest(
            project_name="Pvendor-global-e2e",
            sample_id="S_vendor_global_e2e",
            reference_id="GRCh38_standard",
            r1_path=str(r1),
            r2_path=str(r2),
            vendor_assembly_path=str(vendor),
            comparator_method="exact",
            pass_threshold=0.1,
            max_reads=2,
            generate_reports=True,
        )
    )

    assert out["project"].name == "Pvendor-global-e2e"
    assert out["sample"].sample_id == "S_vendor_global_e2e"
    assert out["e2e"]["validation"].comparator_method == "exact"
    assert out["project_created"] is True
    assert out["sample_reused"] is False


def test_run_vendor_assembly_global_e2e_reuses_existing_sample(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvendor-global-reuse"))
    r1_old = tmp_path / "old_R1.fastq"
    r2_old = tmp_path / "old_R2.fastq"
    r1_old.write_text("@r1\nAAAA\n+\n####\n", encoding="utf-8")
    r2_old.write_text("@r2\nTTTT\n+\n####\n", encoding="utf-8")
    existing = create_sample(
        project.id,
        SampleCreateRequest(
            sample_id="S_vendor_reuse",
            reference_id="GRCh38_standard",
            r1_path=str(r1_old),
            r2_path=str(r2_old),
        ),
    )

    r1_new = tmp_path / "new_R1.fastq"
    r2_new = tmp_path / "new_R2.fastq"
    r1_new.write_text("@r1\nACGT\n+\n####\n", encoding="utf-8")
    r2_new.write_text("@r2\nTTAA\n+\n####\n", encoding="utf-8")
    vendor = tmp_path / "vendor.fa"
    vendor.write_text(">chr1\nACGTTTAA\n", encoding="utf-8")

    out = run_vendor_assembly_global_e2e_from_fastq(
        VendorAssemblyGlobalFastqE2ERequest(
            project_id=project.id,
            sample_id="S_vendor_reuse",
            reference_id="GRCh38_standard",
            r1_path=str(r1_new),
            r2_path=str(r2_new),
            vendor_assembly_path=str(vendor),
            comparator_method="proxy",
            pass_threshold=0.1,
            max_reads=2,
        )
    )

    assert out["project_created"] is False
    assert out["sample_reused"] is True
    assert out["sample"].id == existing.id
    assert out["sample"].r1_path == str(r1_new)
