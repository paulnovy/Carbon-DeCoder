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
    interpretation_resources,
    interpretation_traits,
    interpretation_traits_manifest_validate,
)
from app.store.memory_store import projects, samples, runs, run_steps, run_events, run_logs, reports, variants


def _reset():
    for store in (projects, samples, runs, run_steps, run_events, run_logs, reports, variants):
        store.clear()


def _sample():
    project = create_project(ProjectCreateRequest(name="P-traits"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_traits", reference_id="GRCh38_standard"))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id="GRCh38_standard"))
    import_variant_calls(
        run.id,
        VariantsImportRequest(
            variants=[VariantImportItem(chrom="chr1", pos=12345, ref="A", alt="G", trust_score=91, caller_agreement_score=0.8)]
        ),
    )
    return sample


def test_traits_manifest_validate_and_evaluate(tmp_path, monkeypatch):
    _reset()
    _sample()
    manifest = tmp_path / "traits.tsv"
    manifest.write_text(
        "trait_id\ttrait_name\tcategory\tchrom\tpos\tref\talt\tgene\teffect\tsource\tgenome_build\tconfidence\tmin_trust_score\n"
        "caffeine_metabolism\tCaffeine metabolism\tWellness\t1\t12345\tA\tG\tCYP1A2\tAssociated variant observed\tPMID:123\tGRCh38\tmoderate\t80\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WGS_TRAITS_MANIFEST", str(manifest))

    validation = interpretation_traits_manifest_validate()
    out = interpretation_traits("S_traits")

    assert validation["valid"] is True
    assert validation["count"] == 1
    assert out["status"] == "traits_found"
    assert out["count"] == 1
    assert out["items"][0]["trait_id"] == "caffeine_metabolism"
    assert out["items"][0]["gene"] == "CYP1A2"
    assert out["non_diagnostic"] is True

    resources = interpretation_resources()
    trait_resource = next(x for x in resources["registry"] if x["id"] == "curated_traits_manifest")
    assert trait_resource["status"] == "available"
    assert resources["modules"]["traits_wellness"]["ready"] is True
