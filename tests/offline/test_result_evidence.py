from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.utils.test_results import load_events, summarize

ROOT = Path(__file__).resolve().parents[2]


def test_real_rerun_setup_and_teardown_evidence(tmp_path):
    output = tmp_path / "child"
    child = subprocess.run(
        [sys.executable, "scripts/run_offline.py", "--output", str(output), "--",
         "tests/fixtures/phase_cases.py"], cwd=ROOT, env=os.environ.copy(),
        capture_output=True, text=True, timeout=45,
    )
    assert child.returncode == 1, child.stdout + child.stderr
    summary = json.loads((output / "summary.json").read_text())
    assert summary["total"] == 3
    assert summary["failed"] == 2
    assert summary["passed_after_rerun"] == 1
    recovered = next(t for t in summary["tests"] if t["test_id"].endswith("test_recovers"))
    assert recovered["attempts"] == 2
    assert "rerun" in recovered["initial_outcomes"]
    events = load_events(list(output.glob("results-*.jsonl")))
    assert any(e["phase"] == "setup" and e["outcome"] == "failed" for e in events)
    assert any(e["phase"] == "teardown" and e["outcome"] == "failed" for e in events)


def test_incomplete_evidence_cannot_be_success():
    summary = summarize([{"event": "test_result", "run_id": "r", "test_id": "t",
                          "attempt": 1, "phase": "setup", "outcome": "passed"}])
    assert summary["incomplete"] == 1
    assert summary["passed"] == 0
    assert summarize([])["passed_after_rerun_rate"] is None


@pytest.mark.parametrize("phases", [("call",), ("setup", "call"), ("call", "teardown")])
def test_missing_final_phases_are_incomplete_even_after_a_passed_call(phases):
    reports = [{"event": "test_result", "run_id": "r", "test_id": "t",
                "attempt": 1, "phase": phase, "outcome": "passed"} for phase in phases]
    summary = summarize(reports)
    assert summary["incomplete"] == 1
    assert summary["passed"] == 0


def test_truncated_rerun_does_not_recover_a_previous_failure():
    reports = [{"event": "test_result", "run_id": "r", "test_id": "t",
                "attempt": 1, "phase": phase,
                "outcome": "rerun" if phase == "call" else "passed"}
               for phase in ("setup", "call", "teardown")]
    reports += [{"event": "test_result", "run_id": "r", "test_id": "t",
                 "attempt": 2, "phase": phase, "outcome": "passed"}
                for phase in ("setup", "call")]
    summary = summarize(reports)
    assert summary["incomplete"] == 1
    assert summary["passed_after_rerun"] == 0


def test_invalid_and_duplicated_evidence_is_rejected(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("not-json\n")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_events([path])
    event = {"event": "test_result", "run_id": "r", "test_id": "t", "attempt": 1,
             "phase": "call", "outcome": "passed"}
    path.write_text((json.dumps(event) + "\n") * 2)
    with pytest.raises(ValueError, match="Duplicate phase"):
        load_events([path])


def test_direct_serial_pytest_captures_nonsecret_context(tmp_path):
    environment = os.environ.copy()
    environment.pop("FRAMEWORK_CONTEXT_DIGEST", None)
    environment.update({
        "FRAMEWORK_OFFLINE": "1", "FRAMEWORK_RUN_ID": "direct-provenance-probe",
        "FRAMEWORK_RESULTS_DIR": str(tmp_path),
        "LOG_FILE": str(tmp_path / "http.jsonl"),
        "API_PASSWORD": "synthetic-secret-must-not-appear",
    })
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", "pytest-offline.ini",
         "tests/unit/test_logger_masking.py", "--basetemp", str(tmp_path / "child-tmp")],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    path = tmp_path / "provenance-direct-provenance-probe.json"
    provenance = json.loads(path.read_text())
    assert len(provenance["context_digest"]) == 64
    assert provenance["provenance_valid"]
    assert "synthetic-secret-must-not-appear" not in path.read_text()
    reports = load_events(list(tmp_path.glob("results-*.jsonl")))
    assert reports and all(r["context_digest"] == provenance["context_digest"] for r in reports)
