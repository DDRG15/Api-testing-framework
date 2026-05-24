"""
tests/performance/locustfile.py
================================
Locust load baseline for the Restful-Booker API.

Reuses BookingClient and BookingDataFactory directly — no data duplication,
no separate HTTP setup. If the domain model changes, the load test picks it
up automatically.

Usage:
    # Install performance dependencies first
    pip install -r requirements-perf.txt

    # Headless baseline run (30 users, 5 minutes)
    locust -f tests/performance/locustfile.py \
        --headless \
        --users 30 \
        --spawn-rate 5 \
        --run-time 5m \
        --host https://restful-booker.herokuapp.com

    # Interactive UI (opens browser at http://localhost:8089)
    locust -f tests/performance/locustfile.py \
        --host https://restful-booker.herokuapp.com

Environment variables:
    API_BASE_URL   — target host (overrides --host if set)
    API_USERNAME   — auth username
    API_PASSWORD   — auth password
"""
from __future__ import annotations

import os

from locust import HttpUser, between, task

from src.client.base_client import ApiClient
from src.client.booking_client import BookingClient
from src.utils.data_factory import BookingDataFactory


class _LocustApiClient(ApiClient):
    """
    Thin adapter that routes requests through Locust's HttpUser session
    so Locust can record latency, failure rate, and percentiles.

    Overrides the session with the one Locust manages so all requests
    appear in the Locust statistics dashboard.
    """

    def __init__(self, locust_client: HttpUser) -> None:
        super().__init__(base_url=locust_client.host)
        # Replace the requests.Session with Locust's tracked client
        self._session = locust_client.client  # type: ignore[assignment]


class BookingLoadUser(HttpUser):
    """
    Simulates a single concurrent user against the booking API.

    Task weights reflect a realistic read-heavy traffic pattern:
      - list_bookings:  weight 3  (browsing / search)
      - create+delete:  weight 2  (write cycle — always cleaned up)
      - get_booking:    weight 5  (detail page — most common)

    wait_time: 1–3 seconds between tasks — mimics human pacing,
    avoids hammering the free-tier Heroku API into rate limiting.
    """

    wait_time = between(1, 3)
    _booking_client: BookingClient
    _factory: BookingDataFactory

    def on_start(self) -> None:
        """Called once per simulated user at spawn time."""
        api_client = _LocustApiClient(self)
        self._booking_client = BookingClient(api_client)
        self._factory = BookingDataFactory()

        username = os.environ.get("API_USERNAME", "admin")
        password = os.environ.get("API_PASSWORD", "password123")
        self._booking_client.authenticate(username=username, password=password)

    @task(3)
    def list_bookings(self) -> None:
        """GET /booking — list all booking IDs."""
        self._booking_client.list_bookings()

    @task(5)
    def get_booking(self) -> None:
        """GET /booking/1 — fetch a known booking (static ID for stability)."""
        try:
            self._booking_client.get_booking(1)
        except Exception:
            pass  # Booking may not exist on all environments; not a load-test failure

    @task(2)
    def create_and_delete_booking(self) -> None:
        """POST /booking → DELETE /booking/{id} — full write cycle, always cleaned up."""
        payload = self._factory.realistic()
        try:
            response = self._booking_client.create_booking(payload)
            self._booking_client.delete_booking(response.bookingid)
        except Exception:
            pass  # Log via Locust's built-in failure tracking
