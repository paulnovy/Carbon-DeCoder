import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class _MockHandler(BaseHTTPRequestHandler):
    state = {
        "project_id": "prj_live",
        "sample_id": "smp_live",
        "sample_code": "S_vendor_e2e_live",
        "run_id": "run_live",
        "latest": None,
    }

    def _send(self, code: int, obj: dict):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(body or "{}")

        if self.path == "/projects":
            return self._send(200, {"id": self.state["project_id"], "name": payload.get("name", "P")})

        if self.path == f"/projects/{self.state['project_id']}/samples":
            self.state["sample_code"] = payload.get("sample_id", self.state["sample_code"])
            return self._send(
                200,
                {
                    "id": self.state["sample_id"],
                    "sample_id": self.state["sample_code"],
                    "reference_id": payload.get("reference_id", "GRCh38_standard"),
                },
            )

        if self.path == f"/projects/{self.state['project_id']}/run/full":
            return self._send(200, {"id": self.state["run_id"], "sample_id": self.state["sample_id"]})

        if self.path == f"/runs/{self.state['run_id']}/ingest":
            stage = payload.get("stage")
            p = payload.get("payload", {})
            self.state["latest"] = {
                "id": "vav_live",
                "run_id": self.state["run_id"],
                "sample_id": self.state["sample_code"],
                "status": "passed",
                "similarity_score": 0.99,
                "comparator_method": p.get("comparator_method", "proxy"),
                "kmer_size": p.get("kmer_size"),
            }
            return self._send(200, {"status": "accepted", "stage": stage})

        return self._send(404, {"detail": "not_found"})

    def do_GET(self):
        if self.path == f"/runs/{self.state['run_id']}/validation/vendor-assembly/latest":
            return self._send(200, self.state["latest"] or {"detail": "missing"})

        if self.path == f"/runs/{self.state['run_id']}/validation/vendor-assembly/gate":
            return self._send(
                200,
                {
                    "run_id": self.state["run_id"],
                    "gate_status": "passed",
                    "latest_status": "passed",
                    "non_diagnostic": True,
                },
            )

        return self._send(404, {"detail": "not_found"})

    def log_message(self, fmt, *args):
        return


def test_vendor_validation_live_e2e_script(tmp_path: Path):
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        vendor = tmp_path / "vendor.fa"
        vendor.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")
        pipeline = tmp_path / "pipeline.fa"
        pipeline.write_text(">chr1\nACGTACGTTCGT\n", encoding="utf-8")

        outdir = tmp_path / "live"
        script = Path(__file__).resolve().parents[3] / "pipelines/nextflow/scripts/vendor_validation_live_e2e.py"
        base = f"http://127.0.0.1:{server.server_port}"

        subprocess.run(
            [
                "python3",
                str(script),
                "--api-base-url",
                base,
                "--vendor",
                str(vendor),
                "--pipeline",
                str(pipeline),
                "--method",
                "kmer",
                "--kmer-size",
                "9",
                "--pass-threshold",
                "0.5",
                "--outdir",
                str(outdir),
            ],
            check=True,
        )

        summary = json.loads((outdir / "vendor_validation.live_e2e.summary.json").read_text(encoding="utf-8"))
        assert summary["run_id"] == "run_live"
        assert summary["latest_validation"]["comparator_method"] == "kmer"
        assert summary["run_gate"]["gate_status"] == "passed"
        assert summary["pipeline_assembly_path"].endswith("pipeline.fa")
    finally:
        server.shutdown()
        server.server_close()


def test_vendor_validation_live_e2e_script_builds_pipeline_from_fastq(tmp_path: Path):
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        vendor = tmp_path / "vendor.fa"
        vendor.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")
        r1 = tmp_path / "R1.fastq"
        r2 = tmp_path / "R2.fastq"
        r1.write_text("@r1\nACGT\n+\n####\n", encoding="utf-8")
        r2.write_text("@r2\nTTAA\n+\n####\n", encoding="utf-8")

        outdir = tmp_path / "live_fastq"
        script = Path(__file__).resolve().parents[3] / "pipelines/nextflow/scripts/vendor_validation_live_e2e.py"
        base = f"http://127.0.0.1:{server.server_port}"

        subprocess.run(
            [
                "python3",
                str(script),
                "--api-base-url",
                base,
                "--vendor",
                str(vendor),
                "--r1",
                str(r1),
                "--r2",
                str(r2),
                "--method",
                "proxy",
                "--outdir",
                str(outdir),
            ],
            check=True,
        )

        summary = json.loads((outdir / "vendor_validation.live_e2e.summary.json").read_text(encoding="utf-8"))
        assert summary["run_id"] == "run_live"
        assert summary["pipeline_assembly_path"].endswith("pipeline_assembly.from_fastq.fasta")
        assert Path(summary["pipeline_assembly_path"]).exists()
    finally:
        server.shutdown()
        server.server_close()
