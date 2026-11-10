"""A stdlib-only operation service shared by the local console and MCP adapter.

Public records contain counts and fixed identifiers, never raw reports or host
paths. The subprocess runner uses an independent Python environment and a small
environment allowlist. A SQLite write transaction serializes execution across
service processes without signaling or deleting another process's resources.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.control.connections import KINDS, ConnectionFailure, Connections, Profile, execute_isolated

OPERATIONS = (
    {"id": "offline", "label": "Offline acceptance", "description": "Run controlled local tests and preserve evidence."},
    {"id": "contracts", "label": "Contract baseline", "description": "Check versioned schemas without updating them."},
    {"id": "evaluation", "label": "Response evaluation", "description": "Evaluate the supplied synthetic response sample."},
)
_OPERATION_IDS = {operation["id"] for operation in OPERATIONS} | set(KINDS)
_STATUSES = {"queued", "running", "passed", "failed", "interrupted"}
_ERRORS = {None, "command_failed", "invalid_evidence", "operation_unavailable", "execution_timeout", "service_shutdown", "previous_execution_interrupted"}
_ERRORS |= {"redirect_refused", "authentication_failed", "unexpected_http_status", "unsupported_response_encoding",
            "json_response_required", "connection_timeout", "response_too_large", "connection_request_failed",
            "response_contract_failed", "invalid_provider_catalog"}
_COUNTS = ("total", "passed", "failed", "skipped", "incomplete")


class BusyError(RuntimeError):
    """Another operation currently owns the execution lock."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _valid_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _count(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000_000:
        raise ValueError("invalid_evidence")
    return value


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid_evidence")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("invalid_evidence")
    return parsed.astimezone(UTC).isoformat()


def _clean_summary(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, dict) or summary.get("unit") not in {"tests", "checks", "records"}:
        raise ValueError("invalid_evidence")
    cleaned = {**{key: _count(summary.get(key)) for key in _COUNTS}, "unit": summary["unit"]}
    if cleaned["total"] != sum(cleaned[key] for key in _COUNTS[1:]):
        raise ValueError("invalid_evidence")
    return cleaned


