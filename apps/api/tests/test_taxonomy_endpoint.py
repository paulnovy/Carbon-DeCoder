from app.routers.foundation import (
    AutoIngestRequest,
    ProjectCreateRequest,
    RunCreateRequest,
    RunStep,
    SampleCreateRequest,
    TaxonomyImportHit,
    TaxonomyImportRequest,
    TaxonomyRecoverRequest,
    auto_ingest_run_stage,
    _clear_taxonomy_results_for_run,
    create_project,
    create_run_full,
    create_sample,
    get_run,
    get_taxonomy,
    import_taxonomy_hits,
    recover_taxonomy_from_report,
)
from app.db.models import TaxonomyHit
from app.store.memory_store import (
    cnv_segments,
    mtdna_results,
    projects,
    prs_results,
    reports,
    run_events,
    run_logs,
    run_steps,
    runs,
    save_run,
    save_run_step,
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


def test_taxonomy_endpoint_empty_until_real_import():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptax"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax", reference_id="GRCh38_standard"))
    _ = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    taxonomy = get_taxonomy("S_tax")
    assert taxonomy["count"] == 0
    assert taxonomy["items"] == []
    assert taxonomy["coverage_breadth"]["available_count"] == 0
    assert taxonomy["coverage_breadth"]["read_count_only_count"] == 0
    assert taxonomy["non_diagnostic"] is True


def test_taxonomy_endpoint_filters_by_run_id():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptax"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax", reference_id="GRCh38_standard"))
    run_a = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    run_b = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    import_taxonomy_hits(
        run_a.id,
        TaxonomyImportRequest(
            hits=[
                TaxonomyImportHit(
                    organism="Old organism",
                    kingdom="Bacteria",
                    read_count=10,
                    confidence=0.5,
                    evidence_score=0.5,
                    tools=["Kraken2"],
                )
            ],
        ),
    )
    import_taxonomy_hits(
        run_b.id,
        TaxonomyImportRequest(
            hits=[
                TaxonomyImportHit(
                    organism="New organism",
                    kingdom="Viruses",
                    read_count=20,
                    confidence=0.9,
                    evidence_score=0.8,
                    tools=["Kraken2"],
                )
            ],
            taxonomy_input_mode="host_depleted_bam_unmapped_pairs",
            taxonomy_database="/data/databases/kraken2/standard",
            taxonomy_route="human_wgs_host_depleted",
            taxonomy_analysis_id="S_tax.human_wgs_host_depleted.kraken2",
            taxonomy_analysis_version="taxonomy-route-v1",
            taxonomy_database_version="standard",
            taxonomy_extraction_params={"route": "human_wgs_host_depleted"},
            host_reference="GRCh38_standard",
        ),
    )

    taxonomy = get_taxonomy("S_tax", run_id=run_b.id)

    assert taxonomy["run_id"] == run_b.id
    assert taxonomy["count"] == 1
    assert taxonomy["items"][0].organism == "New organism"
    assert taxonomy["provenance"]["event_type"] == "taxonomy.imported"
    assert taxonomy["provenance"]["taxonomy_input_mode"] == "host_depleted_bam_unmapped_pairs"
    assert taxonomy["provenance"]["taxonomy_route"] == "human_wgs_host_depleted"
    assert taxonomy["provenance"]["taxonomy_analysis_version"] == "taxonomy-route-v1"
    assert taxonomy["provenance"]["taxonomy_extraction_params"]["route"] == "human_wgs_host_depleted"
    assert taxonomy["coverage_breadth"]["read_count_only_count"] == 1


