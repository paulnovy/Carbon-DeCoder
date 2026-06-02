from app.routers.foundation import (
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    VariantImportItem,
    VariantsImportRequest,
    create_project,
    create_run_full,
    create_sample,
    get_caller_agreement,
    get_caller_disagreement,
    get_caller_disagreement_overlay,
    import_variant_calls,
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


def test_caller_agreement_and_disagreement_endpoints():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcall"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_call", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    import_variant_calls(
        run.id,
        VariantsImportRequest(
            variants=[
                VariantImportItem(
                    chrom="chr1",
                    pos=1000,
                    ref="A",
                    alt="G",
                    caller_list=["DeepVariant", "HaplotypeCaller"],
                    caller_agreement_score=0.94,
                    trust_score=90.0,
                ),
                VariantImportItem(
                    chrom="chr1",
                    pos=250000,
                    ref="C",
                    alt="T",
                    caller_list=["DeepVariant"],
                    caller_agreement_score=0.25,
                    trust_score=42.0,
                ),
            ]
        ),
    )

    agreement = get_caller_agreement("S_call")
    assert "summary" in agreement
    assert agreement["summary"]["consensus"] >= 1

    disagreement = get_caller_disagreement("S_call")
    assert disagreement["count"] >= 1

    overlay = get_caller_disagreement_overlay("S_call", level="1mb")
    assert overlay["status"] == "imported"
    assert overlay["count"] >= 1
    assert overlay["hotspots"][0]["variant_count"] >= 1


def test_caller_disagreement_overlay_empty_without_variants():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcall-empty"))
    _ = create_sample(project.id, SampleCreateRequest(sample_id="S_call_empty", reference_id="GRCh38_standard"))

    overlay = get_caller_disagreement_overlay("S_call_empty", level="1mb")
    assert overlay["status"] == "empty"
    assert overlay["count"] == 0
