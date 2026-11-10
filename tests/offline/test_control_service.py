from __future__ import annotations

import http.client
import json
import sys
import threading
import time
import uuid
from datetime import UTC, datetime

import pytest

from src.control.http_server import ConsoleServer
from src.control.service import BusyError, ControlService


@pytest.fixture
def control(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "docs").mkdir()
    (project / "docs/architecture.html").write_text("<h1>Public architecture</h1>")
    (project / "scripts/check_contracts.py").write_text(
        "import os\nassert 'SYNTHETIC_PRIVATE_ENV' not in os.environ\n"
        "print('PRIVATE_OUTPUT_NOT_FOR_API')\n"
    )
    (project / "scripts/run_offline.py").write_text(
        "import json,sys\nfrom pathlib import Path\np=Path(sys.argv[2]);p.mkdir()\n"
        "(p/'summary.json').write_text(json.dumps({'total':3,'passed':3,'failed':0,"
        "'skipped':0,'incomplete':0,'tests':[{'test_id':'PRIVATE_TEST_IDENTIFIER'}]}))\n"
    )
    (project / "scripts/evaluate_responses.py").write_text(
        "import json,sys\nfrom pathlib import Path\np=Path(sys.argv[-1]);p.mkdir()\n"
        "(p/'evaluation.json').write_text(json.dumps({'total_records':4,'failed_records':1,"
        "'groups':[{'model_id':'PRIVATE_MODEL_IDENTIFIER'}]}))\nraise SystemExit(1)\n"
    )
    monkeypatch.setenv("SYNTHETIC_PRIVATE_ENV", "must_not_reach_child")
    service = ControlService(project, tmp_path / "data", sys.executable)
    try:
        yield service
    finally:
        service.close()


def wait_done(service, run_id):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        record = service.get_run(run_id)
        if record["status"] not in {"queued", "running"}:
            return record
        time.sleep(0.01)
    pytest.fail("Local fixture operation did not finish")


@pytest.mark.parametrize("operation,total,failed,unit", [
    ("contracts", 1, 0, "checks"), ("offline", 3, 0, "tests"),
    ("evaluation", 4, 1, "records"),
])
def test_fixed_commands_return_only_sanitized_counts(control, operation, total, failed, unit):
    record = wait_done(control, control.start_run(operation)["run_id"])
    assert record["status"] == ("failed" if failed else "passed")
    assert record["summary"] == {"total": total, "passed": total - failed, "failed": failed,
                                 "skipped": 0, "incomplete": 0, "unit": unit}
    exported = json.dumps(control.list_runs())
    assert "PRIVATE_" not in exported
    assert str(control.project_root) not in exported
    assert str(control.data_root) not in exported
    restored = ControlService(control.project_root, control.data_root, sys.executable)
    try:
        assert restored.get_run(record["run_id"]) == record
    finally:
        restored.close()


def test_two_service_process_owners_share_a_single_execution_slot(control):
    (control.project_root / "scripts/check_contracts.py").write_text("import time\ntime.sleep(2)\n")
    first = control.start_run("contracts")
    second = ControlService(control.project_root, control.data_root, sys.executable)
    try:
        with pytest.raises(BusyError, match="execution_in_progress"):
            second.start_run("contracts")
        assert second.get_run(first["run_id"])["status"] == "running"
        second.close()  # Closing another adapter does not cancel the owner.
        assert control.get_run(first["run_id"])["status"] == "running"
        control.close()
        assert control.get_run(first["run_id"])["status"] == "interrupted"
    finally:
        second.close()


def test_timeout_stops_owned_process_and_releases_execution_slot(control):
    (control.project_root / "scripts/check_contracts.py").write_text("import time\ntime.sleep(30)\n")
    control.timeout_seconds = 0.1
    record = wait_done(control, control.start_run("contracts")["run_id"])
    assert record["status"] == "failed"
    assert record["error_code"] == "execution_timeout"
    (control.project_root / "scripts/check_contracts.py").write_text("pass\n")
    assert wait_done(control, control.start_run("contracts")["run_id"])["status"] == "passed"


def test_zero_exit_with_incomplete_evidence_cannot_be_green(control):
    path = control.project_root / "scripts/run_offline.py"
    path.write_text(path.read_text().replace("'passed':3", "'passed':2").replace("'incomplete':0", "'incomplete':1"))
    record = wait_done(control, control.start_run("offline")["run_id"])
    assert record["status"] == "failed"
    assert record["summary"]["incomplete"] == 1


def test_inconsistent_counts_fail_instead_of_leaving_an_active_record(control):
    path = control.project_root / "scripts/run_offline.py"
    path.write_text(path.read_text().replace("'passed':3", "'passed':300"))
    record = wait_done(control, control.start_run("offline")["run_id"])
    assert record["status"] == "failed"
    assert record["error_code"] == "invalid_evidence"
    assert record["summary"] is None


def test_invalid_operations_paths_and_symlink_records_are_rejected(control, tmp_path):
    for operation in ("live", "offline;echo injected", "--update"):
        with pytest.raises(ValueError, match="invalid_operation"):
            control.start_run(operation)
    with pytest.raises(ValueError, match="invalid_run_id"):
        control.get_run("../../outside")
    with pytest.raises(KeyError, match="unknown_run"):
        control.get_run(str(uuid.uuid4()))
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = control.data_root / str(uuid.uuid4())
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="invalid_run_id"):
        control.get_run(linked.name)
    assert control.list_runs() == []
    with pytest.raises(ValueError, match="outside_project"):
        ControlService(control.project_root, control.project_root / "outputs", sys.executable)