def _public(record: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a record using a narrow schema, even when reading local files."""
    if not _valid_id(record.get("run_id")):
        raise ValueError("invalid_evidence")
    if record.get("operation") not in _OPERATION_IDS or record.get("status") not in _STATUSES:
        raise ValueError("invalid_evidence")
    if record.get("error_code") not in _ERRORS:
        raise ValueError("invalid_evidence")
    summary = record.get("summary")
    if summary is not None:
        summary = _clean_summary(summary)
    created = _timestamp(record.get("created_utc"))
    if created is None:
        raise ValueError("invalid_evidence")
    return {
        "run_id": record["run_id"], "operation": record["operation"], "status": record["status"],
        "created_utc": created, "finished_utc": _timestamp(record.get("finished_utc")),
        "summary": summary, "error_code": record.get("error_code"),
    }


class ControlService:
    """Run only the named local operations; no caller supplies shell arguments."""

    def __init__(
        self, project_root: Path, data_root: Path, runner_python: str = sys.executable,
        *, timeout_seconds: float = 600,
    ) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.data_root = data_root.expanduser().absolute()
        if self.data_root.is_symlink():
            raise ValueError("invalid_data_directory")
        self.data_root = self.data_root.resolve()
        if self.data_root == self.project_root or self.project_root in self.data_root.parents:
            raise ValueError("data_directory_must_be_outside_project")
        if timeout_seconds <= 0 or timeout_seconds > 3600:
            raise ValueError("invalid_timeout")
        # Preserve the venv's executable path: resolving its symlink would select
        # global Python and discard the selected environment.
        self.runner_python = str(Path(runner_python).expanduser().absolute())
        if not Path(self.runner_python).is_file() or not os.access(self.runner_python, os.X_OK):
            raise ValueError("invalid_runner_python")
        self.timeout_seconds = timeout_seconds
        self.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._database = self.data_root / ".execution.sqlite3"
        if self._database.is_symlink():
            raise ValueError("invalid_data_directory")
        self._guard = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False
        self.connections = Connections()
        try:
            connection = self._acquire()
        except BusyError:
            return
        try:
            self._reconcile()
        finally:
            connection.close()

    def _acquire(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, timeout=0, check_same_thread=False)
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            connection.close()
            raise BusyError("execution_in_progress") from exc
        return connection

    def capabilities(self) -> dict[str, Any]:
        return {"name": "API Testing Framework", "version": 2, "offline_only": False,
                "max_concurrent_runs": 1, "operations": [dict(item) for item in OPERATIONS],
                "connection_operations": list(KINDS), "credential_storage": "process_memory"}

    def connection_status(self) -> dict[str, Any]:
        return self.connections.status()

    def _directory(self, run_id: str) -> Path:
        if not _valid_id(run_id):
            raise ValueError("invalid_run_id")
        directory = self.data_root / run_id
        if directory.is_symlink() or directory.resolve().parent != self.data_root:
            raise ValueError("invalid_run_id")
        return directory

    def _read(self, run_id: str) -> dict[str, Any]:
        path = self._directory(run_id) / "state.json"
        if path.is_symlink() or not path.is_file():
            raise KeyError("unknown_run")
        if path.stat().st_size > 16_384:
            raise ValueError("invalid_evidence")
        record = _public(json.loads(path.read_text(encoding="utf-8")))
        if record["run_id"] != run_id:
            raise ValueError("invalid_evidence")
        return record

    def _write(self, record: dict[str, Any]) -> None:
        directory = self._directory(record["run_id"])
        path = directory / "state.json"
        if path.is_symlink():
            raise ValueError("invalid_evidence")
        temporary = directory / f"state-{uuid.uuid4()}.tmp"
        temporary.write_text(json.dumps(_public(record), indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _reconcile(self) -> None:
        # Called only while holding the database execution lock. A crashed
        # owner's transaction is released by SQLite; a live owner keeps it.
        for record in self.list_runs():
            if record["status"] in {"queued", "running"}:
                record.update(status="interrupted", finished_utc=_now(), error_code="previous_execution_interrupted")
                self._write(record)

    def list_runs(self) -> list[dict[str, Any]]:
        records = []
        for directory in self.data_root.iterdir():
            if not _valid_id(directory.name) or directory.is_symlink() or not directory.is_dir():
                continue
            try:
                records.append(self._read(directory.name))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(records, key=lambda record: record["created_utc"], reverse=True)[:200]

    def get_run(self, run_id: str) -> dict[str, Any]:
        try:
            return self._read(run_id)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("invalid_evidence") from exc

    def start_run(self, operation: str) -> dict[str, Any]:
        if not isinstance(operation, str) or operation not in _OPERATION_IDS:
            raise ValueError("invalid_operation")
        with self._guard:
            if self._closed:
                raise RuntimeError("service_closed")
            profile = self.connections.snapshot(operation) if operation in KINDS else None
            connection = self._acquire()
            try:
                self._reconcile()
                run_id = str(uuid.uuid4())
                self._directory(run_id).mkdir(mode=0o700)
                record = {"run_id": run_id, "operation": operation, "status": "running",
                          "created_utc": _now(), "finished_utc": None, "summary": None, "error_code": None}
                self._write(record)
                self._thread = threading.Thread(target=self._execute, args=(record, connection, profile), daemon=True)
                self._thread.start()
            except BaseException:
                connection.close()
                raise
            return _public(record)

    def _command(self, operation: str, directory: Path) -> list[str]:
        scripts = self.project_root / "scripts"
        if operation == "offline":
            return [self.runner_python, str(scripts / "run_offline.py"), "--output", str(directory / "evidence")]
        if operation == "contracts":
            return [self.runner_python, str(scripts / "check_contracts.py")]
        return [self.runner_python, str(scripts / "evaluate_responses.py"),
                "--config", str(self.project_root / "fixtures/evaluation/config.json"),
                "--input", str(self.project_root / "fixtures/evaluation/synthetic_responses.jsonl"),
                "--output", str(directory / "evidence")]

    def _environment(self, directory: Path) -> dict[str, str]:
        retained = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "SystemRoot", "LANG", "LC_ALL")
        environment = {key: os.environ[key] for key in retained if key in os.environ}
        environment.update({"FRAMEWORK_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                            "TMPDIR": str(directory / "tmp"), "TMP": str(directory / "tmp"),
                            "TEMP": str(directory / "tmp"), "NO_PROXY": "127.0.0.1,localhost",
                            "no_proxy": "127.0.0.1,localhost"})
        return environment

    def _summary(self, operation: str, directory: Path, exit_code: int) -> dict[str, Any]:
        if operation == "contracts":
            return {"total": 1, "passed": int(exit_code == 0), "failed": int(exit_code != 0),
                    "skipped": 0, "incomplete": 0, "unit": "checks"}
        filename = "summary.json" if operation == "offline" else "evaluation.json"
        path = directory / "evidence" / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8_000_000:
            raise ValueError("invalid_evidence")
        result = json.loads(path.read_text(encoding="utf-8"))
        if operation == "offline":
            return {**{key: _count(result.get(key)) for key in _COUNTS}, "unit": "tests"}
        total, failed = _count(result.get("total_records")), _count(result.get("failed_records"))
        if failed > total:
            raise ValueError("invalid_evidence")
        return {"total": total, "passed": total - failed, "failed": failed,
                "skipped": 0, "incomplete": 0, "unit": "records"}

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait(timeout=2)

    def _execute(self, record: dict[str, Any], connection: sqlite3.Connection, profile: Profile | None = None) -> None:
        process = None
        try:
            directory = self._directory(record["run_id"])
            (directory / "tmp").mkdir()
            if self._stop.is_set():
                record.update(status="interrupted", error_code="service_shutdown")
                return
            if profile is not None:
                execute_isolated(profile, self._stop, min(10, self.timeout_seconds))
                if self._stop.is_set():
                    record.update(status="interrupted", error_code="service_shutdown")
                    return
                record.update(status="passed", error_code=None,
                              summary={"total": 1, "passed": 1, "failed": 0, "skipped": 0,
                                       "incomplete": 0, "unit": "checks"})
                return
            with (directory / "operation.log").open("wb") as log:
                process = subprocess.Popen(self._command(record["operation"], directory),
                                           cwd=self.project_root, env=self._environment(directory),
                                           stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=os.name == "posix")
                started = time.monotonic()
                while process.poll() is None:
                    if self._stop.wait(0.05):
                        self._terminate(process)
                        record.update(status="interrupted", error_code="service_shutdown")
                        return
                    if time.monotonic() - started > self.timeout_seconds:
                        self._terminate(process)
                        record.update(status="failed", error_code="execution_timeout")
                        return
            record["summary"] = _clean_summary(self._summary(record["operation"], directory, process.returncode))
            summary = record["summary"]
            passed = process.returncode == 0 and summary["passed"] > 0 and summary["failed"] == 0 and summary["incomplete"] == 0
            record.update(status="passed" if passed else "failed", error_code=None if passed else "command_failed")
        except ConnectionFailure as exc:
            record.update(status="interrupted" if str(exc) == "service_shutdown" else "failed", error_code=str(exc),
                          summary={"total": 1, "passed": 0, "failed": 1, "skipped": 0,
                                   "incomplete": 0, "unit": "checks"})
        except (OSError, ValueError, KeyError, TypeError):
            record.update(status="failed", error_code="invalid_evidence" if process is not None else "operation_unavailable")
        finally:
            if process is not None and process.poll() is None:
                self._terminate(process)
            record["finished_utc"] = _now()
            try:
                self._write(record)
            finally:
                connection.close()

    def close(self) -> None:
        with self._guard:
            self._closed = True
            self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=10)
        self.connections.disconnect("all")
