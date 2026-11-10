"""Evaluate recorded, potentially variable responses without calling a provider.

Only JSON Schema and two named numeric invariants are supported. Reports retain
identifiers and validation locations, never raw response bodies or error reprs.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
POINTER_SCHEMA = {"type": "string", "maxLength": 256, "pattern": r"^(?:/(?:[^~/]|~[01])*)*$"}
CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["schema", "rules"],
    "additionalProperties": False,
    "properties": {
        "schema": {"type": ["object", "boolean"]},
        "rules": {
            "type": "array",
            "items": {"oneOf": [
                {
                    "type": "object", "additionalProperties": False,
                    "required": ["kind", "low", "high"],
                    "properties": {
                        "kind": {"const": "ordered_range"},
                        "low": POINTER_SCHEMA, "high": POINTER_SCHEMA,
                    },
                },
                {
                    "type": "object", "additionalProperties": False,
                    "required": ["kind", "total", "parts"],
                    "properties": {
                        "kind": {"const": "sum_equals"},
                        "total": POINTER_SCHEMA, "parts": POINTER_SCHEMA,
                        "tolerance": {"type": "number", "minimum": 0},
                    },
                },
            ]},
        },
    },
}


class EvaluationConfigError(ValueError):
    """A categorical configuration error without embedded input contents."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _local_references_only(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                return False
            if not _local_references_only(child):
                return False
    elif isinstance(value, list):
        return all(_local_references_only(child) for child in value)
    return True


def _validator(config: dict[str, Any]) -> Draft202012Validator:
    try:
        _canonical(config)
    except (ValueError, TypeError, OverflowError) as exc:
        raise EvaluationConfigError("config_must_be_finite_json") from exc
    if not Draft202012Validator(CONFIG_SCHEMA).is_valid(config):
        raise EvaluationConfigError("invalid_config")
    if not _local_references_only(config["schema"]):
        raise EvaluationConfigError("external_schema_references_not_allowed")
    try:
        Draft202012Validator.check_schema(config["schema"])
    except SchemaError as exc:
        raise EvaluationConfigError("invalid_response_schema") from exc
    return Draft202012Validator(config["schema"])


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _at_pointer(response: Any, pointer: str) -> Any:
    value = response
    if not pointer:
        return value
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        else:
            raise KeyError(pointer)
    return value


def _rule_passes(response: Any, rule: dict[str, Any]) -> bool:
    try:
        if rule["kind"] == "ordered_range":
            low = _number(_at_pointer(response, rule["low"]))
            high = _number(_at_pointer(response, rule["high"]))
            return low is not None and high is not None and low <= high
        total = _number(_at_pointer(response, rule["total"]))
        parts = _at_pointer(response, rule["parts"])
        if total is None or not isinstance(parts, list):
            return False
        numbers = [_number(part) for part in parts]
        if any(number is None for number in numbers):
            return False
        subtotal = math.fsum(number for number in numbers if number is not None)
        return math.isfinite(subtotal) and math.isclose(
            total, subtotal, rel_tol=0, abs_tol=float(rule.get("tolerance", 0))
        )
    except (KeyError, IndexError, TypeError, OverflowError, ValueError):
        return False


