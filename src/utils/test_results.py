"""Phase-aware pytest evidence and conservative retry summaries. No quarantine decisions."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def report_event(report: Any, context: dict[str, Any]) -> dict[str, Any]:
    return {
        **context, "event": "test_result", "test_id": report.nodeid,
        "phase": report.when, "outcome": report.outcome,
        "attempt": getattr(report, "rerun", 0) + 1,
        "duration_s": round(report.duration, 6),
        "worker_id": getattr(report, "worker_id", "master"),
        "expected_failure": hasattr(report, "wasxfail"),
    }


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("event") == "test_result":
            grouped[(event["run_id"], event["test_id"])].append(event)
    tests = []
    for (run_id, test_id), reports in sorted(grouped.items()):
        latest = max(r["attempt"] for r in reports)
        final = [r for r in reports if r["attempt"] == latest]
        outcomes = {r["outcome"] for r in final}
        if "failed" in outcomes:
            result = "failed"
        elif "skipped" in outcomes:
            result = "skipped"
        elif ({r["phase"] for r in final} == {"setup", "call", "teardown"}
              and outcomes == {"passed"}):
            result = "passed"
        else:
            result = "incomplete"
        recovered = result == "passed" and any(r["outcome"] == "rerun" for r in reports)
        tests.append({
            "run_id": run_id, "test_id": test_id, "result": result,
            "attempts": latest, "passed_after_rerun": recovered,
            "initial_outcomes": [r["outcome"] for r in reports if r["attempt"] == 1],
            "expected_failure": any(r.get("expected_failure", False) for r in reports),
            "environment": reports[0].get("environment", "unknown"),
            "revision": reports[0].get("revision", "unknown"),
            "contract_digest": reports[0].get("contract_digest", "unknown"),
        })
    recovered_count = sum(t["passed_after_rerun"] for t in tests)
    return {
        "total": len(tests),
        "passed": sum(t["result"] == "passed" for t in tests),
        "failed": sum(t["result"] == "failed" for t in tests),
        "skipped": sum(t["result"] == "skipped" for t in tests),
        "incomplete": sum(t["result"] == "incomplete" for t in tests),
        "passed_after_rerun": recovered_count,
        "passed_after_rerun_rate": recovered_count / len(tests) if tests else None,
        "note": "Recovered reruns signal instability; they are not proven false positives.",
        "tests": tests,
    }


def load_events(paths: list[Path]) -> list[dict[str, Any]]:
    events = []
    seen = set()
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON evidence: {path}:{number}") from exc
            if event.get("event") != "test_result":
                continue
            key = (event["run_id"], event["test_id"], event["attempt"], event["phase"])
            if key in seen:
                raise ValueError(f"Duplicate phase evidence: {path}:{number}")
            seen.add(key)
            events.append(event)
    return events


def markdown_summary(summary: dict[str, Any]) -> str:
    lines = ["# Test evidence", "", f"Tests: {summary['total']}; passed: {summary['passed']}; "
             f"failed: {summary['failed']}; skipped: {summary['skipped']}; "
             f"incomplete: {summary['incomplete']}", "",
             f"Passed after rerun: {summary['passed_after_rerun']}", "", summary["note"], "",
             "| Test | Final | Attempts | Recovered rerun |", "|---|---|---:|---|"]
    for test in summary["tests"]:
        label = test["test_id"].replace("|", "\\|")
        lines.append(f"| {label} | {test['result']} | {test['attempts']} | "
                     f"{test['passed_after_rerun']} |")
    return "\n".join(lines) + "\n"
