"""Client for the synthetic billing acceptance contract used by the local lab.

This is deliberately narrower than Stripe's event API. It signs the exact JSON
bytes produced by requests, but does not claim Stripe SDK compatibility.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field
from requests import Response

from src.client.base_client import ApiClient, SecurityError


class BillingEvent(BaseModel):
    """A synthetic integer-minor-unit ledger event, with strict input types."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    org_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    amount: int = Field(gt=0, le=100_000_000)


class BillingClient:
    """Explicitly opts into POST retries for a server that deduplicates events.

    Use only against an endpoint whose contract guarantees one effect per
    (org_id, event_id). Supplying a key alone cannot make a server idempotent.
    The caller owns and closes the underlying ApiClient.
    """

    def __init__(self, client: ApiClient, signing_secret: str) -> None:
        if not signing_secret:
            raise ValueError("A non-empty signing secret is required")
        parsed = urlparse(client._base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise SecurityError("Billing signatures require HTTPS outside loopback")
        self.client = client
        self._secret = signing_secret.encode("utf-8")

    def submit(self, event: BillingEvent, *, timestamp: int | None = None) -> Response:
        """Submit stable event identity and payload, retaining them across retries."""
        payload = event.model_dump()
        # requests uses json.dumps(..., allow_nan=False) for its json= argument.
        raw = json.dumps(payload, allow_nan=False).encode("utf-8")
        stamp = int(time.time()) if timestamp is None else timestamp
        signed = str(stamp).encode("ascii") + b"." + raw
        digest = hmac.new(self._secret, signed, hashlib.sha256).hexdigest()
        return self.client.request(
            "POST",
            "/webhook/stripe",
            json=payload,
            headers={
                "Stripe-Signature": f"t={stamp},v1={digest}",
                "Idempotency-Key": event.event_id,
            },
            retry_safe=True,
        )