def test_recovery_marks_unowned_running_records_interrupted(control):
    run_id = str(uuid.uuid4())
    directory = control.data_root / run_id
    directory.mkdir()
    record = {"run_id": run_id, "operation": "contracts", "status": "running",
              "created_utc": datetime.now(UTC).isoformat(), "finished_utc": None,
              "summary": None, "error_code": None, "raw_private_data": "MUST_NOT_EXPORT"}
    (directory / "state.json").write_text(json.dumps(record))
    recovered = ControlService(control.project_root, control.data_root, sys.executable)
    try:
        result = recovered.get_run(run_id)
        assert result["status"] == "interrupted"
        assert result["error_code"] == "previous_execution_interrupted"
        assert "MUST_NOT_EXPORT" not in json.dumps(result)
    finally:
        recovered.close()


@pytest.fixture
def console(control, tmp_path):
    assets = tmp_path / "assets"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text('<html><h1>Test console</h1></html>')
    (assets / "assets/app.js").write_text("console.log('public asset');")
    (assets / "secret.txt").write_text("PRIVATE_FILE")
    server = ConsoleServer(control, assets)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(server, method, path, *, token=True, origin=True, body=None, extra=None):
    headers = {}
    if token:
        headers["X-Console-Token"] = server.token
    if origin:
        headers["Origin"] = server.origin
    if body is not None:
        headers["Content-Type"] = "application/json"
    headers.update(extra or {})
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_http_authentication_origin_and_host_boundaries(console):
    assert request(console, "GET", "/api/runs", token=False)[0] == 401
    assert request(console, "GET", "/api/runs", extra={"X-Console-Token": "invalid-ÿ"})[0] == 401
    assert request(console, "GET", "/api/runs", extra={"Host": "attacker.invalid"})[0] == 403
    assert request(console, "POST", "/api/runs", origin=False, body='{"operation":"contracts"}')[0] == 403
    assert request(console, "POST", "/api/runs", body='{"operation":"contracts"}', extra={"Origin": "https://attacker.invalid"})[0] == 403
    status, headers, payload = request(console, "GET", "/api/capabilities")
    assert status == 200 and json.loads(payload)["credential_storage"] == "process_memory"
    assert "Access-Control-Allow-Origin" not in headers
    assert headers["Cache-Control"] == "no-store"


def test_http_runs_work_without_exposing_evidence_files(console):
    status, _, payload = request(console, "POST", "/api/runs", body='{"operation":"contracts"}')
    assert status == 202
    record = wait_done(console.service, json.loads(payload)["run_id"])
    status, _, payload = request(console, "GET", f'/api/runs/{record["run_id"]}')
    assert status == 200 and json.loads(payload)["status"] == "passed"
    assert request(console, "GET", "/")[0] == 200
    assert request(console, "GET", "/architecture")[0] == 200
    for path in ("/secret.txt", "/NOTES.md", "/../secret.txt", "/assets/../../secret.txt", "/api/runs/../../outside", "/api/runs?token=wrong"):
        assert request(console, "GET", path)[0] == 404
    status, _, payload = request(console, "GET", "/api/runs")
    assert status == 200
    assert "PRIVATE_OUTPUT" not in payload.decode()


@pytest.mark.parametrize("body", ['{"operation":"live"}', '{"operation":"contracts","args":["--update"]}', '[]', 'invalid'])
def test_http_rejects_arbitrary_operations_and_arguments(console, body):
    status, _, payload = request(console, "POST", "/api/runs", body=body)
    assert status == 400 and json.loads(payload)["error"] == "invalid_operation"


def test_connection_routes_keep_credentials_out_of_responses_and_require_origin(console):
    secret = "synthetic-http-session-secret"
    body = json.dumps({"secret": secret})
    assert request(console, "GET", "/api/connections", token=False)[0] == 401
    assert request(console, "POST", "/api/connections/openai", origin=False, body=body)[0] == 403
    code, _, payload = request(console, "POST", "/api/connections/openai", body=body)
    assert code == 200 and secret not in payload.decode()
    code, _, payload = request(console, "GET", "/api/connections")
    assert code == 200 and json.loads(payload)["connections"][1]["configured"]
    assert secret not in payload.decode()
    assert request(console, "POST", "/api/connections/disconnect", body='{"kind":"all"}')[0] == 200
    assert not any(item["configured"] for item in console.service.connection_status()["connections"])


def test_connection_routes_reject_url_override_and_do_not_reflect_invalid_secrets(console):
    body = json.dumps({"secret": "synthetic-sensitive-value", "url": "https://example.com/"})
    code, _, payload = request(console, "POST", "/api/connections/openai", body=body)
    assert code == 400 and b"synthetic-sensitive-value" not in payload
    code, _, payload = request(console, "POST", "/api/connections/target", body='{"secret":"synthetic-private"}')
    assert code == 400 and json.loads(payload) == {"error": "invalid_connection"}
