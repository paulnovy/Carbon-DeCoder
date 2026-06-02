"""Process-control helpers for pipeline stage subprocesses."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable


RunStatusGetter = Callable[[str | None], str | None]
RunFlagGetter = Callable[[str], bool]
RunEventEmitter = Callable[[str, str, dict], None]


def _tail(text: str, limit: int = 2000) -> str:
    return text[-limit:] if len(text) > limit else text


def _reader_thread(stream, stream_name: str, output: queue.Queue[tuple[str, str | None]]) -> None:
    try:
        for line in iter(stream.readline, ""):
            if line:
                output.put((stream_name, line))
    finally:
        output.put((stream_name, None))


def _emit_output_batch(
    *,
    run_id: str | None,
    stage_name: str,
    pid: int,
    emit_event: RunEventEmitter,
    stdout_pending: list[str],
    stderr_pending: list[str],
    stdout_parts: list[str],
    stderr_parts: list[str],
    started: float,
) -> None:
    if not run_id or (not stdout_pending and not stderr_pending):
        stdout_pending.clear()
        stderr_pending.clear()
        return

    payload = {
        "stage": stage_name,
        "pid": pid,
        "elapsed_sec": round(time.monotonic() - started, 2),
        "stdout_tail": _tail("".join(stdout_parts)),
        "stderr_tail": _tail("".join(stderr_parts)),
        "stdout_lines": stdout_pending[-20:],
        "stderr_lines": stderr_pending[-20:],
    }
    emit_event(run_id, "stage_process_output", {k: v for k, v in payload.items() if v not in (None, "", [])})
    stdout_pending.clear()
    stderr_pending.clear()


def _communicate_stage_process_streaming(
    proc: subprocess.Popen,
    *,
    run_id: str | None,
    stage_name: str,
    timeout_seconds: int,
    status_for_run: RunStatusGetter,
    pause_requested: RunFlagGetter,
    cancel_requested: RunFlagGetter,
    emit_event: RunEventEmitter,
) -> tuple[str, str]:
    started = time.monotonic()
    paused_since: float | None = None
    paused_total = 0.0
    paused = False
    pause_event_emitted = False
    resume_event_emitted = False
    timeout_enabled = timeout_seconds > 0
    last_output_event = started
    last_heartbeat = started
    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    streams_done = {"stdout": False, "stderr": False}
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    stdout_pending: list[str] = []
    stderr_pending: list[str] = []

    threads = [
        threading.Thread(target=_reader_thread, args=(proc.stdout, "stdout", output_queue), daemon=True),
        threading.Thread(target=_reader_thread, args=(proc.stderr, "stderr", output_queue), daemon=True),
    ]
    for thread in threads:
        thread.start()

    def drain_output() -> None:
        while True:
            try:
                stream_name, line = output_queue.get_nowait()
            except queue.Empty:
                return
            if line is None:
                streams_done[stream_name] = True
                continue
            if stream_name == "stdout":
                stdout_parts.append(line)
                stdout_pending.append(line.rstrip("\n"))
            else:
                stderr_parts.append(line)
                stderr_pending.append(line.rstrip("\n"))

    while True:
        now = time.monotonic()
        effective_elapsed = now - started - paused_total
        drain_output()

        if stdout_pending or stderr_pending:
            if now - last_output_event >= 5 or len(stdout_pending) + len(stderr_pending) >= 20:
                _emit_output_batch(
                    run_id=run_id,
                    stage_name=stage_name,
                    pid=proc.pid,
                    emit_event=emit_event,
                    stdout_pending=stdout_pending,
                    stderr_pending=stderr_pending,
                    stdout_parts=stdout_parts,
                    stderr_parts=stderr_parts,
                    started=started,
                )
                last_output_event = now

        if run_id and now - last_heartbeat >= 30 and proc.poll() is None:
            emit_event(
                run_id,
                "stage_process_heartbeat",
                {"stage": stage_name, "pid": proc.pid, "elapsed_sec": round(effective_elapsed, 2)},
            )
            last_heartbeat = now

        if timeout_enabled and effective_elapsed >= timeout_seconds and proc.poll() is None:
            raise subprocess.TimeoutExpired(stage_name, timeout_seconds)

        if run_id and proc.poll() is None:
            status = status_for_run(run_id)
            should_pause = bool(pause_requested(run_id) or status == "paused")
            should_cancel = bool(cancel_requested(run_id) or status == "cancelling")

            if should_cancel:
                if paused:
                    try:
                        os.killpg(proc.pid, signal.SIGCONT)
                    except Exception:
                        pass
                os.killpg(proc.pid, signal.SIGTERM)

            if should_pause and not paused:
                os.killpg(proc.pid, signal.SIGSTOP)
                paused = True
                paused_since = time.monotonic()
                resume_event_emitted = False
                if not pause_event_emitted:
                    emit_event(run_id, "stage_process_paused", {"stage": stage_name, "pid": proc.pid, "mode": "owner_process"})
                    pause_event_emitted = True
                time.sleep(0.2)
                continue

            if not should_pause and paused:
                os.killpg(proc.pid, signal.SIGCONT)
                paused = False
                if paused_since is not None:
                    paused_total += time.monotonic() - paused_since
                    paused_since = None
                pause_event_emitted = False
                if not resume_event_emitted:
                    emit_event(run_id, "stage_process_resumed", {"stage": stage_name, "pid": proc.pid, "mode": "owner_process"})
                    resume_event_emitted = True

        if proc.poll() is not None and all(streams_done.values()):
            drain_output()
            _emit_output_batch(
                run_id=run_id,
                stage_name=stage_name,
                pid=proc.pid,
                emit_event=emit_event,
                stdout_pending=stdout_pending,
                stderr_pending=stderr_pending,
                stdout_parts=stdout_parts,
                stderr_parts=stderr_parts,
                started=started,
            )
            for thread in threads:
                thread.join(timeout=0.2)
            return "".join(stdout_parts), "".join(stderr_parts)

        time.sleep(0.2)


def _communicate_stage_process_polling(
    proc: subprocess.Popen,
    *,
    run_id: str | None,
    stage_name: str,
    timeout_seconds: int,
    status_for_run: RunStatusGetter,
    pause_requested: RunFlagGetter,
    cancel_requested: RunFlagGetter,
    emit_event: RunEventEmitter,
) -> tuple[str, str]:
    """Compatibility path for fake processes or runtimes without pipe streams."""

    started = time.monotonic()
    paused_since: float | None = None
    paused_total = 0.0
    paused = False
    pause_event_emitted = False
    resume_event_emitted = False
    timeout_enabled = timeout_seconds > 0

    while True:
        effective_elapsed = time.monotonic() - started - paused_total
        remaining = max(0.1, timeout_seconds - effective_elapsed) if timeout_enabled else 1.0
        try:
            return proc.communicate(timeout=min(1.0, remaining))
        except subprocess.TimeoutExpired:
            if timeout_enabled and effective_elapsed >= timeout_seconds:
                raise
            if not run_id or proc.poll() is not None:
                continue

            status = status_for_run(run_id)
            should_pause = bool(pause_requested(run_id) or status == "paused")
            should_cancel = bool(cancel_requested(run_id) or status == "cancelling")

            if should_cancel:
                if paused:
                    try:
                        os.killpg(proc.pid, signal.SIGCONT)
                    except Exception:
                        pass
                os.killpg(proc.pid, signal.SIGTERM)
                return proc.communicate(timeout=10)

            if should_pause and not paused:
                os.killpg(proc.pid, signal.SIGSTOP)
                paused = True
                paused_since = time.monotonic()
                resume_event_emitted = False
                if not pause_event_emitted:
                    emit_event(run_id, "stage_process_paused", {"stage": stage_name, "pid": proc.pid, "mode": "owner_process"})
                    pause_event_emitted = True
                continue

            if not should_pause and paused:
                os.killpg(proc.pid, signal.SIGCONT)
                paused = False
                if paused_since is not None:
                    paused_total += time.monotonic() - paused_since
                    paused_since = None
                pause_event_emitted = False
                if not resume_event_emitted:
                    emit_event(run_id, "stage_process_resumed", {"stage": stage_name, "pid": proc.pid, "mode": "owner_process"})
                    resume_event_emitted = True


def communicate_stage_process(
    proc: subprocess.Popen,
    *,
    run_id: str | None,
    stage_name: str,
    timeout_seconds: int,
    status_for_run: RunStatusGetter,
    pause_requested: RunFlagGetter,
    cancel_requested: RunFlagGetter,
    emit_event: RunEventEmitter,
) -> tuple[str, str]:
    """Wait for a stage process while honoring DB-backed pause/resume/cancel.

    The process owner is the only runtime that can reliably signal its own
    subprocess group. API-thread and worker-queue execution both use this same
    loop, with router-specific state passed in as callbacks.
    """

    if getattr(proc, "stdout", None) is not None and getattr(proc, "stderr", None) is not None:
        return _communicate_stage_process_streaming(
            proc,
            run_id=run_id,
            stage_name=stage_name,
            timeout_seconds=timeout_seconds,
            status_for_run=status_for_run,
            pause_requested=pause_requested,
            cancel_requested=cancel_requested,
            emit_event=emit_event,
        )

    return _communicate_stage_process_polling(
        proc,
        run_id=run_id,
        stage_name=stage_name,
        timeout_seconds=timeout_seconds,
        status_for_run=status_for_run,
        pause_requested=pause_requested,
        cancel_requested=cancel_requested,
        emit_event=emit_event,
    )
