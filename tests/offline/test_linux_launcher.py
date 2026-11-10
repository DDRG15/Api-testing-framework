from __future__ import annotations

import os
import signal
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import launch_linux as launcher  # noqa: E402


def test_sandbox_rejects_repository_and_outside_home_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert launcher.sandbox_path(tmp_path / "sandbox/project") == tmp_path / "sandbox/project"
    with pytest.raises(ValueError, match="Runtime resources"):
        launcher.sandbox_path(tmp_path / "elsewhere")
    monkeypatch.setattr(launcher, "ROOT", tmp_path / "sandbox/repository")
    with pytest.raises(ValueError, match="outside the checkout"):
        launcher.sandbox_path(launcher.ROOT / "runtime")


def test_process_identity_and_corrupted_or_reused_pid_are_not_owned(tmp_path):
    boot, ticks = launcher.process_identity(os.getpid())
    state = {"pid": os.getpid(), "boot_id": boot, "start_ticks": ticks,
             "runner_python": sys.executable}
    assert not launcher.owned_process(state, tmp_path)
    state["start_ticks"] = "stale"
    assert not launcher.owned_process(state, tmp_path)
    for pid in (None, True, -1, 1, "123"):
        assert not launcher.owned_process({**state, "pid": pid}, tmp_path)


def test_stop_never_signals_an_unowned_process(tmp_path, monkeypatch):
    directory = tmp_path / "desktop"
    directory.mkdir()
    launcher.private_write(directory / "state.json", {"pid": os.getpid()})
    monkeypatch.setattr(signal, "pidfd_send_signal", lambda *_: pytest.fail("Unowned process signaled"))
    launcher.stop(Namespace(sandbox=tmp_path), directory)
    assert launcher.read_state(directory / "state.json")["pid"] == os.getpid()


def test_private_state_is_atomic_and_has_no_group_or_world_permissions(tmp_path):
    state = tmp_path / "state.json"
    launcher.private_write(state, {"url": "synthetic-local-token"})
    assert state.stat().st_mode & 0o777 == 0o600
    assert launcher.read_state(state) == {"url": "synthetic-local-token"}
    assert not state.with_suffix(".new").exists()
    state.write_text("broken")
    assert launcher.read_state(state) == {}


def test_desktop_entry_handles_spaces_and_rejects_exec_field_codes(tmp_path, monkeypatch):
    root = tmp_path / "source with spaces"
    monkeypatch.setattr(launcher, "ROOT", root)
    entry = launcher.desktop_entry(Namespace(sandbox=tmp_path / "sandbox/work", python=tmp_path / "venv/bin/python"))
    assert f'Exec="{root}/api-lab" "--sandbox" ' in entry
    assert "Terminal=false\n" in entry
    assert "Autostart" not in entry
    for value in ("bad%f", "bad\npath", "bad\rpath", "bad\x00path"):
        with pytest.raises(ValueError, match="Unsupported character"):
            launcher.desktop_quote(value)


def test_setup_refuses_to_repair_an_arbitrary_interpreter(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "core_ready", lambda _: False)
    monkeypatch.setattr(launcher.subprocess, "run", lambda *_a, **_k: pytest.fail("Unexpected install"))
    with pytest.raises(ValueError, match="prepare it separately"):
        launcher.setup(Namespace(python=tmp_path / "existing/bin/python", sandbox=tmp_path / "sandbox"))


def test_readiness_rejects_remote_or_malformed_session_urls(monkeypatch):
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("Unexpected request"))
    misleading_host = "http://127.0.0.1:80" + "@" + "example.com/#token=x"
    for url in ("https://example.com/#token=x", misleading_host,
                "http://127.0.0.1:bad/#token=x", "http://127.0.0.1:80/path/#token=x", None):
        assert not launcher.ready_url({"url": url})
