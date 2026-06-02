import json

from app import worker_queue
from app.pipeline_contract import PipelineJob


def test_parse_brpop_response_extracts_queue_and_payload():
    response = b"*2\r\n$17\r\nwgs:pipeline:jobs\r\n$18\r\n{\"run_id\":\"r1\"}\r\n"
    assert worker_queue._parse_brpop_response(response) == ("wgs:pipeline:jobs", '{"run_id":"r1"}')


def test_parse_brpop_response_accepts_nil_timeout():
    assert worker_queue._parse_brpop_response(b"*-1\r\n") is None


def test_consume_pipeline_job_once_runs_current_runner(monkeypatch):
    job = PipelineJob(
        run_id="run_1",
        sample_id="S1",
        reference_id="GRCh38_chr20",
        stages=["alignment"],
        required_stages=["alignment"],
    )
    payload = json.dumps(job.model_dump(), separators=(",", ":"))
    response = f"*2\r\n$17\r\nwgs:pipeline:jobs\r\n${len(payload)}\r\n{payload}\r\n".encode()
    calls = {}

    monkeypatch.setattr(worker_queue, "_redis_command", lambda *args, **kwargs: response)

    def fake_runner(*args):
        calls["args"] = args

    monkeypatch.setattr(worker_queue, "_run_pipeline_background", fake_runner)

    ok, status = worker_queue.consume_pipeline_job_once(
        redis_url="redis://redis:6379/0",
        queue_name="wgs:pipeline:jobs",
        timeout_seconds=1,
    )

    assert ok is True
    assert status == "pipeline_job_done"
    assert calls["args"][0] == "run_1"
    assert calls["args"][2] == []
    assert calls["args"][4] == ["alignment"]
