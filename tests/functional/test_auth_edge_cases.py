"""
tests/functional/test_auth_edge_cases.py
==========================================
Auth edge case tests: invalid credentials, bad token, missing token.

These tests validate the API's authentication enforcement boundaries.
A framework that only tests the happy path leaves the most common
real-world failure mode — misconfigured or expired credentials —
completely untested.

All tests use a fresh DirectApiClient (no circuit breaker) so auth
failures do not trip the shared circuit breaker used by other tests.
"""
from __future__ import annotations

from src.client.base_client import ApiClient
from src.models.booking import BookingPayload
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_client() -> ApiClient:
    """Fresh client with no token injected — used for auth boundary tests."""
    return ApiClient()


# ---------------------------------------------------------------------------
# Invalid credential tests
# ---------------------------------------------------------------------------


class TestInvalidCredentials:
    """POST /auth with bad credentials must not issue a usable token."""

    def test_wrong_password_returns_bad_credentials(self) -> None:
        """
        Restful-Booker returns HTTP 200 with body {"reason": "Bad credentials"}
        on invalid login — not a 401. The framework must not treat this 200 as
        a successful auth.
        """
        client = _raw_client()

        response = client.post("/auth", json={"username": "admin", "password": "WRONG"})
        assert response.status_code == 200

        body = response.json()
        assert "reason" in body, f"Expected 'reason' key in auth failure body, got: {body}"
        assert body["reason"] == "Bad credentials"

        # No token key must be present
        assert "token" not in body, "Server must not issue a token on bad credentials"

        client.close()
        logger.info("auth_edge_case_passed", case="wrong_password")

    def test_empty_credentials_rejected(self) -> None:
        """Empty username and password must not yield a usable token."""
        client = _raw_client()

        response = client.post("/auth", json={"username": "", "password": ""})
        assert response.status_code == 200

        body = response.json()
        assert "token" not in body or body.get("reason") == "Bad credentials", (
            f"Empty credentials must not produce a valid token. Got: {body}"
        )

        client.close()
        logger.info("auth_edge_case_passed", case="empty_credentials")

    def test_missing_credentials_fields_rejected(self) -> None:
        """Omitting both fields entirely must not yield a token."""
        client = _raw_client()

        response = client.post("/auth", json={})
        body = response.json()

        assert "token" not in body or body.get("reason") is not None, (
            f"Payload with no credentials must not produce a valid token. Got: {body}"
        )

        client.close()
        logger.info("auth_edge_case_passed", case="missing_fields")


# ---------------------------------------------------------------------------
# Bad / missing token tests
# ---------------------------------------------------------------------------


class TestBadToken:
    """Operations requiring auth must reject invalid or absent tokens."""

    def test_delete_with_invalid_token_returns_403(
        self, created_booking: tuple[int, BookingPayload]
    ) -> None:
        """
        DELETE /booking/{id} with a fabricated token must return 403.
        A 200 here means the auth layer is not enforced.
        """
        booking_id, _ = created_booking
        client = _raw_client()
        client._session.headers["Cookie"] = "token=this-is-not-a-real-token"

        response = client.delete(f"/booking/{booking_id}")
        assert response.status_code == 403, (
            f"Expected 403 Forbidden with invalid token, got {response.status_code}. "
            "Auth enforcement on DELETE is broken."
        )

        client.close()
        logger.info("auth_edge_case_passed", case="invalid_token_delete", booking_id=booking_id)

    def test_delete_with_no_token_returns_403(
        self, created_booking: tuple[int, BookingPayload]
    ) -> None:
        """
        DELETE /booking/{id} with no Cookie header must return 403.
        """
        booking_id, _ = created_booking
        client = _raw_client()
        # Ensure no token header is present
        client._session.headers.pop("Cookie", None)

        response = client.delete(f"/booking/{booking_id}")
        assert response.status_code == 403, (
            f"Expected 403 Forbidden with no token, got {response.status_code}. "
            "Auth enforcement on DELETE is broken."
        )

        client.close()
        logger.info("auth_edge_case_passed", case="no_token_delete", booking_id=booking_id)

    def test_put_with_invalid_token_returns_403(
        self, created_booking: tuple[int, BookingPayload]
    ) -> None:
        """
        PUT /booking/{id} with a fabricated token must return 403.
        Full update requires auth; a 200 here means the guard is bypassed.
        """
        booking_id, _ = created_booking
        client = _raw_client()
        client._session.headers["Cookie"] = "token=fabricated-garbage-token"

        response = client.put(
            f"/booking/{booking_id}",
            json={
                "firstname": "Ghost",
                "lastname": "Writer",
                "totalprice": 0,
                "depositpaid": False,
                "bookingdates": {"checkin": "2026-06-01", "checkout": "2026-06-05"},
                "additionalneeds": "",
            },
        )
        assert response.status_code == 403, (
            f"Expected 403 Forbidden with invalid token on PUT, got {response.status_code}."
        )

        client.close()
        logger.info("auth_edge_case_passed", case="invalid_token_put", booking_id=booking_id)
