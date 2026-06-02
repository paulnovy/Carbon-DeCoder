from app.routers.foundation import (
    AutoIngestRequest,
    MtDNAImportRequest,
    PRSImportRequest,
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    TaxonomyImportHit,
    TaxonomyImportRequest,
    auto_ingest_run_stage,
    create_project,
    create_run_full,
    create_sample,
    get_mtdna,
    get_prs,
    get_taxonomy,
    import_mtdna_result,
    import_prs_result,
    import_taxonomy_hits,
    interpretation_haplogroup_readiness,
    interpretation_haplogroups,
)
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


def test_mtdna_prs_taxonomy_import_endpoints_replace_seeded():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pmito-prs-tax"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_mpt", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    _ = import_mtdna_result(
        run.id,
        MtDNAImportRequest(
            haplogroup="U5",
            heteroplasmy_mean_vaf=0.07,
            num_variants=12,
            numts_warning=False,
            trust_score=74.0,
            replace_existing_for_run=True,
        ),
    )
    _ = import_prs_result(
        run.id,
        PRSImportRequest(
            trait="Type 2 diabetes",
            score_value=0.41,
            overlap_pct=90.2,
            variant_count_total=110000,
            variant_count_matched=100500,
            quality_label="high",
            warning="Research-only output",
            replace_existing_for_run=True,
        ),
    )
    _ = import_taxonomy_hits(
        run.id,
        TaxonomyImportRequest(
            hits=[
                TaxonomyImportHit(
                    organism="Escherichia coli",
                    kingdom="bacteria",
                    read_count=67,
                    confidence=0.62,
                    evidence_score=0.55,
                    tools=["Kraken2"],
                    likely_contaminant=True,
                )
            ],
            replace_existing_for_run=True,
        ),
    )

    mtdna = get_mtdna("S_mpt")
    prs = get_prs("S_mpt")
    tax = get_taxonomy("S_mpt")

    assert mtdna["count"] == 1
    assert prs["count"] == 1
    assert tax["count"] == 1
    assert mtdna["items"][0].haplogroup == "U5"
    assert prs["items"][0].trait == "Type 2 diabetes"
    assert tax["items"][0].organism == "Escherichia coli"


def test_mtdna_import_infers_numts_warning_from_low_trust_low_vaf_pattern():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pmito-numts"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_numts", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    _ = import_mtdna_result(
        run.id,
        MtDNAImportRequest(
            haplogroup="H",
            heteroplasmy_mean_vaf=0.031,
            num_variants=18,
            trust_score=42.0,
            numts_warning=False,
            replace_existing_for_run=True,
        ),
    )

    mtdna = get_mtdna("S_numts")
    assert mtdna["items"][0].numts_warning is True
    assert mtdna["numts_warning_count"] == 1
    assert any("NUMTs" in reason for reason in mtdna["warnings"][0]["reasons"])


def test_auto_ingest_routes_mtdna_prs_taxonomy():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ping-mpt"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_ing_mpt", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    r1 = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="mtdna",
            payload={
                "haplogroup": "H1",
                "heteroplasmy_mean_vaf": 0.11,
                "num_variants": 15,
                "numts_warning": True,
                "replace_existing_for_run": True,
            },
        ),
    )
    r2 = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="prs",
            payload={
                "trait": "CAD",
                "score_value": 0.63,
                "overlap_pct": 87.0,
                "variant_count_total": 120000,
                "variant_count_matched": 105000,
                "quality_label": "medium",
                "replace_existing_for_run": True,
            },
        ),
    )
    r3 = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="taxonomy",
            payload={
                "replace_existing_for_run": True,
                "hits": [
                    {
                        "organism": "Torque teno virus",
                        "kingdom": "viruses",
                        "read_count": 29,
                        "confidence": 0.44,
                        "evidence_score": 0.35,
                        "tools": ["Kraken2"],
                        "likely_contaminant": False,
                    }
                ],
            },
        ),
    )

    assert r1["stage"] == "mtdna"
    assert r2["stage"] == "prs"
    assert r3["stage"] == "taxonomy"

    assert get_mtdna("S_ing_mpt")["count"] == 1
    assert get_prs("S_ing_mpt")["count"] == 1
    assert get_taxonomy("S_ing_mpt")["count"] == 1


