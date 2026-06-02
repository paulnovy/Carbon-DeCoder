from app.routers.foundation import (
    AutoIngestRequest,
    CNVImportItem,
    CNVImportRequest,
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    SVImportItem,
    SVImportRequest,
    auto_ingest_run_stage,
    create_project,
    create_run_full,
    create_sample,
    get_cnv_segments,
    get_structural_variants,
    import_cnv_segments,
    import_structural_variants,
)
from app.store.memory_store import cnv_segments, projects, reports, run_events, run_logs, run_steps, runs, samples, structural_variants, variants


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


def test_sv_and_cnv_endpoints_have_items_after_import():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Psv"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_sv", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    import_structural_variants(
        run.id,
        SVImportRequest(
            sv=[
                SVImportItem(
                    chrom="chr2",
                    start=100,
                    end=250,
                    sv_type="DEL",
                    size_bp=150,
                    evidence_types=["split_reads"],
                    caller_list=["Manta"],
                    trust_score=80.0,
                )
            ]
        ),
    )
    import_cnv_segments(
        run.id,
        CNVImportRequest(
            segments=[
                CNVImportItem(
                    chrom="chr3",
                    start=1000,
                    end=5000,
                    copy_number=1.2,
                    cnv_type="loss",
                    method="CNVkit",
                    trust_score=72.0,
                )
            ]
        ),
    )

    sv = get_structural_variants("S_sv")
    cnv = get_cnv_segments("S_sv")

    assert sv["count"] >= 1
    assert cnv["count"] >= 1


def test_sv_cnv_import_replaces_seeded_records_for_run():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Psvimp"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_svimp", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    sv_res = import_structural_variants(
        run.id,
        SVImportRequest(
            sv=[
                SVImportItem(
                    chrom="7",
                    start=1000,
                    end=1200,
                    sv_type="DEL",
                    size_bp=200,
                    evidence_types=["split_reads"],
                    caller_list=["Manta"],
                    trust_score=77.0,
                )
            ],
            replace_existing_for_run=True,
        ),
    )
    cnv_res = import_cnv_segments(
        run.id,
        CNVImportRequest(
            segments=[
                CNVImportItem(
                    chrom="chr8",
                    start=2000,
                    end=4000,
                    copy_number=2.8,
                    cnv_type="gain",
                    method="gCNV",
                    trust_score=73.0,
                )
            ],
            replace_existing_for_run=True,
        ),
    )

    assert sv_res["count"] == 1
    assert cnv_res["count"] == 1

    sv = get_structural_variants("S_svimp")
    cnv = get_cnv_segments("S_svimp")
    assert sv["count"] == 1
    assert cnv["count"] == 1
    assert sv["items"][0].chrom == "chr7"


def test_auto_ingest_sv_cnv_routes_imports():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Psvauto"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_svauto", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    sv_resp = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="sv",
            payload={
                "replace_existing_for_run": True,
                "sv": [
                    {
                        "chrom": "chr3",
                        "start": 500,
                        "end": 900,
                        "sv_type": "INS",
                        "size_bp": 400,
                    }
                ],
            },
        ),
    )
    cnv_resp = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="cnv",
            payload={
                "replace_existing_for_run": True,
                "segments": [
                    {
                        "chrom": "chr12",
                        "start": 100,
                        "end": 1000,
                        "copy_number": 1.5,
                        "cnv_type": "loss",
                        "method": "CNVnator",
                    }
                ],
            },
        ),
    )

    assert sv_resp["stage"] == "sv"
    assert cnv_resp["stage"] == "cnv"

    sv = get_structural_variants("S_svauto")
    cnv = get_cnv_segments("S_svauto")
    assert sv["count"] == 1
    assert cnv["count"] == 1


