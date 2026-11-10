"""Manage a checkout-specific Linux console and optional per-user menu entry."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import venv
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "api-lab-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
DEFAULT_SANDBOX = Path.home() / "sandbox/enterprise-api-testing-framework"


def sandbox_path(value: Path) -> Path:
    value = value.expanduser().resolve()
    if not value.is_relative_to((Path.home() / "sandbox").resolve()) or value.is_relative_to(ROOT):
        raise ValueError("Runtime resources must be under ~/sandbox, outside the checkout")
    return value


def private_write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".new")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2)
        stream.write("\n")
    temporary.replace(path)


def read_state(path: Path) -> dict:
    try:
        result = json.loads(path.read_text())
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def process_identity(pid: int) -> tuple[str, str]:
    """Distinguish a process from a later process that reuses its PID."""
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    if fields[0] == "Z":
        raise ProcessLookupError("Process has exited")
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip(), fields[19]


def owned_process(state: dict, sandbox: Path) -> bool:
    try:
        pid = state["pid"]
        if type(pid) is not int or pid <= 1:
            return False
        if process_identity(pid) != (state["boot_id"], state["start_ticks"]):
            return False
        command = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        expected_tail = ["-B", str(Path(__file__).resolve()), "--sandbox", str(sandbox),
                         "--python", state["runner_python"], "_serve"]
        return command == [os.fsencode(state["runner_python"]), *map(os.fsencode, expected_tail)]
    except (OSError, ValueError, KeyError, TypeError):
        return False


@contextmanager
def locked(directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    with (directory / "manager.lock").open("a") as stream:
        os.chmod(directory / "manager.lock", 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def core_ready(python: Path) -> bool:
    """Check the pinned core packages without changing an existing environment."""
    probe = """import importlib.metadata as m, pathlib, sys
assert sys.prefix != sys.base_prefix
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    text = line.split('#', 1)[0].strip()
    if not text or text.startswith('-'): continue
    name, version = text.split('==')
    assert m.version(name) == version
