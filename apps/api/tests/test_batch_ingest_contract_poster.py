import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "pipelines/nextflow/scripts/post_ingest_contracts_batch.py"


def _write_contract(path: Path, stage: str, payload: dict | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"event_type": "run.ingest.request", "stage": stage, "payload": payload or {}}),
        encoding="utf-8",
    )


def test_batch_poster_dry_run_orders_pipeline_stages_and_injects_run_id(tmp_path: Path):
    _write_contract(tmp_path / "variants" / "S1.variants.ingest.json", "variants", {"variants_vcf_path": "v.vcf"})
    _write_contract(tmp_path / "alignment" / "S1.alignment.ingest.json", "alignment", {"flagstat_txt": "f.txt"})
    _write_contract(tmp_path / "coverage" / "S1.coverage.ingest.json", "coverage", {"mosdepth_summary_txt": "m.txt"})
    out = tmp_path / "batch.json"

    subprocess.run(
        [str(SCRIPT), "--root", str(tmp_path), "--run-id", "run_abc", "--dry-run", "--output", str(out)],
        check=True,
    )

    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["discovered_count"] == 3
    assert [r["stage"] for r in result["results"]] == ["alignment", "coverage", "variants"]
    assert all("/runs/run_abc/ingest" in r["url"] for r in result["results"])


def test_batch_poster_can_filter_stage(tmp_path: Path):
    _write_contract(tmp_path / "S1.alignment.ingest.json", "alignment")
    _write_contract(tmp_path / "S1.coverage.ingest.json", "coverage")
    out = tmp_path / "coverage-only.json"

    subprocess.run(
        [str(SCRIPT), "--root", str(tmp_path), "--run-id", "run_abc", "--stage", "coverage", "--dry-run", "--output", str(out)],
        check=True,
    )

    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["processed_count"] == 1
    assert result["results"][0]["stage"] == "coverage"


def test_batch_poster_reports_validation_errors(tmp_path: Path):
    _write_contract(tmp_path / "bad.ingest.json", "badstage")
    out = tmp_path / "bad.json"

    proc = subprocess.run(
        [str(SCRIPT), "--root", str(tmp_path), "--run-id", "run_abc", "--dry-run", "--output", str(out)],
        text=True,
        capture_output=True,
    )

    assert proc.returncode == 1
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["results"][0]["phase"] == "validation"
    assert "unsupported_stage" in result["results"][0]["error"]


def test_batch_poster_can_absolutize_payload_paths(tmp_path: Path):
    contract_dir = tmp_path / "alignment"
    _write_contract(
        contract_dir / "S1.alignment.ingest.json",
        "alignment",
        {"flagstat_txt": "S1.flagstat.txt", "source_files": ["S1.bam", "already_note"]},
    )
    out = tmp_path / "abs.json"

    subprocess.run(
        [
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--run-id",
            "run_abs",
            "--dry-run",
            "--absolutize-payload-paths",
            "--output",
            str(out),
        ],
        check=True,
    )

    payload = json.loads(out.read_text(encoding="utf-8"))["results"][0]["request"]["payload"]
    assert payload["flagstat_txt"] == str((contract_dir / "S1.flagstat.txt").resolve())
    assert payload["source_files"][0] == str((contract_dir / "S1.bam").resolve())


def test_batch_poster_absolutizes_variant_and_coverage_payload_paths(tmp_path: Path):
    _write_contract(
        tmp_path / "coverage" / "S1.coverage.ingest.json",
        "coverage",
        {"mosdepth_summary_txt": "S1.summary.txt", "mosdepth_regions_bed_gz": "S1.regions.bed.gz"},
    )
    _write_contract(
        tmp_path / "variants" / "S1.variants.ingest.json",
        "variants",
        {"variants_vcf_path": "S1.vcf"},
    )
    out = tmp_path / "abs2.json"

    subprocess.run(
        [
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--run-id",
            "run_abs2",
            "--dry-run",
            "--absolutize-payload-paths",
            "--output",
            str(out),
        ],
        check=True,
    )

    results = json.loads(out.read_text(encoding="utf-8"))["results"]
    coverage = next(r for r in results if r["stage"] == "coverage")["request"]["payload"]
    variants = next(r for r in results if r["stage"] == "variants")["request"]["payload"]
    assert coverage["mosdepth_summary_txt"] == str((tmp_path / "coverage" / "S1.summary.txt").resolve())
    assert coverage["mosdepth_regions_bed_gz"] == str((tmp_path / "coverage" / "S1.regions.bed.gz").resolve())
    assert variants["variants_vcf_path"] == str((tmp_path / "variants" / "S1.vcf").resolve())
