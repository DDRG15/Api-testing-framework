"""Measure four seeded client defects in a temporary source copy, never in the checkout."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = {
    "unsafe_post_replay": (
        "return method.upper() in IDEMPOTENT_METHODS or retry_safe", "return True"),
    "retry_logic_error": (
        "frozenset({429, 502, 503, 504})", "frozenset({400, 429, 502, 503, 504})"),
    "breaker_bypassed": (
        "with self._cb:", "with __import__('contextlib').nullcontext():"),
    "missing_correlation_id": (
        "[correlation_id={cid}]", "[request_id=removed]"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (args.output or Path.home() / "sandbox/enterprise-api-testing-framework/mutations"
              / str(uuid.uuid4())).resolve()
    output.mkdir(parents=True, exist_ok=False)
    results = []
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory(prefix="source-", dir=output) as temporary:
        copy = Path(temporary)
        for directory in ("src", "config", "tests", "scripts", "fixtures"):
            shutil.copytree(ROOT / directory, copy / directory,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("conftest.py", "pytest-offline.ini", "pyproject.toml"):
            shutil.copy2(ROOT / name, copy / name)
        target = copy / "src/client/base_client.py"
        original = target.read_text(encoding="utf-8")
        for name, mutation in [("baseline", None), *MUTATIONS.items()]:
            if mutation is not None:
                before, after = mutation
                if before not in original:
                    raise RuntimeError(f"Mutation anchor missing: {name}")
                target.write_text(original.replace(before, after), encoding="utf-8")
            run_output = output / name
            completed = subprocess.run(
                [sys.executable, "scripts/run_offline.py", "--output", str(run_output), "--",
                 "tests/unit/test_retry_and_breaker.py", "tests/offline/test_retry_policy.py"],
                cwd=copy, env=env, text=True, capture_output=True, timeout=90,
            )
            summary_path = run_output / "summary.json"
            summary = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
            valid_run = summary.get("total", 0) > 0 and not summary.get("incomplete", 0)
            # An import/collection failure or a timeout never counts as a killed mutation.
            killed = name != "baseline" and completed.returncode == 1 and valid_run and summary.get("failed", 0) > 0
            passed_baseline = name == "baseline" and completed.returncode == 0 and valid_run
            results.append({"name": name, "exit_code": completed.returncode,
                            "tests": summary.get("total", 0), "failures": summary.get("failed", 0),
                            "killed": bool(killed), "baseline_passed": bool(passed_baseline)})
            print(f"{name}: exit={completed.returncode}, failures={summary.get('failed', 0)}")
            if name == "baseline" and not passed_baseline:
                break
    success = len(results) == 5 and results[0]["baseline_passed"] and all(r["killed"] for r in results[1:])
    (output / "mutations.json").write_text(json.dumps({
        "success": success, "scope": "Four seeded client mutations, not exhaustive mutation coverage",
        "results": results,
    }, indent=2) + "\n")
    print(f"Mutation evidence: {output}")
    return int(not success)


if __name__ == "__main__":
    raise SystemExit(main())
