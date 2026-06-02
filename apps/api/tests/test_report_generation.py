import json
from pathlib import Path

from app.routers.foundation import (
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    create_project,
    create_run_full,
    create_sample,
    generate_all_reports,
    generate_run_report,
    import_vendor_assembly_validation,
    get_run_report_bundle,
    get_run_report_bundle_files,
    repair_run_report_bundle,
    verify_run_report_bundle,
    list_run_reports,
    ReportBundleRepairRequest,
    ReportGenerateRequest,
    VendorAssemblyValidationImportRequest,
    VendorVcfCompareRequest,
    compare_vendor_vcf_validation,
)
from app.db.models import MtDNAResult, PRSResult, VariantCall
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
    alignment_metrics.clear()
    coverage_metrics.clear()
    variants.clear()
    structural_variants.clear()
    cnv_segments.clear()
    mtdna_results.clear()
    prs_results.clear()
    taxonomy_hits.clear()
    benchmark_records.clear()
    vendor_assembly_validations.clear()


def test_generate_report_and_bundle_scaffold(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Prep"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_rep", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vendor = tmp_path / "vendor_report_gen.fasta"
    vendor.write_text(">chr1\nACGT\n", encoding="utf-8")

    _ = import_vendor_assembly_validation(
        run.id,
        VendorAssemblyValidationImportRequest(
            vendor_assembly_path=str(vendor),
            similarity_score=0.99,
            comparator_method="kmer",
            kmer_size=13,
            pass_threshold=0.98,
        ),
    )
    vendor_vcf = tmp_path / "vendor_report_gen.vcf"
    vendor_vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t50\tPASS\t.\n",
        encoding="utf-8",
    )
    pipeline_vcf = tmp_path / "pipeline_report_gen.vcf"
    pipeline_vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t100\t.\tA\tG\t50\tPASS\t.\n",
        encoding="utf-8",
    )
    _ = compare_vendor_vcf_validation(
        run.id,
        VendorVcfCompareRequest(
            vendor_vcf_path=str(vendor_vcf),
            pipeline_vcf_path=str(pipeline_vcf),
            pass_threshold=0.98,
            import_result=True,
        ),
    )

    single = generate_run_report(
        run.id,
        ReportGenerateRequest(report_type="qc", include_html=True, include_json=True, include_parquet=False),
    )
    assert single.report_type == "qc"
    assert single.status == "generated"
    assert single.parquet_path is None
    assert "status" in single.summary
    assert single.summary["run_id"] == run.id
    assert single.summary["reference"]["id"] == "GRCh38_standard"
    assert single.summary["reference"]["version"] == "GRCh38"

    assert single.html_path is not None and Path(single.html_path).exists()
    assert single.json_path is not None and Path(single.json_path).exists()
    html = Path(single.html_path).read_text(encoding="utf-8")
    assert "report-shell" in html
    assert "Raw JSON payload" in html
    assert "Reference provenance" in html
    assert "Non-diagnostic research/technical report" in html
    assert "non_diagnostic" in Path(single.json_path).read_text(encoding="utf-8")

    bundle = generate_all_reports(run.id)
    assert bundle["count"] >= 5
    assert all(x.status == "generated" for x in bundle["items"])

    alignment = next((x for x in bundle["items"] if x.report_type == "alignment"), None)
    coverage = next((x for x in bundle["items"] if x.report_type == "coverage"), None)
    sv = next((x for x in bundle["items"] if x.report_type == "sv"), None)
    cnv = next((x for x in bundle["items"] if x.report_type == "cnv"), None)
    prs = next((x for x in bundle["items"] if x.report_type == "prs"), None)
    mtdna = next((x for x in bundle["items"] if x.report_type == "mtdna"), None)
    taxonomy = next((x for x in bundle["items"] if x.report_type == "taxonomy"), None)
    annotation = next((x for x in bundle["items"] if x.report_type == "annotation"), None)
    vendor_validation = next((x for x in bundle["items"] if x.report_type == "vendor_validation"), None)
    acceptance = next((x for x in bundle["items"] if x.report_type == "acceptance"), None)
    interpretation = next((x for x in bundle["items"] if x.report_type == "interpretation"), None)
    assert alignment is not None
    assert coverage is not None
    assert sv is not None
    assert cnv is not None
    assert prs is not None
    assert mtdna is not None
    assert taxonomy is not None
    assert annotation is not None
    assert vendor_validation is not None
    assert acceptance is not None
    assert interpretation is not None
    assert "flagstat" in alignment.summary
    assert "mosdepth" in coverage.summary
    assert alignment.summary["status"] == "missing"
    assert alignment.summary["flagstat"]["mapped_reads_pct"] is None
    assert alignment.summary["idxstats"]["unmapped_reads"] is None
    assert "No alignment metrics" in alignment.summary["note"]
    assert coverage.summary["status"] == "missing"
    assert coverage.summary["mosdepth"]["mean_coverage"] is None
    assert coverage.summary["tiles"]["status"] == "not_imported"
    assert "No coverage metrics" in coverage.summary["note"]
    assert "sv_count" in sv.summary
    assert "segment_count" in cnv.summary
    assert "items" in prs.summary
    assert "items" in mtdna.summary
    assert "top_hits" in taxonomy.summary
    assert "coverage_breadth" in taxonomy.summary
    assert "consequence_distribution" in annotation.summary
    assert "latest" in vendor_validation.summary
    assert acceptance.summary["status"] == "accepted"
    assert acceptance.summary["asset_counts"]["assembly"] == 1
    assert acceptance.summary["asset_counts"]["vcf"] == 1
    assert acceptance.summary["latest"]["comparator_method"] == "vcf_exact"
    assert acceptance.summary["assembly_validations"][0]["comparator_method"] == "kmer"
    assert "sections" in interpretation.summary
    assert "provenance" in interpretation.summary
    assert "resources" in interpretation.summary
    assert vendor_validation.summary["latest"]["comparator_method"] == "vcf_exact"
    assert vendor_validation.summary["latest"]["kmer_size"] is None
    assert vendor_validation.summary["status_counts"]["passed"] >= 2

    listed = list_run_reports(run.id)
    assert len(listed["items"]) >= 2

    assert "bundle_manifest_path" in bundle
    first_json = json.loads(Path(bundle["items"][0].json_path).read_text(encoding="utf-8"))
    assert first_json["_report"]["schema_version"] == "wgs.report.v1"
    assert first_json["_report"]["format"] == "json"
    first_parquet = Path(bundle["items"][0].parquet_path)
    assert first_parquet.read_bytes()[:4] == b"PAR1"
    assert b"PARQUET_PLACEHOLDER" not in first_parquet.read_bytes()

    manifest_path = Path(bundle["bundle_manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == run.id
    assert manifest["count"] == bundle["count"]
    assert manifest["context"]["reference"]["id"] == "GRCh38_standard"
    assert manifest["context"]["reference"]["version"] == "GRCh38"
    assert manifest["items"]
    first_meta = manifest["items"][0]["file_meta"]
    assert first_meta["html"]["exists"] is True
    assert first_meta["json"]["exists"] is True
    assert first_meta["parquet"]["exists"] is True
    assert first_meta["html"]["size_bytes"] is not None
    assert first_meta["json"]["sha256"] is not None

    assert "bundle_index_path" in bundle
    index_path = Path(bundle["bundle_index_path"])
    assert index_path.exists()
    index_html = index_path.read_text(encoding="utf-8")
    assert run.id in index_html
    assert "Reference provenance" in index_html
    assert "report-shell" in index_html
    assert "Artifacts" in index_html

    bundle_meta = get_run_report_bundle(run.id)
    assert bundle_meta["status"] == "ready"
    assert bundle_meta["count"] == bundle["count"]
    assert bundle_meta["context"]["reference"]["id"] == "GRCh38_standard"
    assert len(bundle_meta["items"]) == bundle["count"]

    bundle_files = get_run_report_bundle_files(run.id)
    assert bundle_files["status"] == "ready"
    assert bundle_files["count"] == bundle["count"]
    assert bundle_files["existing_files"] > 0
    assert bundle_files["missing_files"] == 0
    assert all("html_exists" in x for x in bundle_files["items"])

    verify = verify_run_report_bundle(run.id)
    assert verify["status"] == "ready"
    assert verify["mismatched_files"] == 0
    assert verify["missing_files"] == 0
    assert verify["checked_files"] == verify["matched_files"]

    tamper_target = Path(bundle["items"][0].json_path)
    tamper_target.write_text(tamper_target.read_text(encoding="utf-8") + "\n#tamper\n", encoding="utf-8")

    verify_after_tamper = verify_run_report_bundle(run.id)
    assert verify_after_tamper["status"] == "degraded"
    assert verify_after_tamper["mismatched_files"] >= 1
    assert verify_after_tamper["problem_files"] >= 1
    assert verify_after_tamper["problem_report_types"]
    assert any(x["problems"] for x in verify_after_tamper["items"])

    repaired = repair_run_report_bundle(run.id, ReportBundleRepairRequest(report_types=["qc"], only_failed=True))
    assert repaired["repaired_count"] >= 1
    assert repaired["before"]["status"] == "degraded"
    assert repaired["after"]["status"] == "ready"
    assert repaired["after"]["problem_files"] == 0

    verify_after_repair = verify_run_report_bundle(run.id)
    assert verify_after_repair["status"] == "ready"
    assert verify_after_repair["mismatched_files"] == 0


def test_interpretation_report_sections_include_provenance(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pinterp-report"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_interp_report", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    variants.append(
        VariantCall(
            id="var_interp_report_1",
            sample_id=sample.sample_id,
            run_id=run.id,
            reference_id=run.reference_id,
            chrom="chr1",
            pos=123456,
            ref="A",
            alt="G",
            consequence="G|missense_variant|MODERATE|GENE1|ENSG000001|Transcript|ENST000001",
            clinical_annotation="ClinVar: not reviewed",
            trust_score=87.0,
            trust_label="high",
        )
    )
    prs_results.append(
        PRSResult(
            id="prs_interp_report_1",
            sample_id=sample.sample_id,
            run_id=run.id,
            reference_id=run.reference_id,
            trait="Type 2 diabetes",
            score_value=1.23,
            overlap_pct=92.5,
            variant_count_total=100,
            variant_count_matched=93,
            quality_label="good",
            warning="Research-only PRS.",
        )
    )
    mtdna_results.append(
        MtDNAResult(
            id="mt_interp_report_1",
            sample_id=sample.sample_id,
            run_id=run.id,
            reference_id=run.reference_id,
            haplogroup="U5",
            heteroplasmy_mean_vaf=0.03,
            num_variants=8,
            numts_warning=True,
            trust_score=42.0,
            trust_label="low",
        )
    )

    report = generate_run_report(
        run.id,
        ReportGenerateRequest(report_type="interpretation", include_html=True, include_json=True, include_parquet=False),
    )

    assert report.report_type == "interpretation"
    assert report.summary["status"] in {"ready", "ready_with_gaps"}
    assert report.summary["build_validation"]["ready_for_interpretation"] is True
    assert report.summary["provenance"]["input_counts"]["run_variants"] >= 1

    sections = report.summary["sections"]
    assert sections["annotation"]["status"] == "annotated"
    assert sections["annotation"]["provenance"]["source_database"] == "VCF ANN/CSQ imported annotation"
    assert sections["annotation"]["items_total_count"] >= 1
    assert any(item["variant_id"] == "var_interp_report_1" for item in sections["annotation"]["items_preview"])
    assert "provenance" in sections["monogenic"]
    assert sections["prs"]["count"] == 1
    assert sections["prs"]["provenance"]["matched_variant_count"] == 93
    assert sections["mtdna"]["count"] == 1
    assert sections["mtdna"]["warning_count"] == 1
    assert sections["pharmacogenomics"]["provenance"]["source_database"] == "PharmCAT/CPIC"
    assert sections["pharmacogenomics"]["rule_layer"]["provenance"]["source_database"] == "CPIC/PharmGKB curated rule manifest"
    assert sections["haplogroups"]["provenance"]["source_database"] == "HaploGrep/PhyloTree"
    assert report.summary["guardrails"]
    assert report.html_path is not None
    assert "Interpretation" in Path(report.html_path).read_text(encoding="utf-8")


def test_get_run_report_bundle_returns_missing_before_generation():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Prep-missing"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_rep_missing", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    bundle_meta = get_run_report_bundle(run.id)
    assert bundle_meta["status"] == "missing"
    assert bundle_meta["count"] == 0

    bundle_files = get_run_report_bundle_files(run.id)
    assert bundle_files["status"] == "missing"
    assert bundle_files["count"] == 0

    verify = verify_run_report_bundle(run.id)
    assert verify["status"] == "missing"
    assert verify["count"] == 0
