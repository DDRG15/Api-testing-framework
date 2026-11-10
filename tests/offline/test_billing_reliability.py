"""Acceptance checks for a synthetic billing API, over actual loopback HTTP.

These do not verify a real Stripe account, PostgreSQL, or the separate billing
application. Every row is synthetic and every server is owned by its test.
"""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import ValidationError

from config.settings import settings
from src.client.base_client import ApiClient
from src.client.billing_client import BillingClient, BillingEvent
from src.utils.db_oracle import ReadOnlyOracle
from tests.fixtures.billing_server import LAB_SECRET, BillingLab


@pytest.fixture(autouse=True)
def fast_billing_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "retry_base_delay_seconds", 0.001)
    monkeypatch.setattr(settings, "retry_max_delay_seconds", 0.005)
    monkeypatch.setattr(settings, "retry_max_attempts", 3)
    monkeypatch.setattr(settings, "slo_response_time_ms", 5000)


@contextmanager
def billing_client(lab: BillingLab, *, secret: str = LAB_SECRET):
    client = ApiClient(base_url=lab.url)
    try:
        yield BillingClient(client, secret)
    finally:
        client.close()


def event(**changes: object) -> BillingEvent:
    return BillingEvent.model_validate({"event_id": "evt_1", "org_id": "org_1", "amount": 1250, **changes})


def test_duplicate_delivery_has_one_effect(tmp_path: Path) -> None:
    with BillingLab(tmp_path) as lab, billing_client(lab) as client:
        assert client.submit(event()).json()["outcome"] == "POSTED"
        assert client.submit(event()).json()["outcome"] == "DLQ_DUPLICATE"
        ReadOnlyOracle(lab.database).assert_ledger_effect("org_1", "evt_1", count=1, amount=1250)


def test_concurrent_duplicates_have_one_effect(tmp_path: Path) -> None:
    with BillingLab(tmp_path) as lab:
        def deliver(_: int) -> str:
            with billing_client(lab) as client:
                return client.submit(event()).json()["outcome"]

        with ThreadPoolExecutor(max_workers=6) as executor:
            outcomes = list(executor.map(deliver, range(6)))
        assert outcomes.count("POSTED") == 1
        assert outcomes.count("DLQ_DUPLICATE") == 5
        ReadOnlyOracle(lab.database).assert_ledger_effect("org_1", "evt_1", count=1, amount=1250)


def test_lost_response_after_commit_retries_without_duplicate(tmp_path: Path) -> None:
    with BillingLab(tmp_path, drop_response_once=True) as lab, billing_client(lab) as client:
        response = client.submit(event())
        assert response.json()["outcome"] == "DLQ_DUPLICATE"
        assert lab.requests == 2
        ReadOnlyOracle(lab.database).assert_ledger_effect("org_1", "evt_1", count=1, amount=1250)


def test_same_identity_changed_amount_is_conflict(tmp_path: Path) -> None:
    with BillingLab(tmp_path) as lab, billing_client(lab) as client:
        client.submit(event())
        assert client.submit(event(amount=1300)).status_code == 409
        assert lab.requests == 2
        ReadOnlyOracle(lab.database).assert_ledger_effect("org_1", "evt_1", count=1, amount=1250)


@pytest.mark.parametrize("timestamp,secret", [(None, "wrong-secret"), (1, LAB_SECRET)])
def test_bad_or_expired_signature_has_no_effect(tmp_path: Path, timestamp: int | None, secret: str) -> None:
    with BillingLab(tmp_path) as lab, billing_client(lab, secret=secret) as client:
        assert client.submit(event(), timestamp=timestamp).status_code == 400
        ReadOnlyOracle(lab.database).assert_ledger_effect("org_1", "evt_1", count=0, amount=0)


def test_identity_is_scoped_to_organization(tmp_path: Path) -> None:
    with BillingLab(tmp_path) as lab, billing_client(lab) as client:
        assert client.submit(event()).json()["outcome"] == "POSTED"
        assert client.submit(event(org_id="org_2")).json()["outcome"] == "POSTED"
        oracle = ReadOnlyOracle(lab.database)
        oracle.assert_ledger_effect("org_1", "evt_1", count=1, amount=1250)
        oracle.assert_ledger_effect("org_2", "evt_1", count=1, amount=1250)


def test_acceptance_oracle_rejects_broken_deduplication(tmp_path: Path) -> None:
    with BillingLab(tmp_path, deduplicate=False) as lab, billing_client(lab) as client:
        client.submit(event())
        client.submit(event())
        with pytest.raises(AssertionError, match="Persisted ledger effect"):
            ReadOnlyOracle(lab.database).assert_ledger_effect("org_1", "evt_1", count=1, amount=1250)


def test_200_with_wrong_persisted_amount_is_detected(tmp_path: Path) -> None:
    with BillingLab(tmp_path, amount_offset=1) as lab, billing_client(lab) as client:
        assert client.submit(event()).status_code == 200
        with pytest.raises(AssertionError, match="Persisted ledger effect"):
            ReadOnlyOracle(lab.database).assert_ledger_effect("org_1", "evt_1", count=1, amount=1250)


def test_oracle_rejects_write_even_in_approved_query_mapping(tmp_path: Path) -> None:
    with BillingLab(tmp_path) as lab:
        oracle = ReadOnlyOracle(lab.database, queries={"bad": "DELETE FROM ledger"})
        with pytest.raises(sqlite3.DatabaseError):
            oracle.query("bad")
        assert ReadOnlyOracle(lab.database).query("ledger_effect", ("org_1", "evt_1")) == [(0, 0)]


def test_oracle_uses_bound_parameters_and_limits_rows(tmp_path: Path) -> None:
    with BillingLab(tmp_path) as lab, billing_client(lab) as client:
        client.submit(event())
        client.submit(event(event_id="evt_2"))
        oracle = ReadOnlyOracle(lab.database)
        assert oracle.query("ledger_effect", ("org_1' OR 1=1 --", "evt_1")) == [(0, 0)]
        limited = ReadOnlyOracle(lab.database, queries={"rows": "SELECT amount FROM ledger"}, max_rows=1)
        with pytest.raises(ValueError, match="max_rows"):
            limited.query("rows")


@pytest.mark.parametrize("amount", ["1250", True, 12.5, 0])
def test_event_rejects_invalid_amount_types(amount: object) -> None:
    with pytest.raises(ValidationError):
        event(amount=amount)
