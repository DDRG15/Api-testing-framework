"""
src/models/booking.py
======================
Pydantic v2 data models for the Restful-Booker API.

These models serve as the API CONTRACT. Every response is deserialized
through these models. If the API changes its schema — a field is renamed,
a type changes, a required field is removed — the test fails HERE with
a clear ValidationError, not buried in a KeyError inside an assertion.

This is "shift-left contract testing" without a separate Pact broker.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BookingDates(BaseModel):
    checkin: date
    checkout: date

    @model_validator(mode="after")
    def checkout_must_be_after_checkin(self) -> BookingDates:
        if self.checkout <= self.checkin:
            raise ValueError(
                f"checkout ({self.checkout}) must be strictly after "
                f"checkin ({self.checkin})."
            )
        return self


class BookingPayload(BaseModel):
    """Request payload model — used when CREATING or UPDATING a booking."""

    firstname: str = Field(..., min_length=1, max_length=100)
    lastname: str = Field(..., min_length=1, max_length=100)
    totalprice: int = Field(..., ge=0, le=1_000_000)
    depositpaid: bool
    bookingdates: BookingDates
    additionalneeds: str | None = Field(default=None, max_length=500)

    @field_validator("firstname", "lastname")
    @classmethod
    def no_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name fields cannot be whitespace-only.")
        return v


class BookingResponse(BaseModel):
    """
    Response model for a single booking object.
    Identical to BookingPayload — a separate model is intentional:
    request and response shapes can diverge without warning.
    """

    firstname: str
    lastname: str
    totalprice: int
    depositpaid: bool
    bookingdates: BookingDates
    additionalneeds: str | None = None


class CreateBookingResponse(BaseModel):
    """Wrapper returned by POST /booking."""

    # gt=0 already rejects a missing/zero/negative ID with a clear ValidationError,
    # so no extra model_validator is needed here.
    bookingid: int = Field(..., gt=0, description="Server-assigned ID. Must be positive.")
    booking: BookingResponse


class BookingSummary(BaseModel):
    """Lightweight item in the GET /booking list response."""

    bookingid: int = Field(..., gt=0)


class AuthTokenResponse(BaseModel):
    """Response from POST /auth."""

    token: str = Field(..., min_length=1, description="Session token for privileged operations.")


class PartialBookingPayload(BaseModel):
    """
    Payload model for PATCH /booking/{id}.

    All fields are optional — only provided fields are sent to the API.
    extra="forbid" ensures unknown fields raise ValidationError before any
    HTTP call is made, keeping PATCH in line with the full PUT contract.
    """

    model_config = ConfigDict(extra="forbid")

    firstname: str | None = Field(default=None, min_length=1, max_length=100)
    lastname: str | None = Field(default=None, min_length=1, max_length=100)
    totalprice: int | None = Field(default=None, ge=0, le=1_000_000)
    depositpaid: bool | None = None
    bookingdates: BookingDates | None = None
    additionalneeds: str | None = Field(default=None, max_length=500)
