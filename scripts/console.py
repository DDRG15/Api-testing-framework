"""Build (or reuse) the local React console and serve it on loopback."""
from __future__ import annotations

import argparse
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from build_console import ROOT, build_console

sys.path.insert(0, str(ROOT))
from src.control.http_server import ConsoleServer  # noqa: E402
from src.control.service import ControlService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path, default=Path.home() / "sandbox/enterprise-api-testing-framework")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    try:
        assets = build_console(args.sandbox)
        with closing(ControlService(ROOT, args.sandbox / "control", sys.executable)) as service:
            with ConsoleServer(service, assets, port=args.port) as server:
                print(f"Open this local session: {server.launch_url}", flush=True)
                print("Press Ctrl+C to stop. Session tokens and raw evidence are local.", flush=True)
                server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Console could not start: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
