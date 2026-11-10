from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.utils.response_evaluation import (
    EvaluationConfigError,
    evaluate_records,
    evaluation_markdown,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "fixtures/evaluation/config.json").read_text())


def sample(**changes):
    return {
        "case_id": "case-1", "model_id": "synthetic-model", "prompt_version": "v1", "elapsed_ms": 10,
        "response": {"grams_min": 90, "grams_max": 110, "parts": [30, 70], "total": 100}, **changes,
    }


def evaluate(*records):
    return evaluate_records(records, CONFIG)


def test_different_valid_answers_pass_and_have_diversity():
    report = evaluate(sample(), sample(response={"grams_min": 80, "grams_max": 120, "parts": [20, 80], "total": 100}))
    assert report["failed_records"] == 0
    assert report["groups"][0]["distinct_valid_responses"] == 2
    assert report["groups"][0]["schema_passes"] == 2
    assert "Raw responses" in evaluation_markdown(report)


def test_schema_and_invariant_failures_are_retained_without_response_contents():
    bad = sample(response={"grams_min": 120, "grams_max": 100, "parts": [20, 70], "total": 100, "secret": "SECRET_PAYLOAD"})
    report = evaluate(sample(), bad)
    assert report["total_records"] == 2
    assert report["failed_records"] == 1
    assert {error["code"] for error in report["errors"]} == {"schema_violation", "invariant_violation"}
    assert "SECRET_PAYLOAD" not in json.dumps(report)
    assert "SECRET_PAYLOAD" not in evaluation_markdown(report)


@pytest.mark.parametrize("change", [
    {"rules": [{"kind": "execute", "code": "print('not allowed')"}]},
    {"rules": [{"kind": "sum_equals", "total": "/total", "parts": "/parts", "tolerance": -1}]},
    {"rules": [{"kind": "ordered_range", "low": "/bad~2pointer", "high": "/grams_max"}]},
    {"schema": {"type": "not_a_json_schema_type"}},
    {"schema": {"$ref": "https://example.invalid/schema.json"}},
    {"unexpected": True},
])
def test_invalid_configuration_and_unknown_rules_fail_explicitly(change):
    with pytest.raises(EvaluationConfigError):
        evaluate_records([sample()], {**CONFIG, **change})


def test_unresolvable_local_schema_reference_is_config_error():
    with pytest.raises(EvaluationConfigError, match="cannot_be_evaluated"):
        evaluate_records([sample()], {"schema": {"$ref": "#/$defs/missing"}, "rules": []})


def test_percentile_requires_20_samples_and_is_nearest_rank():
    small = evaluate(*(sample(elapsed_ms=index) for index in range(1, 20)))
    assert small["groups"][0]["p95_elapsed_ms"] is None
    assert small["groups"][0]["p95_status"] == "insufficient_samples"
    full = evaluate(*(sample(elapsed_ms=index) for index in range(1, 21)))
    assert full["groups"][0]["p95_elapsed_ms"] == 19
    assert full["groups"][0]["p95_status"] == "descriptive_only"
    assert "no SLA" in full["note"]


def test_case_model_and_prompt_versions_are_separate_groups():
    report = evaluate(sample(), sample(model_id="other"), sample(prompt_version="v2"), sample(case_id="case-2"))
    assert len(report["groups"]) == 4
    assert all(group["samples"] == 1 for group in report["groups"])


@pytest.mark.parametrize("changes", [
    {"case_id": ""}, {"model_id": None}, {"prompt_version": "bad\nmetadata"},
    {"elapsed_ms": -1}, {"elapsed_ms": True}, {"elapsed_ms": float("nan")},
    {"elapsed_ms": float("inf")},
])
def test_invalid_metadata_and_latency_are_failed_records(changes):
    report = evaluate(sample(**changes))
    assert report["total_records"] == 1
    assert report["failed_records"] == 1
    assert report["errors"]


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "90"])
def test_invariants_reject_non_numeric_or_non_finite_values(value):
    response = sample()["response"]
    response["grams_min"] = value
    response["parts"] = [value, 70]
    report = evaluate(sample(response=response))
    assert report["failed_records"] == 1


def test_sum_uses_absolute_tolerance_and_rejects_missing_fields():
    response = sample()["response"]
    response["parts"] = [0.1, 0.2]
    response["total"] = 0.3
    assert evaluate(sample(response=response))["failed_records"] == 0
    del response["total"]
    assert evaluate(sample(response=response))["failed_records"] == 1


def test_boolean_tolerance_and_nonfinite_config_are_rejected():
    config = copy.deepcopy(CONFIG)
    for value in (True, float("inf")):
        config["rules"][1]["tolerance"] = value
        with pytest.raises(EvaluationConfigError):
            evaluate_records([sample()], config)


def test_nonobjects_missing_response_and_empty_input_are_explicit():
    missing = sample()
    del missing["response"]
    report = evaluate(None, missing)
    assert report["total_records"] == 2
    assert report["failed_records"] == 2
    assert evaluate_records([], CONFIG)["total_records"] == 0


def run_cli(inputs: Path, config: Path, output: Path):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/evaluate_responses.py"), str(inputs), "--config", str(config), "--output", str(output)],
        capture_output=True, text=True,
    )


def test_cli_writes_reports_and_refuses_existing_output(tmp_path):
    output = tmp_path / "result"
    result = run_cli(ROOT / "fixtures/evaluation/synthetic_responses.jsonl", ROOT / "fixtures/evaluation/config.json", output)
    assert result.returncode == 0, result.stderr
    assert json.loads((output / "evaluation.json").read_text())["valid_records"] == 4
    assert (output / "evaluation.md").is_file()
    before = (output / "evaluation.json").read_bytes()
    again = run_cli(ROOT / "fixtures/evaluation/synthetic_responses.jsonl", ROOT / "fixtures/evaluation/config.json", output)
    assert again.returncode == 2
    assert (output / "evaluation.json").read_bytes() == before


def test_cli_malformed_line_and_schema_failure_are_not_dropped(tmp_path):
    inputs = tmp_path / "responses.jsonl"
    invalid = sample(response={"secret": "DONT_ECHO_ME"})
    inputs.write_text(json.dumps(sample()) + "\nnot-json\n" + json.dumps(invalid) + "\n")
    output = tmp_path / "report"
    result = run_cli(inputs, ROOT / "fixtures/evaluation/config.json", output)
    assert result.returncode == 1
    report = json.loads((output / "evaluation.json").read_text())
    assert report["total_records"] == 3
    assert report["failed_records"] == 2
    assert "DONT_ECHO_ME" not in (output / "evaluation.json").read_text()
    assert "DONT_ECHO_ME" not in result.stderr


def test_cli_invalid_schema_fails_before_writing_report(tmp_path):
    config = tmp_path / "invalid.json"
    config.write_text(json.dumps({"schema": {"type": "nonsense"}, "rules": []}))
    output = tmp_path / "report"
    result = run_cli(ROOT / "fixtures/evaluation/synthetic_responses.jsonl", config, output)
    assert result.returncode == 2
    assert "invalid_response_schema" in result.stderr
    assert not output.exists()
