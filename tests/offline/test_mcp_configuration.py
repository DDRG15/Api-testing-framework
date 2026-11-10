"""Host configuration round trips must not split or corrupt local paths."""
from __future__ import annotations

import json
import tomllib

import pytest

from scripts.setup_mcp import client_configuration, render_configuration


@pytest.mark.parametrize("command,args", [
    ("/path with spaces/SDK/python", ["/checkout with spaces/scripts/mcp_server.py", "--runner-python", "/runner/python"]),
    (r"C:\Program Files\SDK\Scripts\python.exe", [r"C:\Source Projects\framework\scripts\mcp_server.py", "--runner-python", r"D:\Runner Env\Scripts\python.exe"]),
    ('/path/with "quotes"/python', ["/path/with\\backslash/server.py", "--data-dir", "/path/é/🧪"]),
])
def test_claude_json_and_codex_toml_preserve_identical_launch_values(command, args):
    entry = {"command": command, "args": args, "env": {"PYTHONDONTWRITEBYTECODE": "1"}}
    config = {"mcpServers": {"api-testing-framework": entry}}
    assert json.loads(render_configuration(config)) == config
    codex = tomllib.loads(render_configuration(config, "codex"))
    assert codex == {"mcp_servers": {"api-testing-framework": entry}}


def test_generated_config_selects_separate_sdk_and_framework_interpreters(tmp_path):
    sdk = tmp_path / "SDK environment/bin/python"
    runner = tmp_path / "Framework environment/bin/python"
    data = tmp_path / "Run evidence"
    config = client_configuration(sdk, runner, data)
    entry = config["mcpServers"]["api-testing-framework"]
    assert entry["command"] == str(sdk.absolute())
    assert entry["args"][1:] == ["--runner-python", str(runner.absolute()),
                                  "--data-dir", str(data.absolute())]
    assert tomllib.loads(render_configuration(config, "codex"))["mcp_servers"]["api-testing-framework"] == entry


def test_unknown_host_format_is_rejected():
    with pytest.raises(ValueError, match="invalid_configuration_format"):
        render_configuration({}, "unsupported")


def test_console_bridge_configuration_shares_state_without_embedding_credentials(tmp_path):
    config = client_configuration(tmp_path / "SDK/bin/python", tmp_path / "core/bin/python",
                                  tmp_path / "data", tmp_path / "desktop/checkout/state.json")
    entry = config["mcpServers"]["api-testing-framework"]
    assert entry["args"][1:] == ["--console-state", str(tmp_path / "desktop/checkout/state.json")]
    assert "--runner-python" not in entry["args"]
    assert tomllib.loads(render_configuration(config, "codex"))["mcp_servers"]["api-testing-framework"] == entry


def test_console_bridge_configuration_expands_a_quoted_home_path(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setenv("HOME", str(tmp_path))
    config = client_configuration(tmp_path / "sdk/python", tmp_path / "core/python", tmp_path / "data",
                                  Path("~/sandbox/desktop/state.json"))
    assert config["mcpServers"]["api-testing-framework"]["args"][-1] == str(tmp_path / "sandbox/desktop/state.json")
