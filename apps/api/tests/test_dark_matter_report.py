from app.routers.foundation import (
    AlignmentImportRequest,
    AutoIngestRequest,
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    TaxonomyImportHit,
    TaxonomyImportRequest,
    create_project,
    create_run_full,
    create_sample,
    generate_run_report,
    get_dark_matter_report,
    import_alignment_metrics,
    import_taxonomy_hits,
    auto_ingest_run_stage,
    ReportGenerateRequest,
)
from app.store.memory_store import (
    alignment_metrics,
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
    vendor_assembly_validations,
)


def _reset_stores():
    for store in (
        projects,
        samples,
        runs,
        run_steps,
        run_events,
        run_logs,
        reports,
        variants,
        structural_variants,
        cnv_segments,
        mtdna_results,
        prs_results,
        taxonomy_hits,
        benchmark_records,
        vendor_assembly_validations,
        alignment_metrics,
    ):
        store.clear()


def test_dark_matter_report_is_conservative_summary():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pdark"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_dark", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    import_alignment_metrics(
        run.id,
        AlignmentImportRequest(mapped_reads_pct=99.1, unmapped_reads=1234, mapped_contigs=25),
    )
    import_taxonomy_hits(
        run.id,
        TaxonomyImportRequest(
            hits=[
                TaxonomyImportHit(
                    organism="unclassified",
                    kingdom="unclassified",
                    read_count=42,
                    confidence=0.0,
                    evidence_score=0.0,
                    tools=["Kraken2"],
                ),
                TaxonomyImportHit(
                    organism="Escherichia coli",
                    kingdom="bacteria",
                    read_count=10,
                    confidence=0.7,
                    evidence_score=0.6,
                    tools=["Kraken2"],
                    likely_contaminant=True,
                ),
            ],
            replace_existing_for_run=True,
        ),
    )

    report = get_dark_matter_report("S_dark")

    assert report["status"] == "unclassified_reads_observed"
    assert report["metrics"]["alignment_unmapped_reads"] == 1234
    assert report["metrics"]["taxonomy_unclassified_reads"] == 42
    assert report["metrics"]["taxonomy_classified_reads"] == 10
    assert report["top_unclassified"][0]["organism"] == "unclassified"
    assert any("not evidence of a novel organism" in x for x in report["guardrails"])
    assert report["non_diagnostic"] is True

    artifact = generate_run_report(
        run.id,
        ReportGenerateRequest(report_type="dark_matter", include_html=False, include_json=True, include_parquet=False),
    )
    assert artifact.summary["metrics"]["taxonomy_unclassified_reads"] == 42


def test_unknown_reads_auto_ingest_feeds_dark_matter_report():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Punknown"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_unknown", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    imported = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="unknown_reads",
            payload={
                "collection_mode": "host_bam_unmapped_pairs",
                "host_bam": "/data/results/run_x/S_unknown.sorted.markdup.bam",
                "host_depletion": {"tool": "samtools", "total_reads": "1000", "unmapped_reads": "25"},
                "taxonomy_depletion": {"tool": "kraken2", "classified": "7", "unclassified": "18"},
                "assembly": {"tool": "megahit", "contigs": "3", "total_bp": "1200", "n50": "800"},
                "contig_search": {"tool": "blastn", "total_contigs": "3", "with_hits": "1", "no_hits": "2"},
                "kmer_profile": {
                    "tool": "internal_kmer_counter",
                    "status": "profiled",
                    "kmer_size": "31",
                    "reads_scanned": "400",
                    "distinct_kmers": "12",
                    "top_kmers": [{"kmer": "ACGT", "count": 8}],
                },
                "kmer_clusters": [{"cluster_id": "prefix:ACGT", "prefix": "ACGT", "total_count": 8, "distinct_kmers": 2}],
                "files": {"contigs_fasta": "/data/results/run_x/S_unknown_unknown_reads/contigs.fa"},
            },
        ),
    )

    assert imported["stage"] == "unknown_reads"
    report = get_dark_matter_report("S_unknown")

    assert report["status"] == "unclassified_reads_observed"
    assert report["metrics"]["unknown_host_unmapped_reads"] == 25
    assert report["metrics"]["unknown_taxonomy_unclassified_reads"] == 18
    assert report["metrics"]["unknown_assembled_contigs"] == 3
    assert report["metrics"]["unknown_no_hit_contigs"] == 2
    assert report["metrics"]["unknown_distinct_kmers"] == 12
    assert report["metrics"]["unknown_kmer_cluster_count"] == 1
    assert report["unknown_read_collection"]["collection_mode"] == "host_bam_unmapped_pairs"
    assert report["unknown_read_collection"]["kmer_profile"]["status"] == "profiled"
    assert report["unknown_read_collection"]["files"]["contigs_fasta"].endswith("contigs.fa")

    artifact = generate_run_report(
        run.id,
        ReportGenerateRequest(report_type="dark_matter", include_html=False, include_json=True, include_parquet=False),
    )
    assert artifact.summary["unknown_read_collection"]["assembly"]["contigs"] == 3