def evaluate_records(records: Iterable[Any], config: dict[str, Any]) -> dict[str, Any]:
    """Evaluate every record; invalid records count as failures and are retained.

    Each record requires case_id/model_id/prompt_version, elapsed_ms and response.
    Latency p95 is nearest-rank and descriptive only. Fewer than 20 finite,
    nonnegative observations in a group produce null, not a percentile claim.
    Remote schema references are rejected, so evaluation never retrieves schemas.
    """
    validator = _validator(config)
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    total_records = 0
    valid_records = 0
    for record_index, record in enumerate(records, 1):
        total_records += 1
        if not isinstance(record, dict):
            errors.append({"record": record_index, "code": "record_not_object"})
            continue
        metadata = (record.get("case_id"), record.get("model_id"), record.get("prompt_version"))
        if not all(isinstance(value, str) and IDENTIFIER.fullmatch(value) for value in metadata):
            errors.append({"record": record_index, "code": "invalid_metadata"})
            continue
        key = (str(metadata[0]), str(metadata[1]), str(metadata[2]))
        group = groups.setdefault(key, {
            "case_id": key[0], "model_id": key[1], "prompt_version": key[2],
            "samples": 0, "schema_passes": 0, "invariant_passes": 0,
            "valid_samples": 0, "_latencies": [], "_hashes": set(),
        })
        group["samples"] += 1
        identity = {"record": record_index, "case_id": key[0], "model_id": key[1], "prompt_version": key[2]}
        elapsed = _number(record.get("elapsed_ms"))
        record_errors: list[dict[str, Any]] = []
        if elapsed is None or elapsed < 0:
            record_errors.append({**identity, "code": "invalid_elapsed_ms"})
        else:
            group["_latencies"].append(elapsed)
        if "response" not in record:
            record_errors.append({**identity, "code": "missing_response"})
            errors.extend(record_errors)
            continue
        response = record["response"]
        try:
            encoded = _canonical(response)
        except (ValueError, TypeError, OverflowError):
            record_errors.append({**identity, "code": "response_must_be_finite_json"})
            errors.extend(record_errors)
            continue
        try:
            schema_errors = list(validator.iter_errors(response))
        except Exception as exc:
            # Unresolvable local references and invalid regular expressions
            # are configuration failures, not fabricated response results.
            raise EvaluationConfigError("response_schema_cannot_be_evaluated") from exc
        if not schema_errors:
            group["schema_passes"] += 1
        for error in schema_errors:
            record_errors.append({
                **identity, "code": "schema_violation", "keyword": error.validator,
                "path": list(error.absolute_path),
            })
        invariant_ok = True
        for rule_index, rule in enumerate(config["rules"], 1):
            if not _rule_passes(response, rule):
                invariant_ok = False
                record_errors.append({
                    **identity, "code": "invariant_violation", "rule": rule["kind"],
                    "rule_index": rule_index,
                })
        group["invariant_passes"] += int(invariant_ok)
        if not record_errors:
            valid_records += 1
            group["valid_samples"] += 1
            group["_hashes"].add(hashlib.sha256(encoded.encode("utf-8")).hexdigest())
        errors.extend(record_errors)
    result_groups = []
    for key in sorted(groups):
        group = groups[key]
        latencies = sorted(group.pop("_latencies"))
        group["latency_samples"] = len(latencies)
        group["p95_elapsed_ms"] = (
            latencies[math.ceil(0.95 * len(latencies)) - 1] if len(latencies) >= 20 else None
        )
        group["p95_status"] = "descriptive_only" if len(latencies) >= 20 else "insufficient_samples"
        group["distinct_valid_responses"] = len(group.pop("_hashes"))
        group["failed_samples"] = group["samples"] - group["valid_samples"]
        result_groups.append(group)
    return {
        "schema_version": 1,
        "evaluation_mode": "recorded_responses",
        "config_sha256": hashlib.sha256(_canonical(config).encode("utf-8")).hexdigest(),
        "total_records": total_records, "valid_records": valid_records,
        "failed_records": total_records - valid_records,
        "groups": result_groups, "errors": errors,
        "note": "Descriptive sample statistics only; no SLA, confidence, or provider validation claim.",
    }


def evaluation_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Recorded response evaluation", "",
        f"Records: {report['total_records']}; valid: {report['valid_records']}; failed: {report['failed_records']}.",
        "", report["note"], "",
        "| Case | Model | Prompt | Samples | Schema passes | Invariant passes | Valid diversity | p95 ms |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for group in report["groups"]:
        p95 = group["p95_elapsed_ms"]
        latency = "insufficient samples" if p95 is None else str(p95)
        lines.append(
            f"| {group['case_id']} | {group['model_id']} | {group['prompt_version']} | "
            f"{group['samples']} | {group['schema_passes']} | {group['invariant_passes']} | "
            f"{group['distinct_valid_responses']} | {latency} |"
        )
    lines += ["", "p95 uses nearest-rank only with at least 20 latency observations per group.",
              "Raw responses and validation messages are excluded from reports."]
    if report["errors"]:
        lines += ["", "| Record | Error code |", "|---:|---|"]
        lines += [f"| {error['record']} | {error['code']} |" for error in report["errors"]]
    return "\n".join(lines) + "\n"
