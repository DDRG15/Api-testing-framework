"""Expose bounded local framework operations over the official MCP stdio SDK."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def create_server(service: Any) -> Any:
    """Build the SDK server without starting transport or executing a test."""
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    server = MCPServer(
        "API Test Framework",
        version="1.0.0",
        instructions=(
            "Run bounded local checks and inspect sanitized summaries. "
            "Call capabilities first. Starting a run creates local evidence. "
            "Poll get_run until it finishes; a started run is not a passing run. "
            "Configure connections in the console, never send secrets through chat. "
            "With --console-state, tools share that console's in-memory connections. "
            "No tools accept shell commands, paths, URLs, or credentials."
        ),
        log_level="WARNING",
    )
    read = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                           idempotent_hint=True, open_world_hint=False)
    write = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                            idempotent_hint=False, open_world_hint=True)

    def invoke(action: Callable[[], Any]) -> Any:
        try:
            return action()
        except (ValueError, KeyError, RuntimeError) as exc:
            # Service messages are fixed codes; never forward arbitrary errors.
            code = str(exc).strip("'")
            allowed = {"invalid_operation", "invalid_run_id", "unknown_run",
                       "execution_in_progress", "service_closed", "operation_unavailable",
                       "connection_not_configured", "console_unavailable"}
            raise ToolError(code if code in allowed else "operation_unavailable") from None
        except OSError:
            raise ToolError("operation_unavailable") from None

    @server.tool(annotations=read)
    def capabilities() -> dict[str, Any]:
        """Describe supported local operations and concurrency limits."""
        return invoke(service.capabilities)

    @server.tool(annotations=read)
    def list_runs() -> dict[str, Any]:
        """List persisted runs using sanitized summaries, without logs or local paths."""
        return {"runs": invoke(service.list_runs)}

    @server.tool(annotations=write)
    def start_run(operation: Literal["offline", "contracts", "evaluation", "target", "openai", "anthropic"]) -> dict[str, Any]:
        """Start one fixed local check and return its ID; poll get_run for completion.

        offline runs controlled tests, contracts checks the schema baseline, and
        evaluation checks synthetic responses. target checks the configured GET
        contract; openai/anthropic check provider catalogs. Connection operations
        can contact the configured external API; they do not generate model text.
        """
        return invoke(lambda: service.start_run(operation))

    @server.tool(annotations=read)
    def get_run(run_id: str) -> dict[str, Any]:
        """Read one local run by its generated UUID; paths and raw evidence are omitted."""
        return invoke(lambda: service.get_run(run_id))

    @server.tool(annotations=read)
    def connections() -> dict[str, Any]:
        """Show configured connection flags without keys, URLs, headers or contracts."""
        return invoke(service.connection_status)

    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-python",
                        help="Framework virtual-environment Python, kept separate from the SDK")
    parser.add_argument("--data-dir", type=Path,
                        default=Path.home() / "sandbox/enterprise-api-testing-framework/control")
    parser.add_argument("--console-state", type=Path, help="Bridge to an existing launcher's private state.json")
    args = parser.parse_args()
    try:
        service: Any
        if args.console_state:
            from src.control.bridge import ConsoleBridge
            service = ConsoleBridge(args.console_state)
        else:
            if not args.runner_python:
                parser.error("--runner-python is required unless --console-state is selected")
            from src.control.service import ControlService
            service = ControlService(project_root=ROOT, data_root=args.data_dir,
                                     runner_python=args.runner_python)
        try:
            server = create_server(service)
            server.run(transport="stdio")
        finally:
            service.close()
    except ImportError:
        print("MCP dependencies unavailable. Run scripts/setup_mcp.py from the framework venv.",
              file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError):
        print("MCP startup failed: check the selected runner and sandbox configuration.",
              file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
