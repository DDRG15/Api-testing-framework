"""Process-local connection settings; no credentials or payloads are persisted."""
from __future__ import annotations

import copy
import http.client
import ipaddress
import json
import multiprocessing
import re
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

KINDS = ("target", "openai", "anthropic")
PROVIDERS = {"openai": "https://api.openai.com/v1/models",
             "anthropic": "https://api.anthropic.com/v1/models"}
MAX_RESPONSE = 1_048_576


class ConnectionFailure(ValueError):
    """A fixed error code that contains no remote content."""


@dataclass(frozen=True)
class Profile:
    kind: str
    url: str = field(repr=False)
    secret: str = field(repr=False)
    auth_mode: str
    header_name: str
    expected_status: int
    schema: dict[str, Any] = field(repr=False)


def validate_url(url: Any) -> str:
    if not isinstance(url, str) or not 1 <= len(url) <= 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in url):
        raise ValueError("invalid_target_url")
    try:
        parts = urlsplit(url)
        if (not parts.hostname or parts.username or parts.password or parts.fragment or parts.query
                or parts.port == 0 or "\\" in url):
            raise ValueError
        try:
            address = ipaddress.ip_address(parts.hostname)
        except ValueError:
            address = None
        loopback = parts.hostname == "localhost" or bool(address and address.is_loopback)
        if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
            raise ValueError
        if address and (address.is_link_local or address.is_multicast or address.is_unspecified):
            raise ValueError
        if parts.hostname in {"metadata.google.internal", "instance-data.ec2.internal"}:
            raise ValueError
    except ValueError:
        raise ValueError("invalid_target_url") from None
    return url


