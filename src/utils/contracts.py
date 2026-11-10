"""Versioned local model schemas; these are not the provider's OpenAPI spec."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.models import booking

MODELS = (
    booking.BookingDates, booking.BookingPayload, booking.BookingResponse,
    booking.CreateBookingResponse, booking.BookingSummary,
    booking.AuthTokenResponse, booking.PartialBookingPayload,
)


def schemas() -> dict[str, str]:
    return {
        model.__name__: json.dumps(model.model_json_schema(), sort_keys=True, indent=2) + "\n"
        for model in MODELS
    }


def contract_digest() -> str:
    return hashlib.sha256("".join(schemas().values()).encode()).hexdigest()


def check_snapshots(directory: Path) -> list[str]:
    expected = schemas()
    changed = [name for name, content in expected.items()
               if not (directory / f"{name}.json").is_file()
               or (directory / f"{name}.json").read_text(encoding="utf-8") != content]
    changed.extend(path.stem for path in directory.glob("*.json") if path.stem not in expected)
    return sorted(changed)


def write_snapshots(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in schemas().items():
        (directory / f"{name}.json").write_text(content, encoding="utf-8")