def test_taxonomy_recover_creates_run_from_report(tmp_path):
    _reset_stores()

    report = tmp_path / "sample.kraken2.report"
    report.write_text(
        " 50.00\t100\t0\tR\t1\troot\n"
        " 50.00\t100\t0\tD\t2\t  Bacteria\n"
        " 50.00\t100\t0\tP\t1224\t    Pseudomonadota\n"
        " 50.00\t100\t0\tG\t724\t      Haemophilus\n"
        " 50.00\t100\t100\tS\t727\t        Haemophilus influenzae\n",
        encoding="utf-8",
    )
    project = create_project(ProjectCreateRequest(name="Ptax-recover"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax_recover", reference_id="GRCh38_standard"))

    result = recover_taxonomy_from_report(
        sample.id,
        TaxonomyRecoverRequest(
            run_id="run_recovered_tax",
            taxonomy_report_path=str(report),
            taxonomy_input_mode="host_depleted_bam_unmapped_pairs",
            taxonomy_database="/data/databases/kraken2/standard",
            taxonomy_route="human_wgs_host_depleted",
        ),
    )

    recovered = get_run("run_recovered_tax")
    taxonomy = get_taxonomy("S_tax_recover", run_id="run_recovered_tax")
    assert result["created_run"] is True
    assert result["count"] == 5
    assert recovered.mode == "taxonomy"
    assert recovered.status == "done"
    assert recovered.parameters["recovered_from_backup"] is True
    assert taxonomy["count"] == 5
    assert taxonomy["items"][0].top_clade == "Bacteria"
    assert taxonomy["provenance"]["taxonomy_route"] == "human_wgs_host_depleted"


def test_taxonomy_import_marks_single_stage_replay_done():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptax"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    run.status = "interrupted"
    run.parameters = {"stage_plan": {"final_stages": ["taxonomy"]}, "stages": ["taxonomy"]}
    run_steps.append(
        RunStep(
            id="stp_tax",
            run_id=run.id,
            step_name="taxonomy",
            status="running",
            progress_pct=0,
            last_log="taxonomy queued",
        )
    )
    run_steps.append(
        RunStep(
            id="stp_recovery",
            run_id=run.id,
            step_name="process_recovery",
            status="interrupted",
            progress_pct=0,
            last_log="API process restarted; in-process pipeline worker was interrupted.",
        )
    )

    import_taxonomy_hits(
        run.id,
        TaxonomyImportRequest(
            hits=[
                TaxonomyImportHit(
                    organism="New organism",
                    kingdom="Bacteria",
                    read_count=20,
                    confidence=0.9,
                    evidence_score=0.8,
                    tools=["Kraken2"],
                )
            ],
            taxonomy_input_mode="host_depleted_bam_unmapped_pairs",
        ),
    )

    assert run.status == "done"
    taxonomy_step = next(step for step in run_steps if step.id == "stp_tax")
    recovery_step = next(step for step in run_steps if step.id == "stp_recovery")
    assert taxonomy_step.status == "done"
    assert taxonomy_step.progress_pct == 100
    assert taxonomy_step.error is None
    assert recovery_step.status == "interrupted"
    assert get_taxonomy("S_tax", run_id=run.id)["count"] == 1


def test_get_run_repairs_interrupted_single_stage_replay_status():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptax-repair"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax_repair", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    run.status = "interrupted"
    run.parameters = {"stage_plan": {"final_stages": ["taxonomy"]}, "stages": ["taxonomy"]}
    save_run(run)
    taxonomy_step = RunStep(
        id="stp_tax_repaired",
        run_id=run.id,
        step_name="taxonomy",
        status="done",
        progress_pct=100,
        last_log="taxonomy ingested",
    )
    recovery_step = RunStep(
        id="stp_recovery_repaired",
        run_id=run.id,
        step_name="process_recovery",
        status="interrupted",
        progress_pct=0,
        last_log="API process restarted; in-process pipeline worker was interrupted.",
    )
    run_steps.append(taxonomy_step)
    run_steps.append(recovery_step)
    save_run_step(taxonomy_step)
    save_run_step(recovery_step)

    repaired = get_run(run.id)

    assert repaired.status == "done"
    assert run.status == "done"


def test_auto_ingest_persists_step_done_for_non_taxonomy_stage():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pingest"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_ingest", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    run.status = "running"
    run.parameters = {"stage_plan": {"final_stages": ["benchmark"]}, "stages": ["benchmark"]}
    run_steps.append(
        RunStep(
            id="stp_bench",
            run_id=run.id,
            step_name="benchmark",
            status="running",
            progress_pct=0,
            last_log="benchmark queued",
        )
    )

    auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="benchmark",
            payload={
                "benchmark_id": "truthset",
                "precision": 0.99,
                "recall": 0.98,
                "f1": 0.985,
            },
        ),
    )

    assert run.status == "done"
    assert run_steps[-1].status == "done"
    assert run_steps[-1].progress_pct == 100
    assert run_steps[-1].last_log == "benchmark ingested"


