"""Exercise the actual optional SDK client/server transport and a bounded job."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]


async def check(runner_python: str, output: Path, console_state: Path | None = None) -> dict:
    arguments = ([str(ROOT / "scripts/mcp_server.py"), "--console-state", str(console_state)] if console_state
                 else [str(ROOT / "scripts/mcp_server.py"), "--runner-python", runner_python,
                       "--data-dir", str(output / "runs")])
    parameters = StdioServerParameters(
        command=sys.executable,
        args=arguments,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    with anyio.fail_after(60):
        async with Client(parameters) as client:
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == {
                "capabilities", "list_runs", "start_run", "get_run", "connections",
            }
            start = next(tool for tool in tools if tool.name == "start_run")
            assert start.annotations and start.annotations.read_only_hint is False
            assert start.input_schema["properties"]["operation"]["enum"] == [
                "offline", "contracts", "evaluation", "target", "openai", "anthropic",
            ]
            capabilities = await client.call_tool("capabilities", {})
            assert not capabilities.is_error
            assert capabilities.structured_content["credential_storage"] == "process_memory"
            connections = await client.call_tool("connections", {})
            if console_state:
                assert connections.structured_content["connections"][0]["configured"]
            else:
                assert not any(item["configured"] for item in connections.structured_content["connections"])
            runs = await client.call_tool("list_runs", {})
            assert not runs.is_error
            initial_count = len(runs.structured_content["runs"])
            if not console_state:
                assert initial_count == 0
            invalid = await client.call_tool("start_run", {"operation": "arbitrary-shell"})
            assert invalid.is_error
            missing = await client.call_tool("get_run", {"run_id": "../../private"})
            assert missing.is_error
            operation = "target" if console_state else "contracts"
            started = await client.call_tool("start_run", {"operation": operation})
            assert not started.is_error, started.content
            run_id = started.structured_content["run_id"]
            while True:
                result = await client.call_tool("get_run", {"run_id": run_id})
                assert not result.is_error, result.content
                record = result.structured_content
                if record["status"] not in {"queued", "running"}:
                    break
                await anyio.sleep(0.05)
            assert record["status"] == "passed", record
            serialized = json.dumps(record)
            assert str(ROOT) not in serialized and str(Path.home()) not in serialized
            assert "stdout" not in record and "log" not in record
            listed = await client.call_tool("list_runs", {})
            assert len(listed.structured_content["runs"]) == initial_count + 1
            return {
                "sdk_version": importlib.metadata.version("mcp"),
                "protocol_version": client.protocol_version,
                "tool_names": sorted(tool.name for tool in tools),
                "invalid_operation_rejected": True,
                "invalid_run_id_rejected": True,
                "operation_result": record,
                "console_bridge": console_state is not None,
                "sanitized_summaries": True,
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-python", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--console-state", type=Path, help="Check an existing fixture console with a configured target")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = anyio.run(check, args.runner_python, args.output, args.console_state)
    (args.output / "check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: real MCP stdio discovery, validation, bounded execution and sanitized results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
