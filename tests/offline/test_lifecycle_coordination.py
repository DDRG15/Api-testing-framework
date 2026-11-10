from __future__ import annotations

from types import SimpleNamespace

import pytest

import conftest as framework


@pytest.mark.parametrize("status", [200, 503])
def test_late_health_check_worker_reuses_completed_result(monkeypatch, tmp_path, status):
    calls = []
    closed = []

    class ProbeClient:
        def __init__(self, **kwargs):
            pass

        def get(self, *args, **kwargs):
            calls.append(args)
            return SimpleNamespace(status_code=status)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(framework, "ApiClient", ProbeClient)
    monkeypatch.setattr(framework, "_HEALTH_CHECK_LOCK", tmp_path / "health.lock")
    monkeypatch.setattr(framework, "_HEALTH_CHECK_RESULT", tmp_path / "health.result")
    # Sequential workers exercise the late-acquirer case: both successfully
    # acquire the real file lock, but only the first may call the service.
    for _ in range(2):
        if status == 200:
            framework.health_check.__wrapped__(None, None)
        else:
            with pytest.raises(pytest.exit.Exception, match="health check failed"):
                framework.health_check.__wrapped__(None, None)
    assert len(calls) == 1
    assert len(closed) == 1


def test_cleanup_registration_is_idempotent(monkeypatch):
    monkeypatch.setattr(framework, "_orphan_registry", [])
    framework.register_for_cleanup(42)
    framework.register_for_cleanup(42)
    assert framework._orphan_registry == [42]
    framework.deregister_from_cleanup(42)
    assert framework._orphan_registry == []


@pytest.mark.parametrize("outcome", ["delete_failed", "auth_failed", "deleted", "absent"])
def test_fixture_cleanup_retains_only_unresolved_resources(monkeypatch, outcome):
    monkeypatch.setattr(framework, "_orphan_registry", [])
    closed = []
    deleted = []

    class CleanupClient:
        def set_auth_token(self, token):
            assert token == "synthetic"

        def close(self):
            closed.append(True)

    class CleanupBooking:
        def authenticate(self, **kwargs):
            assert outcome == "auth_failed"
            raise RuntimeError("controlled authentication failure")

        def booking_exists(self, booking_id):
            return outcome != "absent"

        def delete_booking(self, booking_id):
            deleted.append(booking_id)
            if outcome == "delete_failed":
                raise RuntimeError("controlled delete failure")

    monkeypatch.setattr(framework, "DirectApiClient", CleanupClient)
    monkeypatch.setattr(framework, "BookingClient", lambda client: CleanupBooking())
    if outcome == "auth_failed":
        monkeypatch.setattr(framework.settings, "api_token", None)
        monkeypatch.setattr(framework, "_teardown_token_cache", None)
        monkeypatch.setattr(framework, "_teardown_token_obtained_at", None)
    else:
        monkeypatch.setattr(framework, "_get_cached_teardown_token", lambda: "synthetic")
    creator = SimpleNamespace(create_booking=lambda payload: SimpleNamespace(bookingid=42))
    payload = object()
    fixture = framework.created_booking.__wrapped__(creator, payload)
    assert next(fixture) == (42, payload)
    assert framework._orphan_registry == [42]
    fixture.close()
    unresolved = outcome in {"delete_failed", "auth_failed"}
    assert framework._orphan_registry == ([42] if unresolved else [])
    clients_per_attempt = 2 if outcome == "auth_failed" else 1
    assert closed == [True] * clients_per_attempt
    if unresolved:
        # Repeated failed cleanup must keep one session-sweep entry and close
        # each independent client, including failures before DELETE.
        framework._safe_delete_booking_direct(42)
        assert framework._orphan_registry == [42]
        assert closed == [True] * (clients_per_attempt * 2)
    assert bool(deleted) == (outcome in {"delete_failed", "deleted"})