def test_auto_ingest_taxonomy_keeps_hits_visible():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="PingestTax"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_ingest_tax", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    run.status = "running"
    run.parameters = {"stage_plan": {"final_stages": ["taxonomy"]}, "stages": ["taxonomy"]}
    run_steps.append(
        RunStep(
            id="stp_tax_auto",
            run_id=run.id,
            step_name="taxonomy",
            status="running",
            progress_pct=0,
            last_log="taxonomy queued",
        )
    )

    result = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="taxonomy",
            payload={
                "hits": [
                    {
                        "organism": "Rothia dentocariosa",
                        "kingdom": "Bacteria",
                        "read_count": 175748,
                        "confidence": 0.9,
                        "evidence_score": 0.8,
                        "tools": ["kraken2"],
                    }
                ],
                "taxonomy_input_mode": "host_depleted_bam_unmapped_pairs",
                "taxonomy_route": "human_wgs_host_depleted",
            },
        ),
    )

    taxonomy = get_taxonomy("S_ingest_tax", run_id=run.id)
    assert result["result"]["count"] == 1
    assert taxonomy["count"] == 1
    assert taxonomy["items"][0].organism == "Rothia dentocariosa"
    assert taxonomy["provenance"]["event_type"] == "taxonomy.imported"
    assert run.status == "done"
    assert next(step for step in run_steps if step.id == "stp_tax_auto").status == "done"


def test_taxonomy_endpoint_reports_coverage_and_breadth_support():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptax-cov"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax_cov", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    imported = import_taxonomy_hits(
        run.id,
        TaxonomyImportRequest(
            hits=[
                TaxonomyImportHit(
                    organism="Escherichia coli",
                    kingdom="Bacteria",
                    read_count=5000,
                    confidence=0.96,
                    evidence_score=0.91,
                    tools=["Kraken2", "Bracken"],
                    breadth_fraction=0.32,
                    coverage_depth=8.4,
                    genome_covered_bp=1500000,
                    genome_length_bp=4600000,
                    coverage_method="host_depleted_bam_breadth",
                ),
                TaxonomyImportHit(
                    organism="Trace organism",
                    kingdom="Bacteria",
                    read_count=12,
                    confidence=0.3,
                    evidence_score=0.1,
                    tools=["Kraken2"],
                ),
            ],
            taxonomy_input_mode="host_depleted_bam_unmapped_pairs",
        ),
    )

    taxonomy = get_taxonomy("S_tax_cov", run_id=run.id)

    assert imported["coverage_breadth"]["available_count"] == 1
    assert imported["coverage_breadth"]["read_count_only_count"] == 1
    assert taxonomy["coverage_breadth"]["available_count"] == 1
    assert taxonomy["coverage_breadth"]["read_count_only_count"] == 1
    assert taxonomy["coverage_breadth"]["support_counts"]["broad_support"] == 1
    assert taxonomy["coverage_breadth"]["support_counts"]["read_count_only"] == 1
    assert taxonomy["items"][0].breadth_fraction == 0.32
    assert taxonomy["items"][0].coverage_depth == 8.4
    assert taxonomy["items"][0].coverage_method == "host_depleted_bam_breadth"
    assert taxonomy["provenance"]["taxonomy_coverage_available_count"] == 1


