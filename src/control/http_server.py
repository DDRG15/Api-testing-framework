"""Loopback-only HTTP adapter for a built React console and bounded JSON API."""
from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from src.control.service import BusyError, ControlService


class ConsoleServer(ThreadingHTTPServer):
    """Serve only explicit public assets; runtime evidence never becomes a file URL."""

    daemon_threads = True

    def __init__(self, service: ControlService, assets: Path, port: int = 0) -> None:
        self.service = service
        self.assets = assets.resolve(strict=True)
        if not self.assets.is_dir() or not (self.assets / "index.html").is_file():
            raise ValueError("console_build_required")
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), ConsoleHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    @property
    def launch_url(self) -> str:
        return f"{self.origin}/#token={self.token}"


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer

    def log_message(self, format: str, *args: Any) -> None:
        # Paths/query strings and authentication material do not enter logs.
        pass

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5)

    def _respond(self, status: int, data: bytes, mime: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; object-src 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, data: dict[str, Any]) -> None:
        self._respond(status, json.dumps(data).encode(), "application/json; charset=utf-8")

    def _error(self, status: int, code: str) -> None:
        self._json(status, {"error": code})

    def _host_allowed(self) -> bool:
        hosts = self.headers.get_all("Host", [])
        if hosts != [f"127.0.0.1:{self.server.server_port}"]:
            self._error(403, "invalid_host")
            return False
        return True

    def _authenticated(self, *, write: bool = False) -> bool:
        origins = self.headers.get_all("Origin", [])
        if (write and origins != [self.server.origin]) or (origins and origins != [self.server.origin]):
            self._error(403, "invalid_origin")
            return False
        tokens = self.headers.get_all("X-Console-Token", [])
        if len(tokens) != 1 or not hmac.compare_digest(tokens[0].encode("utf-8"), self.server.token.encode("ascii")):
            self._error(401, "authentication_required")
            return False
        return True

    def do_GET(self) -> None:
        if not self._host_allowed():
            return
        url = urlsplit(self.path)
        if url.query or url.fragment:
            self._error(404, "not_found")
            return
        path = unquote(url.path)
        if path.startswith("/api/"):
            if not self._authenticated():
                return
            try:
                if path == "/api/capabilities":
                    self._json(200, self.server.service.capabilities())
                elif path == "/api/connections":
                    self._json(200, self.server.service.connections.status())
                elif path == "/api/runs":
                    self._json(200, {"runs": self.server.service.list_runs()})
                elif path.startswith("/api/runs/"):
                    self._json(200, self.server.service.get_run(path.removeprefix("/api/runs/")))
                else:
                    self._error(404, "not_found")
            except (KeyError, ValueError):
                self._error(404, "unknown_run")
            except (OSError, RuntimeError):
                self._error(503, "operation_unavailable")
            return
        if path == "/architecture":
            target = self.server.service.project_root / "docs/architecture.html"
            if target.is_symlink() or not target.resolve().is_relative_to(self.server.service.project_root):
                self._error(404, "not_found")
                return
        else:
            if path in {"/", "/index.html"}:
                target = self.server.assets / "index.html"
            elif path.startswith("/assets/") and Path(path).suffix in {".js", ".css", ".svg", ".png", ".ico", ".woff2"}:
                target = self.server.assets / path.lstrip("/")
            else:
                self._error(404, "not_found")
                return
            permitted_root = self.server.assets / "assets" if path.startswith("/assets/") else self.server.assets
            if not target.resolve().is_relative_to(permitted_root):
                self._error(404, "not_found")
                return
        try:
            if not target.is_file() or target.stat().st_size > 8_000_000:
                self._error(404, "not_found")
                return
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._respond(200, target.read_bytes(), mime)
        except OSError:
            self._error(404, "not_found")

    def do_POST(self) -> None:
        if not self._host_allowed() or not self._authenticated(write=True):
            return
        routes = {"/api/runs", "/api/connections/target", "/api/connections/openai",
                  "/api/connections/anthropic", "/api/connections/disconnect"}
        if self.path not in routes:
            self._error(404, "not_found")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
            self._error(400, "invalid_body")
            return
        length = int(lengths[0])
        if length > (24_576 if self.path.startswith("/api/connections/") else 4096):
            self._error(413, "body_too_large")
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self._error(415, "json_required")
            return
        try:
            data = json.loads(self.rfile.read(length))
            if self.path.startswith("/api/connections/"):
                if not isinstance(data, dict):
                    raise ValueError("invalid_connection")
                kind = self.path.rsplit("/", 1)[1]
                if kind == "disconnect":
                    if set(data) != {"kind"} or not isinstance(data["kind"], str):
                        raise ValueError("invalid_connection")
                    result = self.server.service.connections.disconnect(data["kind"])
                else:
                    result = self.server.service.connections.configure(kind, data)
                self._json(200, result)
                return
            if not isinstance(data, dict) or set(data) != {"operation"} or not isinstance(data["operation"], str):
                raise ValueError("invalid_operation")
            self._json(202, self.server.service.start_run(data["operation"]))
        except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
            allowed = {"invalid_connection", "invalid_target_url", "invalid_auth_header", "invalid_expected_status",
                       "invalid_contract_schema", "schema_references_not_supported", "invalid_credential",
                       "connection_not_configured"}
            code = str(exc)
            self._error(400, code if code in allowed else "invalid_operation")
        except BusyError:
            self._error(409, "execution_in_progress")
        except (OSError, RuntimeError):
            self._error(503, "operation_unavailable")

    def do_OPTIONS(self) -> None:
        self._error(405, "method_not_allowed")