def test_sv_cnv_import_supports_file_parsers(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Psvfile"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_svfile", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    sv_vcf = tmp_path / "manta.sv.vcf"
    sv_vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr3\t1000\t.\tN\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=1300\n",
        encoding="utf-8",
    )

    cnv_tsv = tmp_path / "segments.tsv"
    cnv_tsv.write_text(
        "chrom\tstart\tend\tcopy_number\tcnv_type\tmethod\n"
        "chr8\t2000\t5000\t1.6\tloss\tCNVnator\n",
        encoding="utf-8",
    )

    sv_res = import_structural_variants(run.id, SVImportRequest(sv_vcf_path=str(sv_vcf), replace_existing_for_run=True))
    cnv_res = import_cnv_segments(
        run.id,
        CNVImportRequest(cnv_segments_tsv_path=str(cnv_tsv), replace_existing_for_run=True),
    )

    assert sv_res["count"] == 1
    assert cnv_res["count"] == 1
    assert get_structural_variants("S_svfile")["items"][0].chrom == "chr3"


def test_cnv_import_supports_cnvnator_event_file(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcnvfile2"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_cnvfile2", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    cnv_calls = tmp_path / "cnvnator.calls.txt"
    cnv_calls.write_text("duplication\tchr2:2000-8000\t6000\t1.65\t2e-5\n", encoding="utf-8")

    cnv_res = import_cnv_segments(
        run.id,
        CNVImportRequest(cnv_segments_tsv_path=str(cnv_calls), replace_existing_for_run=True),
    )

    assert cnv_res["count"] == 1
    rec = get_cnv_segments("S_cnvfile2")["items"][0]
    assert rec.chrom == "chr2"
    assert rec.cnv_type == "gain"


def test_sv_import_supports_delly_bnd_file(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Psvfile2"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_svfile2", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    sv_vcf = tmp_path / "delly.sv.vcf"
    sv_vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=DELLY\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t1000\t.\tN\tN]2:2000]\t.\tPASS\tSVTYPE=BND;CHR2=2;PE=14;SR=7\n",
        encoding="utf-8",
    )

    sv_res = import_structural_variants(run.id, SVImportRequest(sv_vcf_path=str(sv_vcf), replace_existing_for_run=True))
    assert sv_res["count"] == 1
    rec = get_structural_variants("S_svfile2")["items"][0]
    assert rec.chrom == "chr1"
    assert rec.sv_type == "BND"
    assert "Delly" in rec.caller_list


def test_cnv_import_supports_cnv_vcf_file(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcnvvcf"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_cnvvcf", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    cnv_vcf = tmp_path / "sample.cnv.vcf"
    cnv_vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=GATK-gCNV\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "4\t10000\t.\tN\t<DEL>\t90\tPASS\tSVTYPE=DEL;END=22000;CNQ=80\tGT:CN:GQ\t0/1:1:72\n",
        encoding="utf-8",
    )

    cnv_res = import_cnv_segments(
        run.id,
        CNVImportRequest(cnv_vcf_path=str(cnv_vcf), replace_existing_for_run=True),
    )

    assert cnv_res["count"] == 1
    rec = get_cnv_segments("S_cnvvcf")["items"][0]
    assert rec.chrom == "chr4"
    assert rec.copy_number == 1.0
    assert rec.cnv_type == "loss"
    assert rec.method == "GATK-gCNV"


def test_auto_ingest_cnv_routes_cnv_vcf_path(tmp_path):
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcnvvcfauto"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_cnvvcfauto", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    cnv_vcf = tmp_path / "sample.cnv.vcf"
    cnv_vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=Canvas\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr6\t5000\t.\tN\t<DUP>\t70\tPASS\tSVTYPE=DUP;END=9500;CN=3\n",
        encoding="utf-8",
    )

    resp = auto_ingest_run_stage(
        run.id,
        AutoIngestRequest(
            stage="cnv",
            payload={"cnv_vcf_path": str(cnv_vcf), "replace_existing_for_run": True},
        ),
    )

    assert resp["stage"] == "cnv"
    rec = get_cnv_segments("S_cnvvcfauto")["items"][0]
    assert rec.chrom == "chr6"
    assert rec.cnv_type == "gain"
    assert rec.method == "Canvas"
