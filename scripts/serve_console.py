"""Serve the built React console on loopback with a session-only access token."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.control.http_server import ConsoleServer  # noqa: E402
from src.control.service import ControlService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path, help="Built React asset directory")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "sandbox/enterprise-api-testing-framework/control")
    parser.add_argument("--runner-python", default=sys.executable, help="Python from the framework's prepared virtual environment")
    parser.add_argument("--port", default=0, type=int, help="Loopback port; 0 selects an available port")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    service = ControlService(ROOT, args.data_dir, args.runner_python)
    server = None
    try:
        server = ConsoleServer(service, args.assets, args.port)
        print(f"Local console: {server.launch_url}", flush=True)
        print("Keep this session URL private. Press Ctrl+C to stop owned tasks.", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
