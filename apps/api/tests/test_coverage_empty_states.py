from app.routers.foundation import (
    ProjectCreateRequest,
    SampleCreateRequest,
    create_project,
    create_sample,
    get_coverage_terrain,
    get_coverage_summary,
    get_coverage_tiles,
)
from app.store.memory_store import projects, samples


def _reset_stores():
    projects.clear()
    samples.clear()


def test_missing_coverage_endpoints_return_honest_empty_shape():
    _reset_stores()

    project = create_project(ProjectCreateRequest(name="Pcov"))
    create_sample(project.id, SampleCreateRequest(sample_id="S_cov", reference_id="GRCh38_standard"))

    summary = get_coverage_summary("S_cov")
    tiles = get_coverage_tiles("S_cov", level="1mb")
    terrain = get_coverage_terrain("S_cov", level="1mb")

    assert "status" in summary
    assert summary["status"] == "missing"
    assert "tiles" in tiles
    assert tiles["status"] == "missing"
    assert tiles["mode"] == "not_imported"
    assert tiles["tiles"] == []
    assert terrain["status"] == "missing"
    assert terrain["mode"] == "not_imported"
    assert terrain["summary"]["tile_count"] == 0
