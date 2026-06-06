"""
tests/unit/test_retry_and_breaker.py
=====================================
Unit tests for the retry-exhaustion and circuit-breaker behaviour of ApiClient.

No live API. A fake session returns a fixed status code so the resilience
paths can be exercised deterministically and fast (backoff is patched down).

These lock two findings:
  - reraise=True meant the caller received the internal _TransientHttpError on
    exhaustion instead of a public, CID-bearing error.
  - 5xx responses were raised outside the breaker context, so the breaker never
    tripped on a degraded upstream.
"""
from __future__ import annotations

import datetime

import pytest

from config.settings import settings
from src.client import base_client
from src.client.base_client import ApiClient
from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.elapsed = datetime.timedelta(milliseconds=5)
        self.ok = 200 <= status_code < 400

    @property
    def text(self) -> str:
        return f"fake body {self.status_code}"

    def json(self) -> dict:
        return {}


class _FakeSession:
    """Minimal stand-in for requests.Session that always returns one status."""

    def __init__(self, status_code: int) -> None:
        self._status = status_code
        self.headers: dict[str, str] = {}
        self.call_count = 0

    def request(self, **kwargs: object) -> _FakeResponse:
        self.call_count += 1
        return _FakeResponse(self._status)

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink backoff so exhaustion tests do not actually sleep for seconds."""
    monkeypatch.setattr(settings, "retry_base_delay_seconds", 0.001)
    monkeypatch.setattr(settings, "retry_max_delay_seconds", 0.005)


def test_sustained_503_raises_public_error_with_cid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exhausted retries raise RetriesExhaustedError (not the internal sentinel), CID attached."""
    monkeypatch.setattr(settings, "retry_max_attempts", 3)
    # High threshold so the breaker does not trip during this single call.
    client = ApiClient(circuit_breaker=CircuitBreaker(name="t-exhaust", failure_threshold=100))
    client._session = _FakeSession(503)  # type: ignore[assignment]

    with pytest.raises(base_client.RetriesExhaustedError) as excinfo:
        client.get("/booking")

    assert "correlation_id=" in str(excinfo.value)
    assert client._session.call_count == 3  # type: ignore[attr-defined]


def test_internal_transient_error_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    """_TransientHttpError must never propagate past the public client boundary."""
    monkeypatch.setattr(settings, "retry_max_attempts", 2)
    client = ApiClient(circuit_breaker=CircuitBreaker(name="t-leak", failure_threshold=100))
    client._session = _FakeSession(502)  # type: ignore[assignment]

    with pytest.raises(base_client.RetriesExhaustedError):
        client.get("/booking")
    # And specifically NOT the internal type:
    with pytest.raises(base_client.RetriesExhaustedError):
        try:
            client.get("/booking")
        except base_client._TransientHttpError:  # pragma: no cover - must not happen
            pytest.fail("_TransientHttpError leaked past the public client")


def test_sustained_5xx_trips_circuit_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    """A degraded upstream (repeated 503) must open the breaker, then fail fast."""
    monkeypatch.setattr(settings, "retry_max_attempts", 1)  # one attempt = one failure per call
    cb = CircuitBreaker(name="t-trip", failure_threshold=3, recovery_timeout=60)
    client = ApiClient(circuit_breaker=cb)
    client._session = _FakeSession(503)  # type: ignore[assignment]

    for _ in range(3):
        with pytest.raises(base_client.RetriesExhaustedError):
            client.get("/booking")

    # Breaker is now OPEN — the next call fails fast without touching the network.
    with pytest.raises(CircuitBreakerOpenError):
        client.get("/booking")
    assert client._session.call_count == 3  # type: ignore[attr-defined]