def test_taxonomy_endpoint_hides_legacy_run_hits_without_import_event():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptax"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    taxonomy_hits.append(
        TaxonomyHit(
            id="tax_legacy",
            sample_id="S_tax",
            run_id=run.id,
            reference_id="GRCh38_standard",
            organism="Seeded organism",
            kingdom="Bacteria",
            read_count=999,
            confidence=0.9,
            evidence_score=0.8,
            tools=["Mock"],
        )
    )

    taxonomy = get_taxonomy("S_tax", run_id=run.id)

    assert taxonomy["count"] == 0
    assert taxonomy["items"] == []
    assert taxonomy["provenance"] is None


def test_taxonomy_endpoint_keeps_imported_hits_when_event_cache_is_missing():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptax"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    run_steps.append(
        RunStep(
            id="stp_tax",
            run_id=run.id,
            step_name="taxonomy",
            status="done",
            progress_pct=100,
            last_log="taxonomy ingested",
        )
    )
    taxonomy_hits.append(
        TaxonomyHit(
            id="tax_imported_after_restart",
            sample_id="S_tax",
            run_id=run.id,
            reference_id="GRCh38_standard",
            organism="Persisted organism",
            kingdom="Bacteria",
            read_count=123,
            confidence=0.9,
            evidence_score=0.8,
            tools=["Kraken2"],
        )
    )

    taxonomy = get_taxonomy("S_tax", run_id=run.id)

    assert taxonomy["count"] == 1
    assert taxonomy["items"][0].organism == "Persisted organism"
    assert taxonomy["provenance"]["event_type"] == "taxonomy.imported"
    assert taxonomy["provenance"]["warning"] == "taxonomy_import_event_missing"


def test_taxonomy_endpoint_keeps_hits_when_step_status_is_stale_running():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptax"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    run_steps.append(
        RunStep(
            id="stp_tax_running",
            run_id=run.id,
            step_name="taxonomy",
            status="running",
            progress_pct=50,
            last_log="taxonomy process stale after restart",
        )
    )
    taxonomy_hits.append(
        TaxonomyHit(
            id="tax_imported_step_stale",
            sample_id="S_tax",
            run_id=run.id,
            reference_id="GRCh38_standard",
            organism="Rothia dentocariosa",
            kingdom="Bacteria",
            read_count=175748,
            confidence=0.9,
            evidence_score=0.8,
            tools=["Kraken2"],
        )
    )

    taxonomy = get_taxonomy("S_tax", run_id=run.id)

    assert taxonomy["count"] == 1
    assert taxonomy["items"][0].organism == "Rothia dentocariosa"
    assert taxonomy["provenance"]["event_type"] == "taxonomy.imported"
    assert taxonomy["provenance"]["warning"] == "taxonomy_import_event_missing_or_step_stale"
    assert taxonomy["provenance"]["step_status"] == "running"


def test_taxonomy_clear_hides_previous_import_until_new_import():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptax"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    import_taxonomy_hits(
        run.id,
        TaxonomyImportRequest(
            hits=[
                TaxonomyImportHit(
                    organism="Imported organism",
                    kingdom="Viruses",
                    read_count=42,
                    confidence=0.9,
                    evidence_score=0.8,
                    tools=["Kraken2"],
                )
            ],
            taxonomy_input_mode="host_depleted_bam_unmapped_pairs",
        ),
    )
    assert get_taxonomy("S_tax", run_id=run.id)["count"] == 1

    _clear_taxonomy_results_for_run(run.id, "pipeline_taxonomy_start")
    taxonomy = get_taxonomy("S_tax", run_id=run.id)

    assert taxonomy["count"] == 0
    assert taxonomy["items"] == []
    assert taxonomy["provenance"]["event_type"] == "taxonomy.results_cleared"
    assert taxonomy["provenance"]["reason"] == "pipeline_taxonomy_start"
