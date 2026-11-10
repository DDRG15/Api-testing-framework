from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.utils.history import build_history, render_history_html, write_history_report

ROOT = Path(__file__).resolve().parents[2]


def phase(index, outcome="passed", *, context="context-a", timestamp=True, test_id="tests/test_api.py::test_effect", **extra):
    value = {
        "event": "test_result", "run_id": f"run-{index:02}", "test_id": test_id,
        "phase": "call", "outcome": outcome, "attempt": 1,
        "environment": "synthetic", "revision": "abc123", "contract_digest": "contract-a",
        "context_digest": context, "duration_s": 0.1,
    }
    if timestamp:
        value["run_started_utc"] = f"2026-11-07T12:{index:02}:00+00:00"
    return {**value, **extra}


def complete_phases(events):
    """Expand synthetic call outcomes into complete pytest attempt evidence."""
    completed = []
    for event in events:
        if event["phase"] == "call":
            completed.append({**event, "phase": "setup", "outcome": "passed"})
        completed.append(event)
        if event["phase"] == "call":
            completed.append({**event, "phase": "teardown", "outcome": "passed"})
    return completed


def history_from_calls(events, **kwargs):
    return build_history(complete_phases(events), **kwargs)


def test_truncated_passed_call_is_not_a_successful_history_sample():
    history = build_history([phase(0)])
    row = history["rows"][0]
    assert row["sample_count"] == 0
    assert row["results"][0]["result"] == "incomplete"
    assert row["review_status"] == "insufficient_history"


def test_stable_and_alternating_runs_have_bounded_review_status():
    stable = history_from_calls([phase(i) for i in range(10)])["rows"][0]
    assert stable["review_status"] == "no_pattern_detected"
    assert stable["switches"] == 0
    alternating = history_from_calls([phase(i, "passed" if i % 2 else "failed") for i in range(10)])
    assert alternating["candidate_count"] == 1
    assert alternating["rows"][0]["switches"] == 9
    assert "human review" in alternating["note"]
    assert "quarantine" in alternating["note"]


def test_threshold_and_context_isolation_prevent_false_candidates():
    events = [phase(i, "failed" if i % 2 else "passed", context="a" if i < 5 else "b") for i in range(10)]
    history = history_from_calls(events)
    assert len(history["rows"]) == 2
    assert history["candidate_count"] == 0
    assert {row["review_status"] for row in history["rows"]} == {"insufficient_history"}
    assert {row["sample_count"] for row in history["rows"]} == {5}


def test_missing_context_or_chronology_is_visible_without_classification():
    missing = history_from_calls([phase(i, "failed" if i % 2 else "passed", context=None) for i in range(10)])
    assert len(missing["rows"]) == 10
    assert missing["candidate_count"] == 0
    assert {row["review_status"] for row in missing["rows"]} == {"unverified_context"}
    without_time = history_from_calls([phase(i, timestamp=False) for i in range(10)])
    assert without_time["ordering"] == "supplied_input_order"
    assert without_time["rows"][0]["review_status"] == "unverified_chronology"


def test_chronological_sorting_uses_timestamps_instead_of_uuid_order():
    history = history_from_calls([phase(9), phase(0), phase(3)])
    assert [run["run_id"] for run in history["runs"]] == ["run-00", "run-03", "run-09"]
    tied = history_from_calls([phase(i, run_started_utc="2026-11-07T12:00:00Z") for i in range(10)])
    assert tied["rows"][0]["review_status"] == "unverified_chronology"


def test_skips_break_switch_sequences_and_expected_failures_are_not_binary_samples():
    history = history_from_calls([phase(0, "passed"), phase(1, "skipped"), phase(2, "failed"),
                             phase(3, "passed", expected_failure=True)], min_runs=2)
    row = history["rows"][0]
    assert row["sample_count"] == 2
    assert row["switches"] == 0


def test_recovered_rerun_is_preserved_without_claiming_cross_run_flakiness():
    events = [phase(0, "rerun"), phase(0, "passed", attempt=2)]
    row = history_from_calls(events)["rows"][0]
    assert row["recovered_reruns"] == 1
    assert row["results"][0]["attempts"] == 2
    assert "rerun" in row["results"][0]["initial_outcomes"]
    assert row["review_status"] == "insufficient_history"


def test_conflicting_provenance_and_duplicate_phases_are_rejected():
    with pytest.raises(ValueError, match="Conflicting provenance"):
        build_history([phase(0), phase(0, phase="teardown", context="different")])
    with pytest.raises(ValueError, match="Duplicate phase"):
        history_from_calls([phase(0), phase(0)])
    with pytest.raises(ValueError, match="timezone"):
        history_from_calls([phase(0, run_started_utc="2026-11-07T12:00:00")])


def test_generated_html_escapes_identifiers_and_embeds_no_external_resources():
    attack = '</script><img src="https://invalid.example/x" onerror="alert(1)">'
    history = history_from_calls([phase(0, test_id=attack, failure_details="DO_NOT_EXPORT")])
    page = render_history_html(history)
    assert attack not in page
    assert "&lt;/script&gt;" in page
    assert "\\u003c/script>" in page
    assert "DO_NOT_EXPORT" not in page
    assert '<script src=' not in page and '<link ' not in page
    assert 'data-cell="0"' in page and 'aria-live="polite"' in page


def test_files_are_written_once_with_safe_csv_and_source_hashes(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text("\n".join(json.dumps(event) for event in complete_phases([phase(0, test_id="=formula")])) + "\n")
    output = tmp_path / "report"
    history = write_history_report([source], output)
    assert len(history["inputs"][0]["sha256"]) == 64
    assert {p.name for p in output.iterdir()} == {"history.html", "history.json", "history.csv"}
    with (output / "history.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["test_id"] == "'=formula"
    with pytest.raises(FileExistsError):
        write_history_report([source], output)


@pytest.mark.parametrize("content", ["", "not json\n", "[]\n", '{"event":"test_result"}\n'])
def test_cli_rejects_empty_or_malformed_evidence(tmp_path, content):
    source = tmp_path / "source.jsonl"
    source.write_text(content)
    output = tmp_path / "report"
    process = subprocess.run([sys.executable, "scripts/build_history_report.py", str(source),
                              "--output", str(output)], cwd=ROOT, env=os.environ.copy(),
                             capture_output=True, text=True, timeout=10)
    assert process.returncode == 2
    assert "History report failed" in process.stderr
    assert not output.exists()


def test_cli_generates_heatmap_for_valid_history(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text("\n".join(json.dumps(event) for event in complete_phases([phase(i) for i in range(10)])) + "\n")
    output = tmp_path / "report"
    process = subprocess.run([sys.executable, "scripts/build_history_report.py", str(source),
                              "--output", str(output)], cwd=ROOT, env=os.environ.copy(),
                             capture_output=True, text=True, timeout=10)
    assert process.returncode == 0, process.stderr
    assert (output / "history.html").is_file()
    assert "0 candidates" in process.stdout
