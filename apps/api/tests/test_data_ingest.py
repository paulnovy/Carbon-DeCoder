"""Tests for data ingest API endpoints."""
import io
import tarfile
from collections import namedtuple
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.routers import data_ingest

client = TestClient(app)


def test_scan_empty_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_INPUT_DIR", str(tmp_path))
    resp = client.get("/data/scan")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []


def test_scan_with_fastq_files(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_INPUT_DIR", str(tmp_path))
    (tmp_path / "sample1_R1.fastq.gz").write_bytes(b"\x1f\x8b")
    (tmp_path / "sample1_R2.fastq.gz").write_bytes(b"\x1f\x8b")
    (tmp_path / "sample2.fq").write_text("@r\nACGT\n+\n!!!!\n")
    (tmp_path / "readme.txt").write_text("hello")

    resp = client.get("/data/scan")
    data = resp.json()
    fastq_files = [f for f in data["items"] if f["type"] == "fastq"]
    assert len(fastq_files) == 3


def test_scan_detects_pairing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_INPUT_DIR", str(tmp_path))
    (tmp_path / "WGS1_R1.fastq.gz").write_bytes(b"\x1f\x8b")
    (tmp_path / "WGS1_R2.fastq.gz").write_bytes(b"\x1f\x8b")

    resp = client.get("/data/scan")
    files = resp.json()["items"]
    roles = {f["name"]: f["paired"] for f in files}
    assert roles["WGS1_R1.fastq.gz"] == "R1"
    assert roles["WGS1_R2.fastq.gz"] == "R2"


def test_pair_role_casava_detection():
    assert data_ingest._pair_role("Sample_S1_L001_R1_001.fastq.gz") == "R1"


def test_vendor_detection_sra():
    assert data_ingest._detect_vendor("SRR12345678_1.fastq.gz") == "sra"


def test_upload_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_INPUT_DIR", str(tmp_path))
    content = b"test content"
    resp = client.post(
        "/data/upload",
        files={"file": ("test.fastq.gz", content, "application/octet-stream")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "test.fastq.gz"
    assert data["size"] == len(content)
    assert data["storage_preflight"]["ok"] is True
    assert (tmp_path / "test.fastq.gz").exists()


def test_upload_blocks_when_min_free_floor_would_be_crossed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_INPUT_DIR", str(tmp_path))
    monkeypatch.setenv("WGS_INPUT_MIN_FREE_GB", "1")
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr(data_ingest.shutil, "disk_usage", lambda _path: DiskUsage(2 * 1024**3, 2 * 1024**3 - 512, 512))

    resp = client.post(
        "/data/upload",
        files={"file": ("test.fastq.gz", b"test content", "application/octet-stream")},
    )

    assert resp.status_code == 507
    assert resp.json()["detail"]["code"] == "insufficient_input_storage"


def test_deepvariant_tool_probe_uses_run_deepvariant_alias(monkeypatch):
    monkeypatch.setattr(data_ingest.shutil, "which", lambda name: "/usr/bin/run_deepvariant" if name == "run_deepvariant" else None)
    monkeypatch.setattr(
        data_ingest.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="DeepVariant version 1.8.0\n", stderr="", returncode=0),
    )

    details = data_ingest._probe_tool("deepvariant")

    assert details["installed"] is True
    assert details["path"] == "/usr/bin/run_deepvariant"
    assert details["version"] == "DeepVariant version 1.8.0"


def test_browse_reports_bam_preparation_status(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_INPUT_DIR", str(tmp_path))
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"BAM")
    monkeypatch.setattr(data_ingest, "_samtools_sort_order", lambda _path: ("queryname", None))
    monkeypatch.setattr(data_ingest.shutil, "which", lambda tool: f"/usr/bin/{tool}" if tool == "samtools" else None)

    resp = client.get("/data/browse")
    assert resp.status_code == 200
    item = next(i for i in resp.json()["items"] if i["name"] == "sample.bam")
    assert item["preflight"]["ready"] is False
    assert item["preflight"]["prepare_action"] == "sort_and_index"
    assert "bam_index_missing" in item["preflight"]["warnings"]
    assert "bam_not_coordinate_sorted" in item["preflight"]["warnings"]


def test_browse_directory_reports_illumina_fastq_preset(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_INPUT_DIR", str(tmp_path))
    flowcell = tmp_path / "flowcell_a"
    flowcell.mkdir()
    (flowcell / "SampleSheet.csv").write_text("[Data]\n", encoding="utf-8")
    (flowcell / "S1_S1_L001_R1_001.fastq.gz").write_bytes(b"r1")
    (flowcell / "S1_S1_L001_R2_001.fastq.gz").write_bytes(b"r2")

    resp = client.get("/data/browse")

    assert resp.status_code == 200
    item = next(entry for entry in resp.json()["items"] if entry["name"] == "flowcell_a")
    assert item["preset"]["id"] == "illumina_fastq_folder"
    assert item["preset"]["vendor"] == "illumina"
    assert item["preset"]["fastq_pairs"] == 1
    assert item["preset"]["recommended_action"] == "start_pipeline"
    assert item["preset"]["recommended_paths"] == [
        "flowcell_a/S1_S1_L001_R1_001.fastq.gz",
        "flowcell_a/S1_S1_L001_R2_001.fastq.gz",
    ]


def test_browse_directory_reports_single_bam_preset(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_INPUT_DIR", str(tmp_path))
    vendor_dir = tmp_path / "vendor_bam"
    vendor_dir.mkdir()
    (vendor_dir / "sample.sorted.bam").write_bytes(b"bam")

    resp = client.get("/data/browse")

    assert resp.status_code == 200
    item = next(entry for entry in resp.json()["items"] if entry["name"] == "vendor_bam")
    assert item["preset"]["id"] == "prealigned_bam_folder"
    assert item["preset"]["recommended_action"] == "start_pipeline"
    assert item["preset"]["recommended_paths"] == ["vendor_bam/sample.sorted.bam"]


def test_prepare_index_job_updates_status(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_INPUT_DIR", str(tmp_path))
    bam = tmp_path / "sample.bam"
    bam.write_bytes(b"BAM")
    monkeypatch.setattr(data_ingest, "_samtools_sort_order", lambda _path: ("coordinate", None))
    monkeypatch.setattr(data_ingest.shutil, "which", lambda tool: f"/usr/bin/{tool}" if tool == "samtools" else None)

    def fake_run(cmd, capture_output=False, text=False, check=False, stdout=None, stderr=None, timeout=None):
        if cmd[:2] == ["samtools", "index"]:
            Path(str(cmd[-1]) + ".bai").write_text("index", encoding="utf-8")

        class Completed:
            returncode = 0
            stderr = ""
            stdout = ""

        return Completed()

    class ImmediateThread:
        def __init__(self, target=None, args=(), daemon=True):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(data_ingest.subprocess, "run", fake_run)
    monkeypatch.setattr(data_ingest.threading, "Thread", ImmediateThread)

    resp = client.post("/data/prepare", json={"path": "sample.bam"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["progress_pct"] == 100
    assert body["storage_preflight"]["ok"] is True
    assert body["output_relative_path"] == "sample.bam"
    assert (tmp_path / "sample.bam.bai").exists()


def test_capabilities_returns_expected_keys(monkeypatch):
    monkeypatch.setattr(
        data_ingest,
        "_probe_tool",
        lambda tool: {"installed": tool == "samtools", "path": f"/usr/bin/{tool}", "version": "test-version", "version_probe": "ok"},
    )

    resp = client.get("/data/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu" in data
    assert "gpu" in data
    assert "tools" in data
    assert "tool_details" in data
    assert data["tools"]["samtools"] is True
    assert data["tool_details"]["samtools"]["version"] == "test-version"
    assert "estimates_30x_wgs" in data


def test_probe_tool_reports_binary_path_and_version(monkeypatch):
    monkeypatch.setattr(data_ingest.shutil, "which", lambda tool: "/usr/bin/samtools" if tool == "samtools" else None)

    def fake_run(cmd, **kwargs):
        assert cmd == ["samtools", "--version"]
        return data_ingest.subprocess.CompletedProcess(cmd, 0, stdout="samtools 1.20\nUsing htslib\n", stderr="")

    monkeypatch.setattr(data_ingest.subprocess, "run", fake_run)

    detail = data_ingest._probe_tool("samtools")

    assert detail == {
        "installed": True,
        "path": "/usr/bin/samtools",
        "version": "samtools 1.20",
        "version_probe": "ok",
    }


def _tar_with_kraken_files() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in [("hash.k2d", b"h"), ("opts.k2d", b"o"), ("taxo.k2d", b"t")]:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_list_taxonomy_databases(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_KRAKEN_DB_DIR", str(tmp_path / "kraken2"))
    data_ingest.TAXONOMY_DB_DIR = Path(tmp_path / "kraken2")
    resp = client.get("/data/taxonomy-databases")
    assert resp.status_code == 200
    items = resp.json()
    assert any(i["id"] == "viral" for i in items)
    assert all("installed" in i for i in items)
    viral = next(i for i in items if i["id"] == "viral")
    assert viral["storage_preflight"]["required_bytes"] > 0
    assert "free_bytes" in viral["storage_preflight"]


def test_install_taxonomy_database_success(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_KRAKEN_DB_DIR", str(tmp_path / "kraken2"))
    data_ingest.TAXONOMY_DB_DIR = Path(tmp_path / "kraken2")
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr(
        data_ingest.shutil,
        "disk_usage",
        lambda _path: DiskUsage(100 * 1024**3, 10 * 1024**3, 90 * 1024**3),
    )

    tar_bytes = _tar_with_kraken_files()

    class FakeResponse:
        def __init__(self, payload: bytes, headers: dict[str, str] | None = None):
            self._bio = io.BytesIO(payload)
            self.headers = headers or {}

        def read(self, n: int = -1):
            return self._bio.read(n)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(_req):
        return FakeResponse(tar_bytes, {"Content-Length": str(len(tar_bytes))})

    class ImmediateThread:
        def __init__(self, target=None, args=(), daemon=True):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(data_ingest.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(data_ingest.threading, "Thread", ImmediateThread)

    resp = client.post("/data/taxonomy-databases/install", json={"database": "viral"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status = client.get(f"/data/taxonomy-databases/install/{job_id}")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "done"
    assert body["storage_preflight"]["ok"] is True
    assert (tmp_path / "kraken2" / "viral" / "hash.k2d").exists()


def test_install_taxonomy_database_resumes_partial_archive(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WGS_KRAKEN_DB_DIR", str(tmp_path / "kraken2"))
    data_ingest.TAXONOMY_DB_DIR = Path(tmp_path / "kraken2")
    data_ingest.TAXONOMY_INSTALL_JOBS.clear()
    data_ingest.TAXONOMY_DB_DIR.mkdir(parents=True)
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr(
        data_ingest.shutil,
        "disk_usage",
        lambda _path: DiskUsage(100 * 1024**3, 10 * 1024**3, 90 * 1024**3),
    )

    tar_bytes = _tar_with_kraken_files()
    resume_from = 12
    (data_ingest.TAXONOMY_DB_DIR / "viral.tar.gz").write_bytes(tar_bytes[:resume_from])
    seen_headers = {}

    class FakeResponse:
        status = 206

        def __init__(self):
            self._bio = io.BytesIO(tar_bytes[resume_from:])
            self.headers = {
                "Content-Length": str(len(tar_bytes) - resume_from),
                "Content-Range": f"bytes {resume_from}-{len(tar_bytes) - 1}/{len(tar_bytes)}",
            }

        def read(self, n: int = -1):
            return self._bio.read(n)

        def getcode(self):
            return self.status

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req):
        seen_headers.update(req.header_items())
        return FakeResponse()

    class ImmediateThread:
        def __init__(self, target=None, args=(), daemon=True):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(data_ingest.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(data_ingest.threading, "Thread", ImmediateThread)

    resp = client.post("/data/taxonomy-databases/install", json={"database": "viral"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == "taxdb_viral"

    status = client.get("/data/taxonomy-databases/install/taxdb_viral").json()
    assert status["status"] == "done"
    assert status["resume_accepted"] is True
    assert status["resumed_from_bytes"] == resume_from
    assert seen_headers["Range"] == f"bytes={resume_from}-"
    assert (tmp_path / "kraken2" / "viral" / "hash.k2d").exists()


def test_install_taxonomy_database_blocks_when_storage_estimate_exceeds_free(tmp_path: Path, monkeypatch):
    data_ingest.TAXONOMY_DB_DIR = Path(tmp_path / "kraken2")
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr(
        data_ingest.shutil,
        "disk_usage",
        lambda _path: DiskUsage(10 * 1024**3, 9 * 1024**3, 1 * 1024**3),
    )

    resp = client.post("/data/taxonomy-databases/install", json={"database": "standard"})

    assert resp.status_code == 507
    detail = resp.json()["detail"]
    assert detail["code"] == "taxonomy_database_insufficient_storage"
    assert detail["storage"]["ok"] is False
    assert detail["storage"]["required_bytes"] > detail["storage"]["free_bytes"]


def test_safe_extract_taxonomy_tar_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(name="../escape.txt")
        payload = b"bad"
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))

    with tarfile.open(archive, "r:gz") as tf:
        try:
            data_ingest._safe_extract_tar(tf, tmp_path / "dest")
            assert False, "expected unsafe archive rejection"
        except ValueError as exc:
            assert "unsafe archive member" in str(exc)


def test_custom_reference_crud(tmp_path: Path, monkeypatch):
    data_ingest.CUSTOM_REFS_DIR = tmp_path / "references"

    upload = client.post(
        "/data/references/upload",
        data={"name": "hg38", "organism": "Human", "description": "GRCh38"},
        files={"file": ("hg38.fa", b">chr1\nACGT\n", "application/octet-stream")},
    )
    assert upload.status_code == 200
    body = upload.json()
    assert body["name"] == "hg38"

    listed = client.get("/data/references/custom")
    assert listed.status_code == 200
    refs = listed.json()
    assert len(refs) == 1
    assert refs[0]["name"] == "hg38"

    deleted = client.delete("/data/references/hg38")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == "hg38"

    listed2 = client.get("/data/references/custom")
    assert listed2.status_code == 200
    assert listed2.json() == []
