"""Connect an MCP host to the already running console without copying API keys."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class ConsoleBridge:
    """Read the launcher state on every call so a restart cannot leave a stale token."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path.expanduser().absolute()
        if not self.state_path.resolve().is_relative_to((Path.home() / "sandbox").resolve()):
            raise ValueError("invalid_console_state")

    def _call(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            if self.state_path.is_symlink() or self.state_path.stat().st_size > 16_384:
                raise ValueError
            state = json.loads(self.state_path.read_text())
            url = urlsplit(state["url"])
            if (url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                    or url.username or url.password or url.path != "/" or url.query
                    or not re.fullmatch(r"token=[A-Za-z0-9_-]{32,128}", url.fragment)):
                raise ValueError
            request = urllib.request.Request(f"http://127.0.0.1:{url.port}/api/{path}",
                                             data=json.dumps(data).encode() if data is not None else None,
                                             headers={"X-Console-Token": url.fragment[6:],
                                                      "Origin": f"http://127.0.0.1:{url.port}",
                                                      "Content-Type": "application/json"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=5) as response:
                body = response.read(1_048_577)
                if len(body) > 1_048_576:
                    raise ValueError
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ValueError
                return result
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                raise RuntimeError("execution_in_progress") from None
            raise RuntimeError("operation_unavailable") from None
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError("console_unavailable") from None

    def capabilities(self) -> dict[str, Any]:
        return self._call("capabilities")

    def list_runs(self) -> list[dict[str, Any]]:
        result = self._call("runs")["runs"]
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise RuntimeError("console_unavailable")
        return cast(list[dict[str, Any]], result)

    def start_run(self, operation: str) -> dict[str, Any]:
        if operation not in {"offline", "contracts", "evaluation", "target", "openai", "anthropic"}:
            raise ValueError("invalid_operation")
        return self._call("runs", {"operation": operation})

    def get_run(self, run_id: str) -> dict[str, Any]:
        import uuid
        try:
            if str(uuid.UUID(run_id)) != run_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("invalid_run_id") from None
        return self._call(f"runs/{run_id}")

    def connection_status(self) -> dict[str, Any]:
        return self._call("connections")

    def close(self) -> None:
        # The console belongs to the user, not the editor-host connection.
        pass
