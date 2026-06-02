import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class _MockApiFromFastqHandler(BaseHTTPRequestHandler):
    state = {
        "project_id": "prj_api_fastq",
        "sample_id": "smp_api_fastq",
        "sample_code": "S_vendor_api_fastq_e2e",
        "run_id": "run_api_fastq",
        "latest": {
            "id": "vav_api_fastq",
            "status": "passed",
            "comparator_method": "kmer",
            "kmer_size": 9,
        },
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
            return self._send(
                200,
                {
                    "id": self.state["sample_id"],
                    "sample_id": payload.get("sample_id", self.state["sample_code"]),
                    "reference_id": payload.get("reference_id", "GRCh38_standard"),
                },
            )

        if self.path == f"/projects/{self.state['project_id']}/run/full":
            return self._send(200, {"id": self.state["run_id"], "sample_id": self.state["sample_id"]})

        if self.path == f"/runs/{self.state['run_id']}/validation/vendor-assembly/import-from-fastq":
            return self._send(
                200,
                {
                    "run_id": self.state["run_id"],
                    "pipeline_assembly_path": "/tmp/pipeline_assembly.from_fastq.fasta",
                    "validation": {
                        "id": "vav_api_fastq",
                        "status": "passed",
                        "comparator_method": payload.get("comparator_method", "proxy"),
                        "kmer_size": payload.get("kmer_size"),
                    },
                    "non_diagnostic": True,
                },
            )

        if self.path == f"/runs/{self.state['run_id']}/reports/generate-all":
            return self._send(
                200,
                {
                    "count": 13,
                    "bundle_manifest_path": "results/reports/run_api_fastq/bundle_manifest.json",
                    "bundle_index_path": "results/reports/run_api_fastq/index.html",
                },
            )

        return self._send(404, {"detail": "not_found"})

    def do_GET(self):
        if self.path == f"/runs/{self.state['run_id']}/validation/vendor-assembly/latest":
            return self._send(200, self.state["latest"])

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


def test_vendor_validation_api_from_fastq_e2e_script(tmp_path: Path):
    server = HTTPServer(("127.0.0.1", 0), _MockApiFromFastqHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        vendor = tmp_path / "vendor.fa"
        vendor.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")
        r1 = tmp_path / "R1.fastq"
        r2 = tmp_path / "R2.fastq"
        r1.write_text("@r1\nACGT\n+\n####\n", encoding="utf-8")
        r2.write_text("@r2\nTTAA\n+\n####\n", encoding="utf-8")

        outdir = tmp_path / "api_fastq"
        script = Path(__file__).resolve().parents[3] / "pipelines/nextflow/scripts/vendor_validation_api_from_fastq_e2e.py"
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

        summary = json.loads((outdir / "vendor_validation.api_from_fastq_e2e.summary.json").read_text(encoding="utf-8"))
        assert summary["run_id"] == "run_api_fastq"
        assert summary["import_result"]["validation"]["comparator_method"] == "kmer"
        assert summary["run_gate"]["gate_status"] == "passed"
        assert summary["report_bundle"]["count"] == 13
    finally:
        server.shutdown()
        server.server_close()
