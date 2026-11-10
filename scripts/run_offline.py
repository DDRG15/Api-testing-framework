"""Run isolated tests against fakes/loopback services and preserve reviewable evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.utils.run_context import capture_context, source_hashes  # noqa: E402
from src.utils.test_results import load_events, markdown_summary, summarize  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    started = datetime.now(UTC)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    run_id = str(uuid.uuid4())
    output = (args.output or Path.home() / "sandbox/enterprise-api-testing-framework/runs"
              / f"{stamp}-{run_id[:8]}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "tmp").mkdir()
    env = os.environ.copy()
    env.update({
        "FRAMEWORK_OFFLINE": "1", "FRAMEWORK_RUN_ID": run_id,
        "FRAMEWORK_RUN_STARTED_UTC": started.isoformat(),
        "FRAMEWORK_ENVIRONMENT": "offline-synthetic",
        "FRAMEWORK_RESULTS_DIR": str(output),
        "LOG_FILE": str(output / "logs/http.jsonl"),
        "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(output / "tmp"),
        "COVERAGE_FILE": str(output / ".coverage"),
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        "REQUEST_CONNECT_TIMEOUT": "0.1", "REQUEST_READ_TIMEOUT": "0.3",
        "SLO_RESPONSE_TIME_MS": "3000", "RETRY_MAX_ATTEMPTS": "3",
        "RETRY_BASE_DELAY_SECONDS": "0.001", "RETRY_MAX_DELAY_SECONDS": "0.005",
    })
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              text=True, capture_output=True)
    env["FRAMEWORK_REVISION"] = revision.stdout.strip() if revision.returncode == 0 else "unversioned"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            text=True, capture_output=True)
    extra = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    config_keys = (
        "REQUEST_CONNECT_TIMEOUT", "REQUEST_READ_TIMEOUT", "RETRY_MAX_ATTEMPTS",
        "RETRY_BASE_DELAY_SECONDS", "RETRY_MAX_DELAY_SECONDS", "SLO_RESPONSE_TIME_MS",
        "CIRCUIT_BREAKER_FAILURE_THRESHOLD", "CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS",
        "API_VERSION", "SSL_CA_BUNDLE", "LOG_LEVEL",
    )
    # No credentials, raw target URLs or certificates are copied into provenance.
    configuration = {key: env.get(key, "default") for key in config_keys}
    configuration["SSL_CA_BUNDLE"] = hashlib.sha256(configuration["SSL_CA_BUNDLE"].encode()).hexdigest()
    configuration["target"] = "offline-loopback"
    configuration["redis"] = "disabled-offline"
    context = capture_context(ROOT, env["FRAMEWORK_ENVIRONMENT"], extra, configuration)
    env["FRAMEWORK_CONTEXT_DIGEST"] = context["context_digest"]
    command = [sys.executable, "-m", "pytest", "-c", "pytest-offline.ini",
               "--basetemp", str(output / "pytest-tmp"),
               "--junitxml", str(output / "junit.xml"),
               "--html", str(output / "report.html"), "--self-contained-html",
               "--cov=src", "--cov=config", "--cov-branch", "--cov-fail-under=0",
               f"--cov-report=xml:{output / 'coverage.xml'}", "--cov-report=term-missing", *extra]
    with (output / "pytest.log").open("w", encoding="utf-8") as stream:
        completed = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    paths = list(output.glob("results-*.jsonl"))
    changed_during_run = source_hashes(ROOT) != context["source_sha256"]
    if changed_during_run:
        # Do not classify a moving source tree as comparable historical evidence.
        for path in paths:
            records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            for record in records:
                record["context_digest"] = None
                record["source_changed_during_run"] = True
            path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))
    summary = summarize(load_events(paths))
    summary["pytest_exit_code"] = completed.returncode
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output / "summary.md").write_text(markdown_summary(summary), encoding="utf-8")
    manifest = {
        **context,
        "run_id": run_id, "created_utc": stamp, "revision": env["FRAMEWORK_REVISION"],
        "run_started_utc": env["FRAMEWORK_RUN_STARTED_UTC"],
        "source_changed_during_run": changed_during_run,
        "provenance_valid": not changed_during_run,
        "working_tree_dirty": bool(status.stdout.strip()), "python": sys.version,
        "pytest_exit_code": completed.returncode, "command": command,
        "coverage_policy": "Offline measured separately; full-suite 80% gate unchanged.",
        "artifacts": {
            str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.iterdir()) if p.is_file()
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Artifacts: {output}")
    print(f"Tests: {summary['total']}; passed: {summary['passed']}; "
          f"failed: {summary['failed']}; skipped: {summary['skipped']}; exit: {completed.returncode}")
    if completed.returncode or not summary["total"]:
        print((output / "pytest.log").read_text(encoding="utf-8")[-7000:])
    return completed.returncode or int(not summary["total"] or summary["incomplete"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
