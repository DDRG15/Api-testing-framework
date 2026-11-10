"""Comparable-run history reports from phase evidence, without quarantine decisions."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.test_results import load_events, summarize

_PHASES = {"setup", "call", "teardown"}
_OUTCOMES = {"passed", "failed", "skipped", "rerun"}
_CONTEXT_KEYS = ("context_digest", "environment", "revision", "contract_digest")


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("run_started_utc must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("run_started_utc must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("run_started_utc must include its timezone")
    return parsed


def _validate(events: list[dict[str, Any]]) -> None:
    seen = set()
    for event in events:
        if not isinstance(event, dict) or event.get("event") != "test_result":
            raise ValueError("Expected phase evidence with event=test_result")
        if any(not isinstance(event.get(key), str) or not event[key] for key in ("run_id", "test_id")):
            raise ValueError("Each phase needs nonempty run_id and test_id strings")
        attempt = event.get("attempt")
        if type(attempt) is not int or attempt < 1:
            raise ValueError("Each phase needs a positive integer attempt")
        if event.get("phase") not in _PHASES or event.get("outcome") not in _OUTCOMES:
            raise ValueError("Unrecognized phase or outcome")
        duration = event.get("duration_s", 0)
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            raise ValueError("Phase duration must be finite and nonnegative")
        for key in _CONTEXT_KEYS:
            if event.get(key) is not None and not isinstance(event[key], str):
                raise ValueError(f"{key} must be a string when supplied")
        _timestamp(event.get("run_started_utc"))
        phase_key = (event["run_id"], event["test_id"], attempt, event["phase"])
        if phase_key in seen:
            raise ValueError("Duplicate phase evidence")
        seen.add(phase_key)


def build_history(
    events: list[dict[str, Any]], *, min_runs: int = 10, min_switches: int = 3,
) -> dict[str, Any]:
    """Compare only verified contexts, retaining unknown provenance as separate rows.

    Thresholds are review heuristics. They do not establish a defect or a false
    positive. Missing or tied timestamps prevent cross-run classification.
    """
    if type(min_runs) is not int or min_runs < 2:
        raise ValueError("min_runs must be an integer of at least 2")
    if type(min_switches) is not int or min_switches < 1:
        raise ValueError("min_switches must be a positive integer")
    if not events:
        raise ValueError("No test phase evidence was supplied")
    _validate(events)
    runs: dict[str, dict[str, Any]] = {}
    for event in events:
        metadata = {key: event.get(key) for key in _CONTEXT_KEYS}
        metadata["run_started_utc"] = event.get("run_started_utc")
        run_id = event["run_id"]
        if run_id in runs and any(runs[run_id].get(key) != value for key, value in metadata.items()):
            raise ValueError(f"Conflicting provenance within run {run_id!r}")
        runs.setdefault(run_id, {"run_id": run_id, **metadata, "input_order": len(runs)})
    chronological = all(_timestamp(run["run_started_utc"]) is not None for run in runs.values())
    ordered = list(runs.values())
    if chronological:
        ordered.sort(key=lambda run: (_timestamp(run["run_started_utc"]), run["input_order"]))
    run_positions = {run["run_id"]: index for index, run in enumerate(ordered)}
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for result in summarize(events)["tests"]:
        metadata = runs[result["run_id"]]
        digest = metadata.get("context_digest")
        verified = isinstance(digest, str) and bool(digest.strip()) and digest not in {"unknown", "unverified"}
        context = tuple(str(metadata.get(key) or "unknown") for key in _CONTEXT_KEYS)
        # Never combine different unverified runs, even if their labels match.
        group = (result["test_id"], *context) if verified else (result["test_id"], "unverified", result["run_id"])
        grouped[group].append({**result, **{key: metadata[key] for key in _CONTEXT_KEYS},
                               "run_started_utc": metadata["run_started_utc"],
                               "context_verified": verified})
    rows = []
    for group, results in sorted(grouped.items()):
        results.sort(key=lambda result: run_positions[result["run_id"]])
        verified = results[0]["context_verified"]
        binary = [r for r in results if r["result"] in {"passed", "failed"} and not r["expected_failure"]]
        times = [_timestamp(r["run_started_utc"]) for r in results]
        chronology_verified = all(times) and len(set(times)) == len(times)
        switches = 0
        previous = None
        for result in results:
            outcome = result["result"]
            if outcome not in {"passed", "failed"} or result["expected_failure"]:
                previous = None
                continue
            if previous is not None and previous != outcome:
                switches += 1
            previous = outcome
        if not verified:
            status = "unverified_context"
        elif not chronology_verified:
            status = "unverified_chronology"
        elif len(binary) < min_runs:
            status = "insufficient_history"
        elif switches >= min_switches:
            status = "candidate_for_review"
        else:
            status = "no_pattern_detected"
        rows.append({
            "test_id": group[0], "context_digest": results[0].get("context_digest"),
            "environment": results[0].get("environment"), "revision": results[0].get("revision"),
            "contract_digest": results[0].get("contract_digest"), "context_verified": verified,
            "chronology_verified": bool(chronology_verified), "sample_count": len(binary),
            "observed_runs": len(results), "switches": switches if verified and chronology_verified else None,
            "review_status": status,
            "recovered_reruns": sum(r["passed_after_rerun"] for r in results),
            "results": results,
        })
    return {
        "schema_version": 1, "runs": ordered, "rows": rows,
        "thresholds": {"min_runs": min_runs, "min_switches": min_switches},
        "ordering": "run_started_utc" if chronological else "supplied_input_order",
        "candidate_count": sum(row["review_status"] == "candidate_for_review" for row in rows),
        "note": "Candidates require human review. Recovered reruns are instability signals, not proven false positives. No automatic quarantine is performed.",
    }


def render_history_html(history: dict[str, Any]) -> str:
    """Render accessible text/color cells and safely embedded, payload-free details."""
    run_ids = [run["run_id"] for run in history["runs"]]
    headers = "".join(f'<th scope="col" title="{html.escape(run_id, quote=True)}">Run {i + 1}</th>'
                      for i, run_id in enumerate(run_ids))
    cells: list[dict[str, Any]] = []
    rows = []
    for row in history["rows"]:
        result_by_run = {result["run_id"]: result for result in row["results"]}
        entries = []
        for run_id in run_ids:
            result = result_by_run.get(run_id)
            if result is None:
                entries.append('<td class="absent" aria-label="Test not observed in this run">—</td>')
                continue
            index = len(cells)
            details = {**result, "review_status": row["review_status"],
                       "comparable_sample_count": row["sample_count"], "switches": row["switches"]}
            cells.append(details)
            recovered = result["passed_after_rerun"]
            label = "pass after rerun" if recovered else result["result"]
            css = "recovered" if recovered else result["result"]
            aria = html.escape(f"{row['test_id']}, {run_id}: {label}. Show evidence.", quote=True)
            entries.append(f'<td><button type="button" class="cell {css}" data-cell="{index}" aria-label="{aria}">{label}</button></td>')
        context = html.escape(str(row["context_digest"] or "unverified"))
        status = html.escape(row["review_status"].replace("_", " "))
        rows.append(f'<tr><th scope="row">{html.escape(row["test_id"])}<small>Context: {context}<br>{status} · {row["sample_count"]} comparable outcomes</small></th>{"".join(entries)}</tr>')
    payload = json.dumps(cells, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Test history</title>
<style>:root{{color-scheme:dark}}body{{font:14px/1.5 system-ui,sans-serif;background:#10151d;color:#e6edf3;margin:24px}}h1{{margin-bottom:8px}}.scroll{{overflow:auto;max-height:70vh}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #405066;padding:8px;text-align:left}}thead th{{position:sticky;top:0;background:#1b2533}}small{{display:block;max-width:440px;overflow-wrap:anywhere;color:#b6c3d3}}button{{font:inherit;color:inherit;cursor:pointer}}.cell{{width:100%;min-width:100px;border:1px solid #8090a3;border-radius:4px;padding:8px}}.passed{{background:#164b35}}.failed{{background:#712c36}}.skipped{{background:#414957}}.incomplete{{background:#644613}}.recovered{{background:#593a79}}.absent{{text-align:center;color:#9eaabd}}button:focus-visible{{outline:3px solid #58a6ff;outline-offset:2px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid #405066;padding:16px}}a{{color:#79b8ff}}</style></head>
<body><h1>Test history</h1><p>{html.escape(history['note'])}</p><p>{len(history['runs'])} runs · {len(history['rows'])} test/context rows · {history['candidate_count']} review candidates. Minimum: {history['thresholds']['min_runs']} comparable outcomes and {history['thresholds']['min_switches']} switches.</p>
<p>Ordering: {html.escape(history['ordering'])}. Contexts are evaluated separately. Missing provenance or chronology prevents cross-run classification. Gray dashes mean no observation, not a passing test. <a href="history.csv">Download CSV</a></p>
<div class="scroll"><table><caption>Final outcomes by test, verified context and run. Activate a cell for evidence.</caption><thead><tr><th scope="col">Test and context</th>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Selected evidence</h2><pre id="details" role="status" aria-live="polite">Select an outcome cell to inspect its run, attempts and provenance.</pre>
<script id="evidence" type="application/json">{payload}</script><script>const evidence=JSON.parse(document.getElementById('evidence').textContent);for(const button of document.querySelectorAll('[data-cell]')){{button.addEventListener('click',()=>{{document.getElementById('details').textContent=JSON.stringify(evidence[Number(button.dataset.cell)],null,2);}});}}</script></body></html>'''


def _csv_value(value: Any) -> str:
    text = str(value) if value is not None else ""
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def write_history_report(
    inputs: list[Path], output: Path, *, min_runs: int = 10, min_switches: int = 3,
) -> dict[str, Any]:
    """Validate evidence before creating a new report directory; never overwrite."""
    try:
        events = load_events(inputs)
    except (AttributeError, KeyError, TypeError) as exc:
        raise ValueError("Invalid phase evidence structure") from exc
    history = build_history(events, min_runs=min_runs, min_switches=min_switches)
    history["inputs"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                         for path in inputs]
    output.mkdir(parents=True, exist_ok=False)
    (output / "history.json").write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    (output / "history.html").write_text(render_history_html(history), encoding="utf-8")
    columns = ["run_id", "run_started_utc", "test_id", "result", "attempts", "passed_after_rerun",
               "environment", "revision", "contract_digest", "context_digest", "review_status", "sample_count", "switches"]
    with (output / "history.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in history["rows"]:
            for result in row["results"]:
                record = {**result, **{key: row[key] for key in ("review_status", "sample_count", "switches")}}
                writer.writerow(_csv_value(record.get(column)) for column in columns)
    return history