"""
    try:
        return subprocess.run([str(python), "-B", "-c", probe, str(ROOT / "requirements.txt")],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def setup(args) -> None:
    python = args.python
    if core_ready(python):
        print("The pinned core environment is ready.")
        return
    environment = args.sandbox / "venv"
    if python != environment / "bin/python":
        raise ValueError("The selected interpreter is not ready; prepare it separately or use the default sandbox environment")
    if not environment.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    if not (environment / "pyvenv.cfg").is_file():
        raise ValueError("Refusing to install into an invalid environment")
    identity = subprocess.run([str(python), "-B", "-c", "import sys; print(sys.prefix); print(sys.base_prefix)"],
                              capture_output=True, text=True, check=True).stdout.splitlines()
    if (len(identity) != 2 or identity[0] == identity[1]
            or Path(identity[0]).resolve() != environment.resolve()):
        raise ValueError("Refusing to install into a global or mismatched interpreter")
    cache, temporary = args.sandbox / "pip-cache", args.sandbox / "tmp"
    cache.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(exist_ok=True)
    subprocess.run([str(python), "-B", "-m", "pip", "install", "-r", str(ROOT / "requirements-dev.txt")],
                   env={**os.environ, "PIP_CACHE_DIR": str(cache), "TMPDIR": str(temporary)}, check=True)
    if not core_ready(python):
        raise ValueError("Core environment verification failed")
    print("The pinned core environment is ready.")


def ready_url(state: dict) -> bool:
    url = state.get("url", "")
    if not isinstance(url, str) or "/#token=" not in url:
        return False
    origin, token = url.split("/#token=", 1)
    try:
        parts = urlsplit(origin)
        if (parts.scheme != "http" or parts.hostname != "127.0.0.1" or parts.port is None
                or parts.username or parts.password or parts.path or parts.query):
            return False
        request = urllib.request.Request(origin + "/api/capabilities", headers={"X-Console-Token": token})
        with urllib.request.urlopen(request, timeout=1) as response:
            return response.status == 200
    except (OSError, ValueError, urllib.error.URLError):
        return False


def open_browser(url: str) -> None:
    if not shutil.which("xdg-open"):
        print("No xdg-open found; open the private session URL manually.")
        return
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def start(args, directory: Path) -> None:
    state_file = directory / "state.json"
    with locked(directory):
        state = read_state(state_file)
        if owned_process(state, args.sandbox):
            if not ready_url(state):
                raise ValueError("The owned process is still starting or unavailable; inspect the private log")
        else:
            if not core_ready(args.python):
                raise ValueError("Core environment is not ready. Run api-lab setup, or select a prepared --python")
            log = directory / "console.log"
            with log.open("a") as stream:
                os.chmod(log, 0o600)
                child = subprocess.Popen([
                    str(args.python), "-B", str(Path(__file__).resolve()),
                    "--sandbox", str(args.sandbox), "--python", str(args.python), "_serve",
                ], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                    start_new_session=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            # The child writes its identity before performing a potentially slow first build.
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                state = read_state(state_file)
                if state.get("pid") == child.pid and owned_process(state, args.sandbox) and ready_url(state):
                    break
                if child.poll() is not None:
                    raise ValueError(f"Console startup failed; inspect {log}")
                time.sleep(0.2)
            else:
                raise ValueError(f"Startup is still pending; inspect {log} and use status or stop")
    print(f"Local session: {state['url']}")
    print("Closing the browser leaves the console running. Use api-lab stop to stop this checkout.")
    if not args.no_open:
        open_browser(state["url"])


def stop(args, directory: Path) -> None:
    with locked(directory):
        state = read_state(directory / "state.json")
        if not owned_process(state, args.sandbox):
            print("No owned console process is running.")
            return
        # Hold a process handle so PID reuse cannot redirect the signal.
        descriptor = os.pidfd_open(state["pid"])
        try:
            if not owned_process(state, args.sandbox):
                return
            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        finally:
            os.close(descriptor)
        deadline = time.monotonic() + 15
        while owned_process(state, args.sandbox) and time.monotonic() < deadline:
            time.sleep(0.1)
        if owned_process(state, args.sandbox):
            raise ValueError("The owned process has not stopped yet; no forced or unrelated cleanup was attempted")
        print("The owned console stopped. Retained evidence was preserved.")


def serve(args, directory: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from build_console import build_console

    from src.control.http_server import ConsoleServer
    from src.control.service import ControlService

    boot, ticks = process_identity(os.getpid())
    state = {"pid": os.getpid(), "boot_id": boot, "start_ticks": ticks,
             "runner_python": str(args.python)}
    private_write(directory / "state.json", state)
    # Shutdown happens in another thread because HTTPServer.shutdown waits for serve_forever.
    stopping = threading.Event()
    server = None

    def shutdown(_number, _frame):
        stopping.set()
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    assets = build_console(args.sandbox)
    with closing(ControlService(ROOT, args.sandbox / "control", str(args.python))) as service:
        with ConsoleServer(service, assets) as server:
            if stopping.is_set():
                return
            state["url"] = server.launch_url
            private_write(directory / "state.json", state)
            server.serve_forever(poll_interval=0.2)


def desktop_quote(value: str) -> str:
    """Quote one Exec argument through both Desktop Entry escaping layers."""
    if any(character in value for character in "\n\r\x00%"):
        raise ValueError("Unsupported character in desktop launcher path")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return '"' + escaped.replace("\\", "\\\\") + '"'


def desktop_entry(args) -> str:
    command = [str(ROOT / "api-lab"), "--sandbox", str(args.sandbox), "--python", str(args.python), "start"]
    icon = str(ROOT / "assets/api-lab.svg")
    if any(character in icon for character in "\n\r\x00\\"):
        raise ValueError("Unsupported character in icon path")
    return "\n".join([
        "[Desktop Entry]", "Type=Application", "Version=1.0", "Name=API Testing Framework",
        "Comment=Run local API framework checks", "Exec=" + " ".join(map(desktop_quote, command)),
        "Icon=" + icon, "Terminal=false", "Categories=Development;", "StartupNotify=false", "",
    ])


def install(args) -> None:
    if not core_ready(args.python):
        raise ValueError("Prepare the core environment before installing a menu entry")
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))).expanduser()
    if not data_home.is_absolute() or not data_home.resolve().is_relative_to(Path.home().resolve()):
        raise ValueError("The menu entry must be installed under the current user's home")
    target = data_home / "applications" / f"{APP_ID}.desktop"
    entry = desktop_entry(args)
    if target.exists() and target.read_text() != entry:
        raise ValueError("An existing menu entry differs; review it before replacing it")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(entry)
    target.chmod(0o644)
    print(f"Installed menu entry: {target}")
    print("Open API Testing Framework from your application menu. No autostart entry was created.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path, default=DEFAULT_SANDBOX)
    parser.add_argument("--python", type=Path, help="Prepared framework virtual-environment Python")
    parser.add_argument("--sdk-python", type=Path, help="Optional isolated MCP SDK Python")
    commands = parser.add_subparsers(dest="command")
    start_parser = commands.add_parser("start", help="Start or reopen this checkout's console")
    start_parser.add_argument("--no-open", action="store_true")
    status_parser = commands.add_parser("status", help="Inspect this checkout's owned process")
    status_parser.add_argument("--json", action="store_true")
    for name in ("stop", "setup", "install", "mcp", "_serve"):
        commands.add_parser(name)
    mcp_setup = commands.add_parser("mcp-setup")
    mcp_setup.add_argument("--format", choices=("claude", "codex"), default="claude")
    mcp_setup.add_argument("--console", action="store_true", help="Generate a bridge configuration sharing this console session")
    args = parser.parse_args()
    try:
        if sys.platform != "linux":
            raise ValueError("This launcher currently supports Linux")
        os.umask(0o077)
        args.sandbox = sandbox_path(args.sandbox)
        # Do not resolve the final symlink: virtual environments rely on their invocation path.
        args.python = (args.python or args.sandbox / "venv/bin/python").expanduser().absolute()
        directory = args.sandbox / "desktop" / APP_ID
        command = args.command or "start"
        if command == "start":
            if not hasattr(args, "no_open"):
                args.no_open = False
            start(args, directory)
        elif command == "stop":
            stop(args, directory)
        elif command == "status":
            state = read_state(directory / "state.json")
            running = owned_process(state, args.sandbox)
            result = {"running": running, **(state if running else {})}
            print(json.dumps(result) if args.json else (f"Running: {state.get('url', 'starting')}" if running else "Stopped"))
        elif command == "setup":
            setup(args)
        elif command == "install":
            install(args)
        elif command == "_serve":
            serve(args, directory)
        elif command == "mcp-setup":
            bridge_args = ["--console-state", str(directory / "state.json")] if args.console else []
            return subprocess.call([str(args.python), "-B", str(ROOT / "scripts/setup_mcp.py"),
                                    "--sandbox", str(args.sandbox / "mcp"), "--data-dir",
                                    str(args.sandbox / "control"), "--format", args.format, *bridge_args])
        elif command == "mcp":
            sdk = (args.sdk_python or args.sandbox / "mcp/venv/bin/python").expanduser().absolute()
            os.execv(str(sdk), [str(sdk), "-B", str(ROOT / "scripts/mcp_server.py"),
                               "--runner-python", str(args.python), "--data-dir", str(args.sandbox / "control")])
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        message = f"API Testing Framework: {exc}"
        print(message, file=sys.stderr)
        if (not sys.stderr.isatty() and os.environ.get("DISPLAY") and shutil.which("zenity")
                and args.command in (None, "start") and not getattr(args, "no_open", False)):
            subprocess.Popen(["zenity", "--error", "--title=API Testing Framework", "--text=" + message],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
