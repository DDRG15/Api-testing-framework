from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.control import connections
from src.control.bridge import ConsoleBridge
from src.control.connections import ConnectionFailure, Connections, execute, validate_url
from src.control.http_server import ConsoleServer
from src.control.service import ControlService

KEY = "synthetic-session-secret"
PRIVATE = "synthetic-private-response"


@pytest.fixture
def target():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            received.append((self.path, dict(self.headers)))
            status = 302 if self.path == "/redirect" else 401 if self.path == "/unauthorized" else 200
            body = json.dumps({"status": "broken" if self.path == "/bad" else "ok",
                               "private": PRIVATE, "echo": KEY, "data": []}).encode()
            if self.path == "/pathological":
                body = json.dumps({"value": "a" * 100 + "!"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html" if self.path == "/html" else "application/json")
            self.send_header("Location", "/must-not-follow")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def profile(url, **changes):
    return {"url": url, "auth_mode": "bearer", "secret": KEY, "header_name": "",
            "expected_status": 200, "schema": {"type": "object", "required": ["status"],
            "properties": {"status": {"const": "ok"}}}, **changes}


@pytest.mark.parametrize("url", ["http://example.com/", "https://example.com/?key=value",
    "https://example.com/#fragment", "https://169.254.169.254/", "https://0.0.0.0/",
    "https://example.com:0/", "https://example.com/\r\nheader", "file:///path"])
def test_target_url_rejects_unsafe_forms(url):
    with pytest.raises(ValueError, match="invalid_target_url"):
        validate_url(url)


def test_target_validation_and_secret_free_status(target):
    url, _ = target
    vault = Connections()
    status = vault.configure("target", profile(url + "/ok"))
    assert KEY not in json.dumps(status) and url not in json.dumps(status)
    assert KEY not in repr(vault.snapshot("target"))
    execute(vault.snapshot("target"))
    vault.disconnect("all")
    assert not any(item["configured"] for item in vault.status()["connections"])
    with pytest.raises(ValueError, match="connection_not_configured"):
        vault.snapshot("target")


@pytest.mark.parametrize("path,error", [("/bad", "response_contract_failed"),
    ("/redirect", "redirect_refused"), ("/unauthorized", "authentication_failed"),
    ("/html", "json_response_required")])
def test_remote_failures_use_fixed_codes_without_reflection(target, path, error):
    url, received = target
    vault = Connections()
    vault.configure("target", profile(url + path))
    with pytest.raises(ConnectionFailure, match=error) as failure:
        execute(vault.snapshot("target"))
    assert KEY not in str(failure.value) and PRIVATE not in str(failure.value)
    assert len(received) == 1


@pytest.mark.parametrize("change", [
    {"schema": {"$ref": "https://example.com/remote.json"}},
    {"header_name": "Host", "auth_mode": "header"},
    {"secret": "bad\r\nvalue"}, {"expected_status": True},
])
def test_invalid_configuration_is_rejected_without_changing_previous_profile(target, change):
    url, _ = target
    vault = Connections()
    vault.configure("target", profile(url))
    with pytest.raises(ValueError):
        vault.configure("target", profile(url, **change))
    assert vault.snapshot("target").secret == KEY


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_provider_catalog_uses_separate_key_and_fixed_endpoint(target, monkeypatch, kind):
    url, received = target
    monkeypatch.setitem(connections.PROVIDERS, kind, url + "/models")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    vault = Connections()
    vault.configure("target", profile(url, secret="another-synthetic-target-secret"))
    vault.configure(kind, {"secret": KEY})
    execute(vault.snapshot(kind))
    assert received[0][1]["Authorization"] == "Bearer " + KEY
    assert received[0][0] == "/models"
    if kind == "anthropic":
        assert received[0][1]["anthropic-version"] == "2026-10-21"
    with pytest.raises(ValueError):
        vault.configure(kind, {"secret": KEY, "url": url})


def test_service_records_counts_without_credentials_url_or_remote_body(tmp_path, target):
    url, _ = target
    service = ControlService(Path(__file__).resolve().parents[2], tmp_path / "runs", sys.executable)
    try:
        service.connections.configure("target", profile(url + "/ok"))
        record = service.start_run("target")
        deadline = time.monotonic() + 5
        while record["status"] == "running" and time.monotonic() < deadline:
            time.sleep(.01)
            record = service.get_run(record["run_id"])
        assert record["status"] == "passed"
        assert record["summary"]["passed"] == 1
        for path in (tmp_path / "runs").rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                assert all(term.encode() not in data for term in (KEY, PRIVATE, url))
        service.connections.disconnect("target")
        with pytest.raises(ValueError, match="connection_not_configured"):
            service.start_run("target")
    finally:
        service.close()


def test_pathological_schema_is_terminated_and_execution_lock_is_released(tmp_path, target):
    url, _ = target
    service = ControlService(Path(__file__).resolve().parents[2], tmp_path / "data", sys.executable,
                             timeout_seconds=1)
    try:
        schema = {"type": "object", "properties": {"value": {"type": "string", "pattern": "(a+)+$"}}}
        service.connections.configure("target", profile(url + "/pathological", schema=schema))
        started = time.monotonic()
        record = service.start_run("target")
        while record["status"] == "running" and time.monotonic() - started < 4:
            time.sleep(.02)
            record = service.get_run(record["run_id"])
        assert record["status"] == "failed" and record["error_code"] == "execution_timeout"
        assert time.monotonic() - started < 4
        # A second run proves the worker and SQLite transaction did not stay stuck.
        service.connections.configure("openai", {"secret": KEY})
        service.connections.disconnect("all")
        assert not any(item["configured"] for item in service.connection_status()["connections"])
        service.connections.configure("target", profile(url + "/ok"))
        service.timeout_seconds = 5
        record = service.start_run("target")
        deadline = time.monotonic() + 6
        while record["status"] == "running" and time.monotonic() < deadline:
            time.sleep(.02)
            record = service.get_run(record["run_id"])
        assert record["status"] == "passed"
    finally:
        service.close()
    assert not any(item["configured"] for item in service.connection_status()["connections"])


def test_console_bridge_shares_session_and_does_not_stop_console(tmp_path, target, monkeypatch):
    url, _ = target
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    state = tmp_path / "sandbox/desktop/state.json"
    state.parent.mkdir(parents=True)
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>API Testing Framework</h1>")
    service = ControlService(Path(__file__).resolve().parents[2], tmp_path / "data", sys.executable)
    service.connections.configure("target", profile(url))
    try:
        with ConsoleServer(service, assets) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                state.write_text(json.dumps({"url": server.launch_url}))
                bridge = ConsoleBridge(state)
                assert bridge.connection_status()["connections"][0]["configured"]
                assert KEY not in json.dumps(bridge.connection_status())
                assert bridge.start_run("target")["operation"] == "target"
                with pytest.raises(ValueError, match="invalid_run_id"):
                    bridge.get_run("../../private")
                bridge.close()
                assert bridge.capabilities()["name"] == "API Testing Framework"
                state.write_text(json.dumps({"url": "https://example.com/#token=invalid"}))
                with pytest.raises(RuntimeError, match="console_unavailable"):
                    bridge.capabilities()
            finally:
                server.shutdown()
                thread.join(timeout=2)
    finally:
        service.close()
