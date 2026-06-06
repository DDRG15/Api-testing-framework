"""
tests/functional/test_canary.py
=================================
Canary probe: single-threaded, static payload against the live API.

Used for safe verification against production without triggering WAFs
or polluting the database with high-entropy synthetic data. The static
payload uses canonical BookingPayload/BookingDates with proper date
objects so the full Pydantic validation stack fires — including the
checkout_must_be_after_checkin invariant.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.models.booking import BookingDates, BookingPayload
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.smoke
@pytest.mark.flaky(reruns=1, reruns_delay=2)
def test_production_canary_probe(booking_client):
    """
    CANARY PROBE: Single-threaded, static payload.
    Used for safe verification against live production environments without
    triggering WAFs or polluting the database with high-entropy synthetic data.
    """
    from conftest import deregister_from_cleanup, register_for_cleanup

    logger.info("canary_probe_start", payload="static")

    static_payload = BookingPayload(
        firstname="Canary",
        lastname="Probe",
        totalprice=1,
        depositpaid=True,
        bookingdates=BookingDates(
            checkin=date(2026, 6, 1),
            checkout=date(2026, 6, 6),
        ),
        additionalneeds="SRE Health Check",
    )

    # 1. Create — register for cleanup BEFORE the read so a failed assertion
    #    cannot leak the booking into a live/production database.
    create_response = booking_client.create_booking(static_payload)
    booking_id = create_response.bookingid
    register_for_cleanup(booking_id)
    logger.info("canary_deployed", booking_id=booking_id)

    try:
        # 2. Read — validate round-trip integrity
        read_response = booking_client.get_booking(booking_id)
        assert read_response.firstname == "Canary"
    finally:
        # 3. Delete — runs unconditionally, even if the assertion above fails.
        booking_client.delete_booking(booking_id)
        deregister_from_cleanup(booking_id)
        logger.info("canary_neutralized", booking_id=booking_id)
