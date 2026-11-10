"""Loopback billing lab: real HTTP + SQLite, never a production payment service.

Implements a documented synthetic event contract, including deliberate defects
for acceptance tests. It does not run the separate Micro-Billing project.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Any

from pydantic import ValidationError

from src.client.billing_client import BillingEvent

LAB_SECRET = "synthetic-test-signing-secret"


class BillingLab:
    """Owns its HTTP server thread; leaving the context closes all resources."""

    def __init__(
        self,
        directory: Path,
        *,
        deduplicate: bool = True,
        drop_response_once: bool = False,
        amount_offset: int = 0,
    ) -> None:
        self.database = directory / "ledger.sqlite"
        self.deduplicate = deduplicate
        self.drop_response_once = drop_response_once
        self.amount_offset = amount_offset
        self.requests = 0
        self._lock = threading.Lock()
        self._dropped = False
        unique = ", UNIQUE(org_id, event_id)" if deduplicate else ""
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE ledger (org_id TEXT, event_id TEXT, amount INTEGER, "
                f"fingerprint TEXT{unique})"
            )
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = False
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.02})

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def __enter__(self) -> BillingLab:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("Billing lab server did not stop")

    def _record(self, event: BillingEvent) -> tuple[int, dict[str, Any], bool]:
        fingerprint = hashlib.sha256(event.model_dump_json().encode()).hexdigest()
        with self._lock, sqlite3.connect(self.database) as connection:
            self.requests += 1
            old = connection.execute(
                "SELECT fingerprint FROM ledger WHERE org_id = ? AND event_id = ?",
                (event.org_id, event.event_id),
            ).fetchone()
            if self.deduplicate and old:
                if old[0] != fingerprint:
                    return 409, {"error": "idempotency_conflict"}, False
                return 200, {"outcome": "DLQ_DUPLICATE", "transaction_id": event.event_id}, False
            connection.execute(
                "INSERT INTO ledger VALUES (?, ?, ?, ?)",
                (event.org_id, event.event_id, event.amount + self.amount_offset, fingerprint),
            )
            # Commit BEFORE dropping the connection: the client cannot know
            # whether the operation reached the database from its exception.
            connection.commit()
            drop = self.drop_response_once and not self._dropped
            self._dropped |= drop
            return 200, {"outcome": "POSTED", "transaction_id": event.event_id}, drop

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        lab = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                if self.path != "/webhook/stripe":
                    self._send(404, {"error": "not_found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8192:
                        raise ValueError("invalid request length")
                    raw = self.rfile.read(length)
                    signature = dict(
                        part.split("=", 1)
                        for part in self.headers.get("Stripe-Signature", "").split(",")
                    )
                    stamp = int(signature["t"])
                    digest = hmac.new(
                        LAB_SECRET.encode(), str(stamp).encode() + b"." + raw, hashlib.sha256
                    ).hexdigest()
                    if abs(time.time() - stamp) > 300 or not hmac.compare_digest(digest, signature["v1"]):
                        raise ValueError("invalid or expired signature")
                except (ValueError, KeyError):
                    self._send(400, {"error": "invalid_signature"})
                    return
                try:
                    event = BillingEvent.model_validate_json(raw)
                    if self.headers.get("Idempotency-Key") != event.event_id:
                        raise ValueError("event identity mismatch")
                except (ValidationError, ValueError):
                    self._send(422, {"error": "invalid_event"})
                    return
                status, payload, drop = lab._record(event)
                if drop:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    self.close_connection = True
                    return
                self._send(status, payload)

        return Handler
