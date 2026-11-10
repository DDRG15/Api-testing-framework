"""
Synthetic booking data using Faker, UUID fragments and relative dates.

UUID suffixes reduce collision risk across workers and runs; they do not
provide a zero-collision guarantee. Human-like names and Unicode variants
exercise selected input shapes without using real customer records.

The realistic payload embeds a run identifier for tracing possible leftovers.
A seed reproduces Faker-derived fields, not the complete payload: UUIDs are
fresh, dates depend on the current day, and run identifiers can change.
Boundary methods provide specific length, price and character-set cases; they
are not exhaustive input-space coverage.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from typing import Any

from faker import Faker

from src.models.booking import BookingDates, BookingPayload
from src.utils.logger import RUN_ID, get_logger

logger = get_logger(__name__)

# Module-level Faker instance with a broad locale pool.
# Each factory() call can override with a specific locale.
_faker_pool = Faker(
    ["en_US", "en_GB", "es_ES", "fr_FR", "de_DE", "ja_JP"]
)


class BookingDataFactory:
    """
    Generates synthetic BookingPayload instances with UUID-suffixed identifiers.

    Usage:
        factory = BookingDataFactory()
        payload = factory.realistic()       # Random realistic booking
        edge    = factory.max_length()      # Max-field-length stress test
        minimal = factory.minimum_price()   # Boundary: price = 0
    """

    def __init__(self, seed: int | None = None) -> None:
        """
        Args:
            seed: Optional integer seed for deterministic generation.
                  If None, a random seed is logged to help reproduce Faker-derived fields.
        """
        if seed is None:
            seed = random.randint(0, 2**32 - 1)

        self._seed = seed
        self._faker = Faker(["en_US", "en_GB"])
        self._faker.seed_instance(seed)

        logger.debug(
            "data_factory_initialized",
            seed=seed,
            run_id=RUN_ID,
            note="This seed reproduces Faker-derived fields; UUIDs and dates may differ.",
        )

    @property
    def seed(self) -> int:
        return self._seed

    # ------------------------------------------------------------------
    # Primary factory methods
    # ------------------------------------------------------------------

    def realistic(
        self,
        checkin_offset_days: int = 30,
        stay_duration_days: int = 3,
    ) -> BookingPayload:
        """
        Generate a realistic booking payload with randomized human-like data.

        The unique_tag (UUID fragment) is embedded in the lastname to reduce
        collisions and help distinguish synthetic records.

        Args:
            checkin_offset_days: Days from today for checkin date.
            stay_duration_days:  Length of stay in days.
        """
        unique_tag = uuid.uuid4().hex[:8].upper()
        checkin = date.today() + timedelta(days=checkin_offset_days)
        checkout = checkin + timedelta(days=stay_duration_days)

        # Embed unique_tag into lastname — searchable in the API without
        # reducing confusion with other records
        firstname = self._faker.first_name()
        lastname = f"{self._faker.last_name()}-{unique_tag}"

        price = self._faker.random_int(min=50, max=2500)
        deposit = self._faker.boolean(chance_of_getting_true=70)
        needs = self._faker.random_element(
            elements=[
                "Early check-in",
                "Late checkout",
                "Airport transfer",
                "Vegetarian meals",
                "Extra towels",
                "Wheelchair accessible room",
                "Sea view room",
                None,
            ]
        )

        payload = BookingPayload(
            firstname=firstname,
            lastname=lastname,
            totalprice=price,
            depositpaid=deposit,
            bookingdates=BookingDates(checkin=checkin, checkout=checkout),
            additionalneeds=f"run:{RUN_ID[:8]} | {needs}" if needs else f"run:{RUN_ID[:8]}",
        )

        logger.debug(
            "synthetic_payload_generated",
            variant="realistic",
            firstname=firstname,
            lastname=lastname,
            seed=self._seed,
        )
        return payload

    def max_length(self) -> BookingPayload:
        """
        Stress-test payload: all string fields at their maximum allowed length.
        Designed to catch truncation bugs, database column overflow, and
        API-level field length validation regressions.
        """
        unique_tag = uuid.uuid4().hex[:8].upper()
        checkin = date.today() + timedelta(days=1)

        # Max lengths per BookingPayload model definition
        firstname = f"{'F' * 91}-{unique_tag}"[:100]
        lastname = f"{'L' * 91}-{unique_tag}"[:100]

        payload = BookingPayload(
            firstname=firstname,
            lastname=lastname,
            totalprice=1_000_000,  # Maximum allowed
            depositpaid=True,
            bookingdates=BookingDates(
                checkin=checkin,
                checkout=checkin + timedelta(days=365),
            ),
            additionalneeds=("X" * 483 + f" run:{RUN_ID[:8]}")[:500],  # At 500 char limit
        )

        logger.debug("synthetic_payload_generated", variant="max_length", seed=self._seed)
        return payload

    def minimum_price(self) -> BookingPayload:
        """
        Boundary test: totalprice = 0. Some systems treat zero as null.
        This is a known edge case in financial systems — a $0 booking
        can trigger different code paths than a $1 booking.
        """
        unique_tag = uuid.uuid4().hex[:8].upper()
        checkin = date.today() + timedelta(days=14)

        payload = BookingPayload(
            firstname=f"Zero-{unique_tag}",
            lastname=f"Price-{unique_tag}",
            totalprice=0,
            depositpaid=False,
            bookingdates=BookingDates(
                checkin=checkin,
                checkout=checkin + timedelta(days=1),
            ),
            additionalneeds=f"boundary:zero_price run:{RUN_ID[:8]}",
        )

        logger.debug("synthetic_payload_generated", variant="minimum_price", seed=self._seed)
        return payload

    def unicode_names(self) -> BookingPayload:
        """
        Unicode stress test: names from non-Latin character sets.
        Financial systems must handle international customer names correctly.
        Character encoding bugs are disproportionately common in name fields.
        """
        unicode_faker = Faker(["ja_JP", "zh_CN", "ar_EG", "ru_RU"])
        unique_tag = uuid.uuid4().hex[:8].upper()
        checkin = date.today() + timedelta(days=7)

        firstname = unicode_faker.first_name()
        lastname = f"{unicode_faker.last_name()}-{unique_tag}"

        payload = BookingPayload(
            firstname=firstname,
            lastname=lastname,
            totalprice=500,
            depositpaid=True,
            bookingdates=BookingDates(
                checkin=checkin,
                checkout=checkin + timedelta(days=2),
            ),
            additionalneeds=f"unicode_test run:{RUN_ID[:8]}",
        )

        logger.debug(
            "synthetic_payload_generated",
            variant="unicode_names",
            firstname=firstname,
            lastname=lastname,
            seed=self._seed,
        )
        return payload

    def bulk(self, count: int, **kwargs: Any) -> list[BookingPayload]:
        """
        Generate `count` unique realistic payloads.
        Each gets its own UUID suffix — safe for parallel creation.
        """
        return [self.realistic(**kwargs) for _ in range(count)]
