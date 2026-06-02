from app.routers.foundation import (
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    VariantsImportRequest,
    VariantImportItem,
    auto_ingest_run_stage,
    create_project,
    create_run_full,
    create_sample,
    import_variant_calls,
    import_existing_variant_vcf,
    get_run_variant_status,
    list_sample_variants,
    AutoIngestRequest,
)
from app.store.memory_store import projects, reports, run_events, run_logs, run_steps, runs, samples, variants


def _reset_stores():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()
    reports.clear()
    variants.clear()


def test_import_variant_calls_replaces_existing_for_run():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvarimp"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_varimp", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    assert len([v for v in variants if v.run_id == run.id]) == 0

    payload = VariantsImportRequest(
        variants=[
            VariantImportItem(
                chrom="chr1",
                pos=12345,
                ref="A",
                alt="G",
                genotype="0/1",
                zygosity="heterozygous",
                caller_list=["HaplotypeCaller", "DeepVariant"],
                caller_agreement_score=0.92,
                trust_score=88.0,
                consequence="missense_variant",
            ),
            VariantImportItem(
                chrom="chr2",
                pos=98765,
                ref="C",
                alt="T",
                caller_list=["HaplotypeCaller"],
                caller_agreement_score=0.34,
            ),
        ],
        replace_existing_for_run=True,
    )

    res = import_variant_calls(run.id, payload)
    assert res["count"] == 2

    listed = list_sample_variants("S_varimp")
    assert listed["count"] == 2
    labels = {v.trust_label for v in listed["items"]}
    assert labels.issubset({"high", "medium", "low", "unknown"})
    assert listed["items"][0].genotype == "0/1"
    assert listed["items"][0].zygosity == "heterozygous"


def test_auto_ingest_variants_stage_routes_import():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvarauto"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_varauto", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    response = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="variants",
            payload={
                "replace_existing_for_run": True,
                "variants": [
                    {
                        "chrom": "chr7",
                        "pos": 5501234,
                        "ref": "G",
                        "alt": "A",
                        "caller_list": ["DeepVariant"],
                        "caller_agreement_score": 0.55,
                    }
                ],
            },
        ),
    )

    assert response["stage"] == "variants"
    listed = list_sample_variants("S_varauto")
    assert listed["count"] == 1
    assert listed["items"][0].chrom == "chr7"


def test_variant_import_normalizes_chrom_and_alleles_for_chr_style_reference():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pnormchr"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_norm_chr", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    _ = import_variant_calls(
        run.id,
        VariantsImportRequest(
            variants=[
                VariantImportItem(
                    chrom="7",
                    pos=111,
                    ref="a",
                    alt="g",
                    caller_list=["DV"],
                    caller_agreement_score=0.5,
                )
            ]
        ),
    )

    listed = list_sample_variants("S_norm_chr")
    assert listed["count"] == 1
    assert listed["items"][0].chrom == "chr7"
    assert listed["items"][0].ref == "A"
    assert listed["items"][0].alt == "G"


def test_variant_import_normalizes_chrom_for_numeric_reference():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pnormnum"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_norm_num", reference_id="GRCh37_legacy"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh37_legacy"))

    _ = import_variant_calls(
        run.id,
        VariantsImportRequest(
            variants=[
                VariantImportItem(
                    chrom="chrM",
                    pos=222,
                    ref="c",
                    alt="t",
                    caller_list=["HC"],
                    caller_agreement_score=0.5,
                )
            ]
        ),
    )

    listed = list_sample_variants("S_norm_num")
    assert listed["count"] == 1
    assert listed["items"][0].chrom == "MT"


def test_variant_import_supports_vcf_file(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvcf"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vcf", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    vcf = tmp_path / "variants.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "7\t101\t.\tA\tG\t.\tPASS\tCALLER_AGREEMENT=0.91;CSQ=missense_variant\tGT:GQ:DP:AD\t1/1:80:42:0,42\n",
        encoding="utf-8",
    )

    _ = import_variant_calls(
        run.id,
        VariantsImportRequest(variants_vcf_path=str(vcf), replace_existing_for_run=True),
    )

    listed = list_sample_variants("S_vcf")
    assert listed["count"] == 1
    assert listed["items"][0].chrom == "chr7"
    assert listed["items"][0].zygosity == "homozygous_alt"


def test_variant_status_and_import_existing_vcf_fast_path(tmp_path, monkeypatch):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvcfstatus"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_vcfstatus", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    variants.clear()

    vcf = tmp_path / "S_vcfstatus.bcftools.raw.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t202\t.\tC\tT\t50\tPASS\tCALLER_AGREEMENT=0.8\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.routers.foundation._sample_output_prefix",
        lambda _run, _sample=None: (tmp_path, "S_vcfstatus"),
    )

    status = get_run_variant_status(run.id)
    assert status["state"] == "vcf_exists_import_needed"
    assert status["action"] == "import_existing_vcf"
    assert status["existing_vcf_path"] == str(vcf)

    imported = import_existing_variant_vcf(run.id)
    assert imported["mode"] == "existing_vcf_import"
    assert imported["count"] == 1
    assert imported["status_after_import"]["state"] == "imported"
