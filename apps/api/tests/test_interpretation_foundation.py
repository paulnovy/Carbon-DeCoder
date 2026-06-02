from app.routers.foundation import (
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    VariantImportItem,
    VariantsImportRequest,
    create_project,
    create_run_full,
    create_sample,
    import_variant_calls,
    interpretation_acmg_secondary_findings,
    interpretation_annotation,
    interpretation_foundation,
    interpretation_monogenic,
    interpretation_clinvar_validate,
    interpretation_pgx_readiness,
    interpretation_pgx_rules,
    interpretation_pgx_rules_validate,
    interpretation_resource_detail,
    interpretation_resources,
    get_interpretation_results_for_sample,
    materialize_interpretation_results,
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
    interpretation_results,
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
    interpretation_results.clear()
    taxonomy_hits.clear()


def _sample_with_variant():
    project = create_project(ProjectCreateRequest(name="P-interpret"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_interp", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    import_variant_calls(
        run.id,
        VariantsImportRequest(
            variants=[
                VariantImportItem(
                    chrom="chr17",
                    pos=43044295,
                    ref="A",
                    alt="G",
                    variant_type="SNV",
                    caller_list=["bcftools"],
                    caller_agreement_score=0.55,
                    trust_score=88,
                    genotype="0/1",
                    zygosity="heterozygous",
                    explainability={"depth": 42, "allele_balance": 0.48, "variant_quality": 120},
                )
            ]
        ),
    )
    return sample, run


def test_interpretation_foundation_validates_build():
    _reset_stores()
    _sample_with_variant()

    out = interpretation_foundation("S_interp")

    assert out["ready_for_interpretation"] is True
    assert out["build_validation"]["status"] == "ready"
    assert out["variant_count"] == 1
    assert out["provenance_required"] is True


def test_annotation_summary_uses_imported_csq_fields():
    _reset_stores()
    sample, run = _sample_with_variant()
    variants[0].consequence = "G|missense_variant|MODERATE|BRCA1|ENSG00000012048|Transcript|ENST00000357654"

    out = interpretation_annotation("S_interp")

    assert out["status"] == "annotated"
    assert out["count"] == 1
    assert out["items"][0]["gene"] == "BRCA1"
    assert out["items"][0]["impact"] == "MODERATE"
    assert out["provenance"]["source_database"] == "VCF ANN/CSQ imported annotation"


def test_monogenic_uses_exact_match_clinvar_tsv(tmp_path, monkeypatch):
    _reset_stores()
    _sample_with_variant()
    clinvar = tmp_path / "clinvar.tsv"
    clinvar.write_text(
        "chrom\tpos\tref\talt\tgene\tcondition\tclinical_significance\treview_status\taccession\tinheritance\n"
        "17\t43044295\tA\tG\tBRCA1\tHereditary breast and ovarian cancer\tPathogenic\tcriteria provided, multiple submitters\tVCV000001\tAD\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WGS_CLINVAR_TSV", str(clinvar))

    out = interpretation_monogenic("S_interp")

    assert out["status"] == "pathogenic_or_likely_pathogenic_found"
    assert out["count"] == 1
    assert out["items"][0]["gene"] == "BRCA1"
    assert out["items"][0]["is_acmg_sf"] is True
    assert out["items"][0]["genotype"] == "0/1"
    assert out["items"][0]["zygosity"] == "heterozygous"
    assert out["items"][0]["assessability"] == "variant_assessable"
    assert out["items"][0]["technical_evidence"]["local_depth"] == 42
    assert out["condition_count"] == 1
    assert out["summary"]["pathogenic_or_likely_pathogenic_count"] == 1
    assert out["conditions"][0]["condition"] == "Hereditary breast and ovarian cancer"
    assert out["conditions"][0]["genes"] == ["BRCA1"]
    assert out["conditions"][0]["variant_count"] == 1
    assert out["summary"]["catalog_version"].startswith("dev-seed")
    assert out["conditions"][0]["catalog_matches"]
    assert out["items"][0]["catalog_match"]
    assert out["provenance"]["source_database"] == "ClinVar"


def test_acmg_secondary_findings_requires_opt_in(tmp_path, monkeypatch):
    _reset_stores()
    _sample_with_variant()
    clinvar = tmp_path / "clinvar.tsv"
    clinvar.write_text(
        "chrom\tpos\tref\talt\tgene\tcondition\tclinical_significance\treview_status\n"
        "17\t43044295\tA\tG\tBRCA1\tHBOC\tPathogenic\tcriteria provided\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WGS_CLINVAR_TSV", str(clinvar))

    gated = interpretation_acmg_secondary_findings("S_interp")
    enabled = interpretation_acmg_secondary_findings("S_interp", enabled=True)

    assert gated["status"] == "opt_in_required"
    assert enabled["count"] == 1
    assert enabled["items"][0]["gene"] == "BRCA1"


def test_interpretation_resources_exposes_modules():
    out = interpretation_resources()
    assert out["modules"]["provenance"]["ready"] is True
    assert "pharmcat_pgx" in out["modules"]
    assert "cpic_pharmgkb_rules" in out["modules"]
    assert out["non_diagnostic"] is True
    assert any(r["id"] == "clinvar_exact_match_tsv" for r in out["registry"])
    assert any(r["id"] == "cpic_pharmgkb_rule_manifest" for r in out["registry"])
    assert "clinvar_monogenic" in out["resources_by_module"]
    assert "pipeline" in out["modules"]["clinvar_monogenic"]
    assert out["modules"]["clinvar_monogenic"]["pipeline"]["validate_endpoint"] == "/interpretation/resources/clinvar/validate"


def test_clinvar_validator_reports_exact_match_rows(tmp_path, monkeypatch):
    clinvar = tmp_path / "clinvar.tsv"
    clinvar.write_text(
        "chrom\tpos\tref\talt\tgene\tclinical_significance\treview_status\n"
        "17\t43044295\tA\tG\tBRCA1\tPathogenic\tcriteria provided\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WGS_CLINVAR_TSV", str(clinvar))

    out = interpretation_clinvar_validate()

    assert out["valid"] is True
    assert out["valid_exact_match_rows"] == 1
    assert out["gene_count_seen"] == 1


def test_interpretation_resource_detail(tmp_path, monkeypatch):
    clinvar = tmp_path / "clinvar.tsv"
    clinvar.write_text("chrom\tpos\tref\talt\n", encoding="utf-8")
    monkeypatch.setenv("WGS_CLINVAR_TSV", str(clinvar))

    out = interpretation_resource_detail("clinvar_exact_match_tsv")

    assert out["status"] == "available"
    assert out["path"] == str(clinvar)
    assert out["source_database"] == "ClinVar"


def test_pgx_rule_manifest_validation_and_exact_match(tmp_path, monkeypatch):
    _reset_stores()
    _sample_with_variant()
    manifest = tmp_path / "pgx_rules.json"
    manifest.write_text(
        """
        {
          "items": [
            {
              "rule_id": "CPIC-CYP2C19-CLOP-001",
              "gene": "CYP2C19",
              "drug": "clopidogrel",
              "chrom": "chr17",
              "pos": 43044295,
              "ref": "A",
              "alt": "G",
              "phenotype": "reduced function allele observed",
              "recommendation": "Review with validated PGx workflow before considering clopidogrel guidance.",
              "source": "CPIC/PharmGKB",
              "source_version": "curated-test-v1",
              "source_url": "https://cpicpgx.org/",
              "genome_build": "GRCh38",
              "confidence": "moderate",
              "caveat": "Exact variant test fixture; not a star-allele caller."
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("WGS_PGX_RULES_MANIFEST", str(manifest))

    validation = interpretation_pgx_rules_validate()
    readiness = interpretation_pgx_readiness("S_interp")
    out = interpretation_pgx_rules("S_interp")

    assert validation["valid"] is True
    assert readiness["rule_manifest_ready"] is True
    assert readiness["status"] in {"curated_rules_ready", "ready"}
    assert out["status"] == "pgx_rules_matched"
    assert out["count"] == 1
    assert out["items"][0]["gene"] == "CYP2C19"
    assert out["items"][0]["drug"] == "clopidogrel"
    assert out["items"][0]["source"] == "CPIC/PharmGKB"
    assert out["provenance"]["source_database"] == "CPIC/PharmGKB curated rule manifest"


def test_materialize_interpretation_results_persists_snapshots():
    _reset_stores()
    sample, run = _sample_with_variant()

    created = materialize_interpretation_results("S_interp")
    listed = get_interpretation_results_for_sample("S_interp", run_id=run.id)
    monogenic = get_interpretation_results_for_sample("S_interp", run_id=run.id, module="monogenic")

    assert created["count"] >= 6
    assert listed["count"] == created["count"]
    assert {item.module for item in listed["items"]} >= {
        "foundation",
        "annotation",
        "monogenic",
        "traits_wellness",
        "pharmacogenomics_rules",
    }
    assert monogenic["count"] == 1
    assert monogenic["items"][0].module == "monogenic"
    assert monogenic["items"][0].run_id == run.id
    assert run_events[-1].event_type == "interpretation.results_materialized"
