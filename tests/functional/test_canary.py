"""
Small live booking probe using a static, synthetic payload.

The probe creates, reads and attempts to delete one booking. It uses canonical
BookingPayload/BookingDates models, including the checkout/checkin invariant.
Run it only against a configured environment that permits test-data mutations.
A static payload does not guarantee WAF acceptance or cleanup after termination.
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
    Creates and attempts to remove test data in an explicitly permitted
    environment. Provider availability and cleanup are not guaranteed.
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
    #    leaves the ID available for a later cleanup attempt.
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