def test_taxonomy_import_supports_report_file(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptaxfile"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax_file", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    report = tmp_path / "kraken.report"
    report.write_text("3.40\t88\t20\tS\t562\tEscherichia coli\n", encoding="utf-8")

    _ = import_taxonomy_hits(
        run.id,
        TaxonomyImportRequest(taxonomy_report_path=str(report), replace_existing_for_run=True),
    )

    tax = get_taxonomy("S_tax_file")
    assert tax["count"] == 1
    assert tax["items"][0].organism == "Escherichia coli"


def test_taxonomy_import_preserves_bracken_refinement_provenance(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Ptaxbracken"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_tax_bracken", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    report = tmp_path / "S_tax_bracken.bracken.tsv"
    report.write_text(
        "name\ttaxonomy_id\ttaxonomy_lvl\tkraken_assigned_reads\tadded_reads\tnew_est_reads\tfraction_total_reads\n"
        "Torque teno virus\t688881\tS\t43\t9\t52\t0.0067\n",
        encoding="utf-8",
    )

    imported = import_taxonomy_hits(
        run.id,
        TaxonomyImportRequest(
            taxonomy_report_path=str(report),
            taxonomy_mode="kraken2+bracken",
            taxonomy_refinement="bracken",
            taxonomy_refinement_status="applied",
            bracken_report_path=str(report),
            bracken_level="S",
            bracken_read_length=150,
            replace_existing_for_run=True,
        ),
    )

    tax = get_taxonomy("S_tax_bracken", run_id=run.id)

    assert imported["count"] == 1
    assert imported["items"][0].read_count == 52
    assert imported["items"][0].tools == ["Kraken2", "Bracken"]
    assert tax["provenance"]["taxonomy_refinement"] == "bracken"
    assert tax["provenance"]["taxonomy_refinement_status"] == "applied"
    assert tax["provenance"]["bracken_level"] == "S"


def test_mtdna_prs_import_supports_report_files(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pmpt-file"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_mpt_file", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    mtdna = tmp_path / "mtdna.report.txt"
    mtdna.write_text(
        "haplogroup=U5\n"
        "heteroplasmy_mean_vaf=0.08\n"
        "num_variants=14\n"
        "numts_warning=false\n"
        "trust_score=72\n",
        encoding="utf-8",
    )

    prs = tmp_path / "prs.result.txt"
    prs.write_text(
        "trait=CAD\n"
        "score_value=0.63\n"
        "overlap_pct=87.0\n"
        "variant_count_total=120000\n"
        "variant_count_matched=105000\n"
        "quality_label=medium\n",
        encoding="utf-8",
    )

    _ = import_mtdna_result(run.id, MtDNAImportRequest(mtdna_report_path=str(mtdna), replace_existing_for_run=True))
    _ = import_prs_result(run.id, PRSImportRequest(prs_result_path=str(prs), replace_existing_for_run=True))

    m = get_mtdna("S_mpt_file")
    p = get_prs("S_mpt_file")
    assert m["count"] == 1
    assert p["count"] == 1
    assert m["items"][0].haplogroup == "U5"
    assert p["items"][0].trait == "CAD"


def test_haplogrep_endpoint_uses_imported_mtdna_vcf(tmp_path, monkeypatch):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Phaplo"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_haplo", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    mtdna_vcf = tmp_path / "S_haplo.mtdna.vcf"
    mtdna_vcf.write_text("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n", encoding="utf-8")

    import_mtdna_result(
        run.id,
        MtDNAImportRequest(
            haplogroup="pending",
            num_variants=1,
            mtdna_vcf_path=str(mtdna_vcf),
            replace_existing_for_run=True,
        ),
    )

    monkeypatch.setattr(
        "app.routers.foundation.interpretation_tool_status",
        lambda: {"haplogrep": True},
    )
    monkeypatch.setattr(
        "app.routers.foundation.run_haplogrep",
        lambda vcf, output_dir: {
            "status": "completed",
            "input_vcf_path": str(vcf),
            "output_dir": str(output_dir),
            "haplogroups": [{"sample_id": "S_haplo", "haplogroup": "H1", "quality_score": 0.91}],
            "non_diagnostic": True,
        },
    )

    readiness = interpretation_haplogroup_readiness("S_haplo")
    result = interpretation_haplogroups("S_haplo")

    assert readiness["status"] == "ready"
    assert readiness["mtdna_vcf_path"] == str(mtdna_vcf)
    assert result["status"] == "completed"
    assert result["input_vcf_path"] == str(mtdna_vcf)
    assert result["input_vcf_source"] == "run_event:mtdna_vcf_path"
    assert result["haplogroups"][0]["haplogroup"] == "H1"
