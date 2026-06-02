import pytest
from fastapi import HTTPException

from app.db.models import VariantCall
from app.core.pgs_catalog import curated_manifest_status, draft_manifest_from_downloaded_scores, draft_manifest_tsv, load_curated_pgs_manifest, search_curated_pgs, validate_curated_pgs_manifest
from app.routers.foundation import ProjectCreateRequest, PRSPanelRunRequest, RunCreateRequest, SampleCreateRequest, _discover_all_pgs_ids, _prs_panel_caveats, create_project, create_run_full, create_sample, prs_catalog_draft_manifest, prs_catalog_manifest, prs_catalog_manifest_validate, prs_panel_run
from app.store.memory_store import projects, run_events, run_logs, run_steps, runs, samples, variants


def _reset_stores():
    projects.clear()
    samples.clear()
    runs.clear()
    run_steps.clear()
    run_events.clear()
    run_logs.clear()
    variants.clear()


def _sample_with_variant(reference_id: str = "GRCh38_standard"):
    project = create_project(ProjectCreateRequest(name="Ppgs"))
    sample = create_sample(project.id, SampleCreateRequest(sample_id="S_PGS", reference_id=reference_id))
    run = create_run_full(project.id, RunCreateRequest(sample_id=sample.id, reference_id=reference_id))
    variants.append(VariantCall(id="v_pgs", sample_id=sample.sample_id, run_id=run.id, reference_id=reference_id, chrom="chr1", pos=1000, ref="A", alt="G"))
    return sample


def test_curated_pgs_manifest_defaults_to_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("WGS_PGS_CURATED_MANIFEST", str(tmp_path / "missing.tsv"))

    status = curated_manifest_status()
    items, count = search_curated_pgs()

    assert status["status"] == "missing"
    assert status["count"] == 0
    assert items == []
    assert count == 0


def test_curated_pgs_manifest_loads_tsv(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.tsv"
    manifest.write_text(
        "pgs_id\ttrait_reported\ttrait_category\tvariants_number\tpublication\tgenome_build\tmin_overlap\n"
        "PGS000001\tType 2 diabetes\tMetabolic\t1200\tDoe 2024\tGRCh38\t0.70\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WGS_PGS_CURATED_MANIFEST", str(manifest))

    loaded = load_curated_pgs_manifest()
    status = prs_catalog_manifest()
    validation = prs_catalog_manifest_validate()
    items, count = search_curated_pgs(q="diabetes")

    assert loaded[0]["pgs_id"] == "PGS000001"
    assert loaded[0]["min_overlap"] == 0.70
    assert status["status"] == "available"
    assert status["count"] == 1
    assert validation["valid"] is True
    assert count == 1
    assert items[0]["trait_category"] == "Metabolic"


def test_curated_pgs_manifest_warns_on_incomplete_metadata(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.tsv"
    manifest.write_text(
        "pgs_id\ttrait_reported\ttrait_category\tmin_overlap\n"
        "PGS000002\tCoronary artery disease\tCardiovascular\t0.25\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WGS_PGS_CURATED_MANIFEST", str(manifest))

    out = validate_curated_pgs_manifest()

    assert out["valid"] is True
    assert any("genome_build" in w for w in out["warnings"])
    assert any("min_overlap" in w for w in out["warnings"])


def test_draft_manifest_from_downloaded_scores(monkeypatch, tmp_path):
    pgs_dir = tmp_path / "pgs"
    pgs_dir.mkdir()
    (pgs_dir / "PGS000001.meta.json").write_text(
        '{"pgs_id":"PGS000001","pgs_name":"PRS77_BC","trait_reported":"Breast cancer","genome_build":"NR","variants_number":77,"ftp_url":"https://example/PGS000001.txt.gz"}',
        encoding="utf-8",
    )

    draft = draft_manifest_from_downloaded_scores(str(pgs_dir))
    tsv = draft_manifest_tsv(draft["items"])

    assert draft["status"] == "draft_available"
    assert draft["items"][0]["curation_status"] == "needs_review"
    assert draft["items"][0]["trait_category"] == "Cancer"
    assert "genome_build_missing_or_not_reported" in draft["items"][0]["warnings"]
    assert tsv.startswith("pgs_id\ttrait_reported")


def test_draft_manifest_endpoint_works(monkeypatch, tmp_path):
    monkeypatch.setenv("WGS_PGS_CURATED_MANIFEST", str(tmp_path / "missing.tsv"))
    out = prs_catalog_draft_manifest(limit=5)
    assert out["non_diagnostic"] is True
    assert "items" in out


def test_prs_panel_caveats_cover_overlap_coverage_build_and_ancestry():
    out = _prs_panel_caveats(
        {"match_rate": 0.34, "genome_build": None},
        {},
        {"ready": False, "reasons": ["no coverage metrics imported"]},
    )

    assert any("Variant overlap" in x for x in out)
    assert any("Coverage/readiness" in x for x in out)
    assert any("Genome build" in x for x in out)
    assert any("ancestry" in x.lower() for x in out)


def test_discover_all_pgs_ids_from_remote_payload(monkeypatch):
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'{"results":[{"id":"PGS000001"},{"id":"PGS000002"}]}'
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: FakeResponse())

    assert _discover_all_pgs_ids(limit=2) == ["PGS000001", "PGS000002"]


def test_prs_panel_run_requires_curated_manifest_before_downloaded_scores(monkeypatch, tmp_path):
    _reset_stores()
    sample = _sample_with_variant()
    monkeypatch.setenv("WGS_PGS_CURATED_MANIFEST", str(tmp_path / "missing.tsv"))

    with pytest.raises(HTTPException) as exc:
        prs_panel_run(PRSPanelRunRequest(sample_id=sample.sample_id))

    assert exc.value.status_code == 501
    assert exc.value.detail["code"] == "prs_curated_manifest_missing"


def test_prs_panel_run_blocks_manifest_build_mismatch(monkeypatch, tmp_path):
    _reset_stores()
    sample = _sample_with_variant("GRCh38_standard")
    manifest = tmp_path / "manifest.tsv"
    manifest.write_text(
        "pgs_id\ttrait_reported\ttrait_category\tvariants_number\tpublication\tgenome_build\tmin_overlap\n"
        "PGS000001\tBreast cancer\tCancer\t1200\tDoe 2024\tGRCh37\t0.70\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WGS_PGS_CURATED_MANIFEST", str(manifest))

    with pytest.raises(HTTPException) as exc:
        prs_panel_run(PRSPanelRunRequest(sample_id=sample.sample_id))

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "prs_manifest_build_mismatch"
