"""Install the optional isolated MCP SDK and print a local client configuration."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_VERSION = "2.3.0"
PIP_VERSION = "26.2"


def environment_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def client_configuration(sdk_python: Path, runner_python: Path, data_dir: Path, console_state: Path | None = None) -> dict:
    """Generate machine-local paths at runtime instead of committing identities."""
    arguments = ([str(ROOT / "scripts/mcp_server.py"), "--console-state", str(console_state.expanduser().absolute())]
                 if console_state else [str(ROOT / "scripts/mcp_server.py"),
                 "--runner-python", str(runner_python.absolute()), "--data-dir", str(data_dir.absolute())])
    return {"mcpServers": {"api-testing-framework": {
        "command": str(sdk_python.absolute()),
        "args": arguments,
        "env": {"PYTHONDONTWRITEBYTECODE": "1"},
    }}}


def render_configuration(configuration: dict, output_format: str = "claude") -> str:
    """Render host syntax while preserving spaces, quotes and platform paths."""
    if output_format == "claude":
        return json.dumps(configuration, indent=2, ensure_ascii=False)
    if output_format != "codex":
        raise ValueError("invalid_configuration_format")
    entry = configuration["mcpServers"]["api-testing-framework"]
    def quote(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    return "\n".join([
        "[mcp_servers.api-testing-framework]",
        f"command = {quote(entry['command'])}",
        f"args = {quote(entry['args'])}",
        "",
        "[mcp_servers.api-testing-framework.env]",
        f"PYTHONDONTWRITEBYTECODE = {quote(entry['env']['PYTHONDONTWRITEBYTECODE'])}",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path,
                        default=Path.home() / "sandbox/enterprise-api-testing-framework/mcp",
                        help="SDK environment/cache directory beneath ~/sandbox")
    parser.add_argument("--data-dir", type=Path,
                        default=Path.home() / "sandbox/enterprise-api-testing-framework/control")
    parser.add_argument("--format", choices=("claude", "codex"), default="claude",
                        help="Print Claude JSON (default) or Codex TOML; host settings are not edited")
    parser.add_argument("--console-state", type=Path, help="Use the running console's connections instead of a separate session")
    args = parser.parse_args()
    if sys.prefix == sys.base_prefix:
        parser.error("activate the framework virtual environment first; global Python is not used")
    sandbox = args.sandbox.expanduser().resolve()
    data_dir = args.data_dir.expanduser().resolve()
    allowed = (Path.home() / "sandbox").resolve()
    if args.console_state:
        args.console_state = args.console_state.expanduser().absolute()
        if not args.console_state.resolve().is_relative_to(allowed):
            parser.error("the console state must be beneath ~/sandbox")
    if not sandbox.is_relative_to(allowed) or not data_dir.is_relative_to(allowed):
        parser.error("SDK resources and run data must be beneath ~/sandbox")
    if sandbox.is_relative_to(ROOT) or data_dir.is_relative_to(ROOT):
        parser.error("select sandbox paths outside the source checkout")
    sdk_dir = sandbox / "venv"
    sdk_python = environment_python(sdk_dir)
    if sdk_dir.resolve() == Path(sys.prefix).resolve():
        parser.error("the SDK environment must differ from the framework environment")
    try:
        sandbox.mkdir(parents=True, exist_ok=True)
        cache, temporary = sandbox / "cache", sandbox / "tmp"
        cache.mkdir(exist_ok=True)
        temporary.mkdir(exist_ok=True)
        if not sdk_dir.exists():
            print("Creating the isolated MCP SDK environment.", file=sys.stderr)
            venv.EnvBuilder(with_pip=True).create(sdk_dir)
        if not sdk_python.is_file() or not (sdk_dir / "pyvenv.cfg").is_file():
            raise ValueError("invalid SDK environment")
        env = {**os.environ, "PIP_CACHE_DIR": str(cache), "TMPDIR": str(temporary),
               "PYTHONDONTWRITEBYTECODE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
        identity = subprocess.run(
            [str(sdk_python), "-c", "import sys; print(sys.prefix); print(sys.base_prefix)"],
            env=env, capture_output=True, text=True,
        )
        prefixes = identity.stdout.splitlines()
        if (identity.returncode or len(prefixes) != 2 or prefixes[0] == prefixes[1]
                or Path(prefixes[0]).resolve() != sdk_dir.resolve()):
            raise ValueError("refusing a global or mismatched SDK interpreter")
        # Compare package versions without importing a server or opening a port.
        check = subprocess.run(
            [str(sdk_python), "-c", "import importlib.metadata as m; print(m.version('mcp')); print(m.version('pip'))"],
            env=env, capture_output=True, text=True,
        )
        if check.returncode or check.stdout.splitlines() != [SDK_VERSION, PIP_VERSION]:
            print("Installing the optional SDK; framework dependencies remain separate.", file=sys.stderr)
            subprocess.run([str(sdk_python), "-m", "pip", "install", "-r",
                            str(ROOT / "requirements-mcp.txt")], env=env,
                           stdout=sys.stderr, stderr=sys.stderr, check=True)
        subprocess.run([str(sdk_python), "-m", "pip", "check"], env=env,
                       stdout=sys.stderr, stderr=sys.stderr, check=True)
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("MCP setup failed; check the SDK environment and installation output.", file=sys.stderr)
        return 2
    print(render_configuration(client_configuration(sdk_python, Path(sys.executable), data_dir, args.console_state),
                               args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
