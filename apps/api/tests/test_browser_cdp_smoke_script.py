import importlib.util
import socket
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/browser_cdp_smoke.py"


def load_script():
    spec = importlib.util.spec_from_file_location("browser_cdp_smoke", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_routes_cover_core_frontend_pages():
    module = load_script()

    assert module.DEFAULT_ROUTES == [
        "/",
        "/runs",
        "/data-import",
        "/taxonomy",
        "/coverage",
        "/references",
        "/settings",
    ]


def test_find_browser_reports_missing_binary(monkeypatch):
    module = load_script()

    monkeypatch.setattr(module.shutil, "which", lambda _candidate: None)
    monkeypatch.setattr(module.Path, "exists", lambda _path: False)
    monkeypatch.delenv("BROWSER", raising=False)

    with pytest.raises(module.CDPError, match="Chrome/Chromium not found"):
        module.find_browser()


def test_new_page_ws_uses_put_before_get(monkeypatch):
    module = load_script()
    calls = []

    def fake_json_request(url, timeout=10.0, method="GET"):
        calls.append((url, timeout, method))
        return {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1"}

    monkeypatch.setattr(module, "json_request", fake_json_request)

    result = module.new_page_ws("ws://127.0.0.1:9222/devtools/browser/session", "about:blank")

    assert result == "ws://127.0.0.1:9222/devtools/page/1"
    assert calls == [("http://127.0.0.1:9222/json/new?about:blank", 10.0, "PUT")]


def test_smoke_route_ignores_network_errors_by_default():
    module = load_script()

    class FakeCDP:
        def __init__(self):
            self.messages = [
                {
                    "method": "Log.entryAdded",
                    "params": {
                        "entry": {
                            "level": "error",
                            "source": "network",
                            "text": "Failed to load resource: 404",
                        }
                    },
                },
                {"method": "Page.loadEventFired", "params": {}},
            ]

        def call(self, _method, _params=None):
            return {}

        def recv(self, _timeout=None):
            if not self.messages:
                raise socket.timeout()
            return self.messages.pop(0)

    assert module.smoke_route(FakeCDP(), "http://example.test", 1.0, 0.1) == []


def test_smoke_route_fails_on_console_error():
    module = load_script()

    class FakeCDP:
        def __init__(self):
            self.messages = [
                {
                    "method": "Log.entryAdded",
                    "params": {
                        "entry": {
                            "level": "error",
                            "source": "console-api",
                            "text": "frontend exploded",
                        }
                    },
                },
                {"method": "Page.loadEventFired", "params": {}},
            ]

        def call(self, _method, _params=None):
            return {}

        def recv(self, _timeout=None):
            if not self.messages:
                raise socket.timeout()
            return self.messages.pop(0)

    assert module.smoke_route(FakeCDP(), "http://example.test", 1.0, 0.1) == ["frontend exploded"]
