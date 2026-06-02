#!/usr/bin/env python3
"""Browser/CDP smoke test for WGS Cockpit frontend routes.

The existing runtime smoke verifies HTTP responses. This script opens real
pages in headless Chrome/Chromium through the DevTools Protocol and fails on
uncaught JavaScript exceptions, browser crashes, or console errors.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_ROUTES = [
    "/",
    "/runs",
    "/data-import",
    "/taxonomy",
    "/coverage",
    "/references",
    "/settings",
]


class CDPError(RuntimeError):
    pass


class CDPWebSocket:
    def __init__(self, ws_url: str, timeout: float = 10.0):
        parsed = urllib.parse.urlparse(ws_url)
        if parsed.scheme != "ws":
            raise CDPError(f"unsupported websocket scheme: {parsed.scheme}")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        self.timeout = timeout
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._next_id = 1
        self._handshake()

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise CDPError(f"websocket handshake failed: {response[:200]!r}")
        accept_expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        )
        if accept_expected not in response:
            raise CDPError("websocket accept header mismatch")

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def send(self, method: str, params: dict[str, Any] | None = None) -> int:
        msg_id = self._next_id
        self._next_id += 1
        self._send_json({"id": msg_id, "method": method, "params": params or {}})
        return msg_id

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        msg_id = self.send(method, params)
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            msg = self.recv(deadline - time.monotonic())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise CDPError(f"{method} failed: {msg['error']}")
                return msg.get("result", {})
        raise CDPError(f"{method} timed out")

    def recv(self, timeout: float | None = None) -> dict[str, Any]:
        if timeout is not None:
            self.sock.settimeout(max(0.1, timeout))
        payload = self._recv_frame()
        return json.loads(payload.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = bytearray([0x81])
        length = len(raw)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(raw))
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise CDPError("websocket closed")
            data += chunk
        return data

    def _recv_frame(self) -> bytes:
        while True:
            b1, b2 = self._recv_exact(2)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if masked:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            if opcode == 0x8:
                raise CDPError("websocket closed by browser")
            if opcode == 0x9:
                continue
            if opcode == 0x1:
                return payload


def find_browser(explicit: str | None = None) -> str:
    candidates = [explicit] if explicit else []
    candidates.extend([
        os.getenv("BROWSER"),
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    ])
    for candidate in candidates:
        if not candidate:
            continue
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).exists():
            return candidate
    raise CDPError("Chrome/Chromium not found. Set --browser or BROWSER.")


def wait_for_devtools(proc: subprocess.Popen[str], timeout: float) -> str:
    deadline = time.monotonic() + timeout
    lines: list[str] = []
    assert proc.stderr is not None
    while time.monotonic() < deadline:
        line = proc.stderr.readline()
        if not line:
            if proc.poll() is not None:
                raise CDPError(f"browser exited early: {''.join(lines)[-1000:]}")
            time.sleep(0.05)
            continue
        lines.append(line)
        marker = "DevTools listening on "
        if marker in line:
            return line.split(marker, 1)[1].strip()
    raise CDPError(f"timed out waiting for DevTools endpoint: {''.join(lines)[-1000:]}")


def json_request(url: str, timeout: float = 10.0, method: str = "GET") -> Any:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as res:  # nosec: operator-provided local browser URL
        return json.loads(res.read().decode("utf-8"))


def new_page_ws(browser_ws: str, url: str) -> str:
    parsed = urllib.parse.urlparse(browser_ws)
    base = f"http://{parsed.hostname}:{parsed.port}"
    target_url = f"{base}/json/new?{urllib.parse.quote(url, safe=':/?&=#')}"
    try:
        target = json_request(target_url, method="PUT")
    except urllib.error.HTTPError as exc:
        if exc.code != 405:
            raise
        target = json_request(target_url, method="GET")
    return target["webSocketDebuggerUrl"]


def smoke_route(
    cdp: CDPWebSocket,
    url: str,
    timeout: float,
    settle_seconds: float,
    fail_network_errors: bool = False,
) -> list[str]:
    errors: list[str] = []
    cdp.call("Runtime.enable")
    cdp.call("Log.enable")
    cdp.call("Page.enable")
    cdp.call("Page.navigate", {"url": url})
    deadline = time.monotonic() + timeout
    settle_deadline: float | None = None
    loaded = False
    while time.monotonic() < deadline:
        if settle_deadline is not None and time.monotonic() >= settle_deadline:
            break
        recv_deadline = min(deadline, settle_deadline) if settle_deadline is not None else deadline
        try:
            msg = cdp.recv(recv_deadline - time.monotonic())
        except socket.timeout:
            break
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "Page.loadEventFired":
            loaded = True
            settle_deadline = min(deadline, time.monotonic() + settle_seconds)
            continue
        if method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            text = details.get("text") or details.get("exception", {}).get("description") or "Runtime exception"
            errors.append(str(text))
        if method == "Log.entryAdded":
            entry = params.get("entry", {})
            if entry.get("level") == "error" and (fail_network_errors or entry.get("source") != "network"):
                errors.append(str(entry.get("text") or "console error"))
        if method in {"Inspector.targetCrashed", "Target.targetCrashed"}:
            errors.append("browser target crashed")
    if not loaded:
        errors.append("page load timed out")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Browser/CDP smoke for WGS Cockpit frontend")
    parser.add_argument("--frontend", default="http://localhost:3000", help="Frontend base URL")
    parser.add_argument("--routes", nargs="*", default=DEFAULT_ROUTES, help="Frontend routes to navigate")
    parser.add_argument("--browser", default=None, help="Chrome/Chromium executable")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-route timeout seconds")
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=1.0,
        help="Seconds to keep listening for runtime errors after page load",
    )
    parser.add_argument(
        "--fail-network-errors",
        action="store_true",
        help="Treat browser network errors, such as 404 favicon requests, as failures",
    )
    args = parser.parse_args()

    browser = find_browser(args.browser)
    user_data_dir = tempfile.mkdtemp(prefix="wgs-cdp-smoke-")
    proc: subprocess.Popen[str] | None = None
    failures: list[str] = []
    try:
        proc = subprocess.Popen(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                f"--user-data-dir={user_data_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        browser_ws = wait_for_devtools(proc, args.timeout)
        for route in args.routes:
            url = urllib.parse.urljoin(args.frontend.rstrip("/") + "/", route.lstrip("/"))
            page_ws = new_page_ws(browser_ws, "about:blank")
            cdp = CDPWebSocket(page_ws, timeout=args.timeout)
            try:
                errors = smoke_route(
                    cdp,
                    url,
                    args.timeout,
                    args.settle_seconds,
                    fail_network_errors=args.fail_network_errors,
                )
            finally:
                cdp.close()
            if errors:
                failures.append(f"{route}: {'; '.join(errors[:4])}")
                print(f"[FAIL] {route}: {'; '.join(errors[:4])}")
            else:
                print(f"[OK] {route}: no JS exceptions or console errors")
    except Exception as exc:  # noqa: BLE001 - smoke script reports operator-facing failures
        failures.append(str(exc))
        print(f"[FAIL] browser smoke: {exc}")
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(user_data_dir, ignore_errors=True)

    if failures:
        print(json.dumps({"ok": False, "failures": failures}, indent=2))
        return 1
    print(json.dumps({"ok": True, "routes": args.routes}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
