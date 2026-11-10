from __future__ import annotations

from datetime import timedelta

import pytest
from requests import Response
from requests.exceptions import ReadTimeout

from config.settings import settings
from src.client.base_client import ApiClient, RetriesExhaustedError


class SequenceSession:
    def __init__(self, *outcomes: int | Exception) -> None:
        self.outcomes = iter(outcomes)
        self.headers: dict[str, str] = {}
        self.calls: list[dict] = []

    def request(self, **kwargs) -> Response:
        self.calls.append(kwargs)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        response = Response()
        response.status_code = outcome
        response._content = b'{}'
        response.elapsed = timedelta(milliseconds=1)
        response.headers = {"Retry-After": "0"}
        return response

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(settings, "retry_base_delay_seconds", 0.001)
    monkeypatch.setattr(settings, "retry_max_delay_seconds", 0.005)


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_get_retries_only_transient_statuses(status):
    with ApiClient() as client:
        session = SequenceSession(status, 200)
        client._session = session
        assert client.get("/probe").status_code == 200
        assert len(session.calls) == 2
        assert session.calls[0]["headers"]["X-Correlation-ID"] == session.calls[1]["headers"]["X-Correlation-ID"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
def test_logic_errors_are_never_retried(status):
    with ApiClient() as client:
        session = SequenceSession(status, 200)
        client._session = session
        assert client.get("/probe").status_code == status
        assert len(session.calls) == 1


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_unsafe_method_is_not_replayed_even_with_key_header(method):
    with ApiClient() as client:
        session = SequenceSession(503, 200)
        client._session = session
        with pytest.raises(RetriesExhaustedError, match="1 permitted attempts"):
            client.request(method, "/charge", headers={"Idempotency-Key": "same"})
        assert len(session.calls) == 1


def test_post_timeout_has_unknown_effect_and_is_not_replayed():
    with ApiClient() as client:
        session = SequenceSession(ReadTimeout("response lost"), 200)
        client._session = session
        with pytest.raises(ReadTimeout):
            client.post("/charge", json={"amount": 100})
        assert len(session.calls) == 1


def test_declared_replay_safe_post_reuses_payload_and_identity():
    with ApiClient() as client:
        session = SequenceSession(ReadTimeout("response lost"), 200)
        client._session = session
        assert client.post("/charge", json={"amount": 100},
                           headers={"Idempotency-Key": "same"}, retry_safe=True).status_code == 200
        assert len(session.calls) == 2
        assert session.calls[0]["json"] == session.calls[1]["json"]
        assert session.calls[0]["headers"] == session.calls[1]["headers"]