def validate_schema(schema: Any) -> dict[str, Any]:
    # Import only in the core environment; the standalone MCP SDK can list status
    # without installing the core's different dependency baseline.
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    if not isinstance(schema, dict) or not schema or len(json.dumps(schema)) > 16_384:
        raise ValueError("invalid_contract_schema")
    budget = 512

    def walk(value: Any, depth: int = 0) -> None:
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 16:
            raise ValueError("invalid_contract_schema")
        if isinstance(value, dict):
            if {"$ref", "$dynamicRef", "$recursiveRef"}.intersection(value):
                raise ValueError("schema_references_not_supported")
            for item in value.values():
                walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)

    walk(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        raise ValueError("invalid_contract_schema") from None
    return copy.deepcopy(schema)


def _secret(value: Any, required: bool) -> str:
    if (not isinstance(value, str) or len(value) > 4096
            or any(ord(c) < 33 or ord(c) > 126 for c in value) or (required and not value)):
        raise ValueError("invalid_credential")
    return value


class Connections:
    """One session per service process, shared with editor hosts through the bridge."""

    def __init__(self) -> None:
        self._profiles: dict[str, Profile] = {}
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"storage": "process_memory", "connections": [
                {"kind": kind, "configured": kind in self._profiles,
                 "has_credential": bool(self._profiles.get(kind) and self._profiles[kind].secret),
                 "auth_mode": self._profiles[kind].auth_mode if kind in self._profiles else None}
                for kind in KINDS]}

    def configure(self, kind: str, value: Any) -> dict[str, Any]:
        if kind not in KINDS or not isinstance(value, dict):
            raise ValueError("invalid_connection")
        if kind == "target":
            required = {"url", "auth_mode", "header_name", "secret", "expected_status", "schema"}
            if set(value) != required or value["auth_mode"] not in {"none", "bearer", "header"}:
                raise ValueError("invalid_connection")
            auth = value["auth_mode"]
            header = value["header_name"]
            if not isinstance(header, str) or (auth == "header" and not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", header)):
                raise ValueError("invalid_auth_header")
            if auth == "header" and header.lower() in {
                "host", "origin", "connection", "content-length", "transfer-encoding", "cookie",
                "proxy-authorization", "accept-encoding", "user-agent", "accept", "content-type",
            }:
                raise ValueError("invalid_auth_header")
            code = value["expected_status"]
            if type(code) is not int or not 200 <= code <= 299:
                raise ValueError("invalid_expected_status")
            profile = Profile(kind, validate_url(value["url"]), _secret(value["secret"], auth != "none") if auth != "none" else "",
                              auth, header if auth == "header" else "", code, validate_schema(value["schema"]))
        else:
            if set(value) != {"secret"}:
                raise ValueError("invalid_connection")
            profile = Profile(kind, PROVIDERS[kind], _secret(value["secret"], True), "bearer", "", 200, {})
        with self._lock:
            self._profiles[kind] = profile
        return self.status()

    def snapshot(self, kind: str) -> Profile:
        with self._lock:
            if kind not in KINDS or kind not in self._profiles:
                raise ValueError("connection_not_configured")
            return copy.deepcopy(self._profiles[kind])

    def disconnect(self, kind: str) -> dict[str, Any]:
        if kind not in KINDS and kind != "all":
            raise ValueError("invalid_connection")
        with self._lock:
            if kind == "all":
                self._profiles.clear()
            else:
                self._profiles.pop(kind, None)
        return self.status()


def _request(profile: Profile) -> tuple[int, Any]:
    """One GET, no retries, redirects, proxy environment, cookies or payload logs."""
    parts = urlsplit(profile.url)
    headers = {"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "api-testing-framework/1"}
    if profile.auth_mode == "bearer":
        headers["Authorization"] = "Bearer " + profile.secret
    elif profile.auth_mode == "header":
        headers[profile.header_name] = profile.secret
    if profile.kind == "anthropic":
        headers["anthropic-version"] = "2026-10-21"
    connection: http.client.HTTPConnection
    if parts.scheme == "https":
        connection = http.client.HTTPSConnection(parts.hostname or "", parts.port, timeout=5,
                                                context=ssl.create_default_context())
    else:
        connection = http.client.HTTPConnection(parts.hostname or "", parts.port, timeout=5)
    try:
        started = time.monotonic()
        connection.request("GET", parts.path or "/", headers=headers)
        response = connection.getresponse()
        if 300 <= response.status <= 399:
            raise ConnectionFailure("redirect_refused")
        if response.status in {401, 403}:
            raise ConnectionFailure("authentication_failed")
        if response.status != profile.expected_status:
            raise ConnectionFailure("unexpected_http_status")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ConnectionFailure("unsupported_response_encoding")
        content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json" and not content_type.endswith("+json"):
            raise ConnectionFailure("json_response_required")
        body = bytearray()
        while True:
            remaining = 8 - (time.monotonic() - started)
            if remaining <= 0:
                raise ConnectionFailure("connection_timeout")
            if connection.sock is not None:
                connection.sock.settimeout(min(5, remaining))
            part = response.read1(min(65536, MAX_RESPONSE + 1 - len(body)))
            body.extend(part)
            if len(body) > MAX_RESPONSE:
                raise ConnectionFailure("response_too_large")
            if not part:
                break
        return response.status, json.loads(body.decode("utf-8"))
    except ConnectionFailure:
        raise
    except (TimeoutError, OSError, http.client.HTTPException, ValueError, RecursionError):
        raise ConnectionFailure("connection_request_failed") from None
    finally:
        connection.close()


def execute(profile: Profile) -> None:
    """Validate remote content without returning the response or any credentials."""
    _, body = _request(profile)
    if profile.kind == "target":
        from jsonschema import Draft202012Validator
        try:
            valid = Draft202012Validator(profile.schema).is_valid(body)
        except (ValueError, RecursionError):
            valid = False
        if not valid:
            raise ConnectionFailure("response_contract_failed")
    elif not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ConnectionFailure("invalid_provider_catalog")


def _worker(profile: Profile, output: Any) -> None:
    """The profile crosses a RAM pipe, never argv, environment or a disk file."""
    try:
        execute(profile)
        output.send(None)
    except ConnectionFailure as exc:
        output.send(str(exc))
    except Exception:
        # Validation libraries must not print remote content or a user schema.
        output.send("connection_request_failed")
    finally:
        output.close()


def execute_isolated(profile: Profile, stop: threading.Event, timeout: float = 10) -> None:
    """Bound DNS, socket I/O and schema CPU time from an independent parent."""
    context = multiprocessing.get_context("spawn")
    received, sent = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(profile, sent), daemon=True)
    started = time.monotonic()
    try:
        process.start()
        sent.close()
        while process.is_alive():
            if stop.wait(.025):
                raise ConnectionFailure("service_shutdown")
            if time.monotonic() - started >= timeout:
                raise ConnectionFailure("execution_timeout")
        process.join()
        if not received.poll() or process.exitcode:
            raise ConnectionFailure("connection_request_failed")
        result = received.recv()
        if result is not None:
            allowed = {"redirect_refused", "authentication_failed", "unexpected_http_status",
                       "unsupported_response_encoding", "json_response_required", "connection_timeout",
                       "response_too_large", "connection_request_failed", "response_contract_failed",
                       "invalid_provider_catalog"}
            raise ConnectionFailure(result if result in allowed else "connection_request_failed")
    except EOFError:
        raise ConnectionFailure("connection_request_failed") from None
    finally:
        sent.close()
        received.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
            process.close()
