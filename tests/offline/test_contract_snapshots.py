from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.utils.contracts import check_snapshots, schemas, write_snapshots

ROOT = Path(__file__).resolve().parents[2]


def test_versioned_model_schemas_match():
    assert check_snapshots(ROOT / "fixtures/contracts") == []
    for schema in schemas().values():
        Draft202012Validator.check_schema(json.loads(schema))


def test_removed_required_field_is_detected(tmp_path):
    write_snapshots(tmp_path)
    path = tmp_path / "BookingPayload.json"
    schema = json.loads(path.read_text())
    schema["required"].remove("firstname")
    path.write_text(json.dumps(schema))
    assert check_snapshots(tmp_path) == ["BookingPayload"]


def test_type_change_is_detected(tmp_path):
    write_snapshots(tmp_path)
    path = tmp_path / "BookingSummary.json"
    schema = json.loads(path.read_text())
    schema["properties"]["bookingid"]["type"] = "string"
    path.write_text(json.dumps(schema))
    assert check_snapshots(tmp_path) == ["BookingSummary"]


def test_missing_and_unexpected_baselines_fail(tmp_path):
    write_snapshots(tmp_path)
    (tmp_path / "BookingDates.json").unlink()
    (tmp_path / "RetiredModel.json").write_text("{}")
    assert check_snapshots(tmp_path) == ["BookingDates", "RetiredModel"]
