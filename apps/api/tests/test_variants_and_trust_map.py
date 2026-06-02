from app.routers.foundation import (
    ProjectCreateRequest,
    RunCreateRequest,
    SampleCreateRequest,
    VariantImportItem,
    VariantsImportRequest,
    create_project,
    create_run_full,
    create_sample,
    get_sample_trust_map,
    get_variant,
    import_variant_calls,
    list_sample_variants,
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


def test_variant_and_trust_map_scaffold():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pvar"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_var", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))

    import_variant_calls(
        run.id,
        VariantsImportRequest(
            variants=[
                VariantImportItem(
                    chrom="chr1",
                    pos=12345,
                    ref="A",
                    alt="G",
                    caller_list=["DeepVariant", "HaplotypeCaller"],
                    caller_agreement_score=0.95,
                    trust_score=91.0,
                )
            ]
        ),
    )

    listed = list_sample_variants("S_var")
    assert listed["count"] >= 1

    variant_id = listed["items"][0].id
    detail = get_variant(variant_id)
    assert detail.id == variant_id
    assert detail.trust_label in {"high", "medium", "low", "unknown"}

    trust_map = get_sample_trust_map("S_var")
    assert trust_map["score_range"] == [0, 100]
    assert len(trust_map["variant_points"]) >= 1
