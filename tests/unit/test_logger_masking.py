"""
tests/unit/test_logger_masking.py
==================================
Unit tests for the structlog redaction processors.

These need no live API — they exercise pure functions. They are the
regression lock for the credential-leak finding: header masking alone left
the POST /auth request body (with the password) unredacted at DEBUG level.
"""
from __future__ import annotations

from src.utils.logger import (
    _MASK,
    _mask_sensitive_body,
    _mask_sensitive_headers,
)


def test_request_body_password_is_redacted() -> None:
    event = {"event": "request_attempt", "request_body": {"username": "admin", "password": "hunter2"}}
    out = _mask_sensitive_body(None, "info", event)  # type: ignore[arg-type]
    assert out["request_body"]["password"] == _MASK
    assert out["request_body"]["username"] == "admin"


def test_response_body_token_is_redacted() -> None:
    event = {"event": "x", "response_body": {"token": "abc123", "reason": "ok"}}
    out = _mask_sensitive_body(None, "info", event)  # type: ignore[arg-type]
    assert out["response_body"]["token"] == _MASK
    assert out["response_body"]["reason"] == "ok"


def test_body_masking_is_case_insensitive() -> None:
    event = {"request_body": {"Password": "x", "API_KEY": "y", "name": "z"}}
    out = _mask_sensitive_body(None, "info", event)  # type: ignore[arg-type]
    assert out["request_body"]["Password"] == _MASK
    assert out["request_body"]["API_KEY"] == _MASK
    assert out["request_body"]["name"] == "z"


def test_non_dict_body_is_left_untouched() -> None:
    event = {"request_body": None, "response_body": "<unreadable>"}
    out = _mask_sensitive_body(None, "info", event)  # type: ignore[arg-type]
    assert out["request_body"] is None
    assert out["response_body"] == "<unreadable>"


def test_sensitive_headers_still_masked() -> None:
    event = {"request_headers": {"Cookie": "token=secret", "Accept": "application/json"}}
    out = _mask_sensitive_headers(None, "info", event)  # type: ignore[arg-type]
    assert out["request_headers"]["Cookie"] == _MASK
    assert out["request_headers"]["Accept"] == "application/json"
