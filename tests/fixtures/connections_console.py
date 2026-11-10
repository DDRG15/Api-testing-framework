"""Explicit loopback-only acceptance fixture, never a production provider override."""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.control import connections  # noqa: E402
from src.control.http_server import ConsoleServer  # noqa: E402
from src.control.service import ControlService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=False)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            body = json.dumps({"status": "ok", "data": [], "private": "synthetic-private-fixture-response"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    target = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=target.serve_forever, daemon=True)
    worker.start()
    target_url = f"http://127.0.0.1:{target.server_port}"
    # Only this explicit fixture redirects provider catalogs to a synthetic server.
    connections.PROVIDERS.update({kind: target_url + "/models" for kind in connections.PROVIDERS})
    service = ControlService(ROOT, args.work_dir / "data", sys.executable)
    console = ConsoleServer(service, args.assets)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    server_worker = threading.Thread(target=console.serve_forever, daemon=True)
    server_worker.start()
    (args.work_dir / "state.json").write_text(json.dumps({"url": console.launch_url}))
    (args.work_dir / "fixture.json").write_text(json.dumps({"target_url": target_url, "console_url": console.launch_url}))
    print("Loopback connection acceptance fixture ready.", flush=True)
    try:
        stop.wait()
    finally:
        console.shutdown()
        console.server_close()
        server_worker.join(timeout=2)
        service.close()
        target.shutdown()
        target.server_close()
        worker.join(timeout=2)


if __name__ == "__main__":
    main()
