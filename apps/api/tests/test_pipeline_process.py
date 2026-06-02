import signal
import subprocess
import sys

from app import pipeline_process


class FakeProcess:
    pid = 4242

    def __init__(self, timeouts_before_success: int):
        self.timeouts_before_success = timeouts_before_success
        self.calls = 0

    def communicate(self, timeout=None):
        self.calls += 1
        if self.calls <= self.timeouts_before_success:
            raise subprocess.TimeoutExpired("stage", timeout)
        return "stdout", "stderr"

    def poll(self):
        return None


def test_communicate_stage_process_terminates_on_cancel(monkeypatch):
    proc = FakeProcess(timeouts_before_success=1)
    signals = []

    monkeypatch.setattr(pipeline_process.os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    stdout, stderr = pipeline_process.communicate_stage_process(
        proc,
        run_id="run_1",
        stage_name="alignment",
        timeout_seconds=30,
        status_for_run=lambda _run_id: "cancelling",
        pause_requested=lambda _run_id: False,
        cancel_requested=lambda _run_id: False,
        emit_event=lambda *_args: None,
    )

    assert (stdout, stderr) == ("stdout", "stderr")
    assert signals == [(4242, signal.SIGTERM)]


def test_communicate_stage_process_pauses_and_resumes(monkeypatch):
    proc = FakeProcess(timeouts_before_success=2)
    statuses = iter(["paused", "running"])
    signals = []
    events = []

    monkeypatch.setattr(pipeline_process.os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    stdout, stderr = pipeline_process.communicate_stage_process(
        proc,
        run_id="run_1",
        stage_name="alignment",
        timeout_seconds=30,
        status_for_run=lambda _run_id: next(statuses),
        pause_requested=lambda _run_id: False,
        cancel_requested=lambda _run_id: False,
        emit_event=lambda run_id, event_type, data: events.append((run_id, event_type, data)),
    )

    assert (stdout, stderr) == ("stdout", "stderr")
    assert signals == [(4242, signal.SIGSTOP), (4242, signal.SIGCONT)]
    assert [event[1] for event in events] == ["stage_process_paused", "stage_process_resumed"]
    assert all(event[2]["mode"] == "owner_process" for event in events)


def test_communicate_stage_process_streams_stdout_and_stderr_events():
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; print('out-1', flush=True); print('err-1', file=sys.stderr, flush=True); time.sleep(0.1); print('out-2', flush=True)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    events = []

    stdout, stderr = pipeline_process.communicate_stage_process(
        proc,
        run_id="run_1",
        stage_name="variants",
        timeout_seconds=10,
        status_for_run=lambda _run_id: "running",
        pause_requested=lambda _run_id: False,
        cancel_requested=lambda _run_id: False,
        emit_event=lambda run_id, event_type, data: events.append((run_id, event_type, data)),
    )

    assert "out-1" in stdout
    assert "out-2" in stdout
    assert "err-1" in stderr
    output_events = [event for event in events if event[1] == "stage_process_output"]
    assert output_events
    assert output_events[-1][2]["stage"] == "variants"
    assert "out-2" in output_events[-1][2]["stdout_tail"]
    assert "err-1" in output_events[-1][2]["stderr_tail"]
