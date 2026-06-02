import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import data_ingest, foundation
from app.routers.foundation import ReferenceActionRequest, ReferenceCreateRequest, reference_download


class _ImmediateThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class _FakeDownloadResponse:
    def __init__(self, content: bytes):
        self._content = content
        self._offset = 0
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._content):
            return b""
        if size is None or size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_reference_download_unknown_ref_raises_404():
    with pytest.raises(HTTPException) as exc:
        reference_download(ReferenceActionRequest(reference_id="does-not-exist"))
    assert exc.value.status_code == 404


def _install_synchronous_reference_download(monkeypatch, tmp_path: Path, content: bytes):
    monkeypatch.setattr(foundation, "REFERENCE_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(foundation.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        foundation.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _FakeDownloadResponse(content),
    )
    monkeypatch.setattr(foundation.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=1))


def test_reference_download_verifies_configured_sha256(tmp_path, monkeypatch):
    reference_id = "test_sha256_ok"
    content = b">chr1\nACGT\n"
    checksum = hashlib.sha256(content).hexdigest()
    _install_synchronous_reference_download(monkeypatch, tmp_path, content)
    data_ingest.DOWNLOAD_JOBS.clear()
    foundation.REFERENCE_DOWNLOAD_URLS.pop(reference_id, None)

    try:
        foundation.create_reference(
            ReferenceCreateRequest(
                id=reference_id,
                source="unit-test",
                download_url="https://example.test/ref.fa",
                download_sha256=f"sha256: {checksum}",
            )
        )

        response = foundation.download_reference(reference_id)
        status = data_ingest.import_from_url_status(response["job_id"])

        assert status["status"] == "done"
        assert status["phase"] == "done"
        assert status["progress_pct"] == 100
        assert status["filename"] == "ref.fa"
        assert status["checksum"]["status"] == "verified"
        assert status["checksum"]["algorithm"] == "sha256"
        assert status["checksum"]["actual"] == checksum
        assert Path(response["destination"]).read_bytes() == content
    finally:
        foundation.remove_reference(reference_id)
        foundation.REFERENCE_DOWNLOAD_URLS.pop(reference_id, None)


def test_reference_download_rejects_sha256_mismatch(tmp_path, monkeypatch):
    reference_id = "test_sha256_bad"
    content = b">chr1\nACGT\n"
    expected = hashlib.sha256(b"different reference").hexdigest()
    _install_synchronous_reference_download(monkeypatch, tmp_path, content)
    data_ingest.DOWNLOAD_JOBS.clear()
    foundation.REFERENCE_DOWNLOAD_URLS.pop(reference_id, None)

    try:
        foundation.create_reference(
            ReferenceCreateRequest(
                id=reference_id,
                source="unit-test",
                download_url="https://example.test/ref.fa",
                download_sha256=expected,
            )
        )

        response = foundation.download_reference(reference_id)
        status = data_ingest.import_from_url_status(response["job_id"])

        assert status["status"] == "failed"
        assert status["phase"] == "failed"
        assert status["error"] == "reference_checksum_mismatch"
        assert status["checksum"]["status"] == "failed"
        assert status["checksum"]["expected"] == expected
        assert not Path(response["destination"]).exists()
    finally:
        foundation.remove_reference(reference_id)
        foundation.REFERENCE_DOWNLOAD_URLS.pop(reference_id, None)
