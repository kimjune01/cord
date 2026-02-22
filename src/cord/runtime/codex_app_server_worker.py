"""Run one Cord node turn via Codex App Server (JSON-RPC over stdio)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUIRED_CORD_TOOLS = {
    "read_tree",
    "read_node",
    "create",
    "ask",
    "stop",
    "complete",
    "pause",
    "resume",
    "modify",
}


def _send(proc: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if proc.stdin is None:
        raise RuntimeError("Codex app-server stdin is unavailable")
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def _start_app_server(
    project_dir: Path,
    mcp_command: str,
    mcp_args: list[str],
) -> subprocess.Popen[str]:
    cmd = [
        "codex",
        "app-server",
        "-c",
        'approval_policy="never"',
        "-c",
        'sandbox_mode="danger-full-access"',
        "-c",
        f"mcp_servers.cord.command={json.dumps(mcp_command)}",
        "-c",
        f"mcp_servers.cord.args={json.dumps(mcp_args)}",
        "-c",
        "mcp_servers.cord.required=true",
        "-c",
        f"mcp_servers.cord.cwd={json.dumps(str(project_dir.resolve()))}",
    ]

    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(project_dir.resolve()),
    )


def _format_rpc_error(message: dict[str, Any]) -> str:
    err = message.get("error")
    if not isinstance(err, dict):
        return "unknown app-server error"
    code = err.get("code")
    text = err.get("message")
    if code is None and text is None:
        return str(err)
    return f"{code}: {text}"


def _read_message(proc: subprocess.Popen[str]) -> dict[str, Any]:
    if proc.stdout is None:
        raise RuntimeError("Codex app-server stdout is unavailable")

    while True:
        line = proc.stdout.readline()
        if line == "":
            rc = proc.poll()
            if rc is None:
                continue
            raise RuntimeError("Codex app-server exited unexpectedly")

        line = line.strip()
        if not line:
            continue

        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue


def _handle_server_request(proc: subprocess.Popen[str], message: dict[str, Any]) -> bool:
    if "id" not in message or "method" not in message:
        return False

    req_id = message["id"]
    method = message.get("method")

    if method in (
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    ):
        _send(proc, {"id": req_id, "result": "accept"})
        return True

    _send(
        proc,
        {
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Unsupported request method: {method}",
            },
        },
    )
    return True


def _extract_tool_names(server_entry: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("tools", "enabledTools", "availableTools", "toolNames"):
        value = server_entry.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    names.add(item)
                elif isinstance(item, dict):
                    for name_key in ("name", "tool", "id"):
                        candidate = item.get(name_key)
                        if isinstance(candidate, str):
                            names.add(candidate)
                            break
        elif isinstance(value, dict):
            for item_key in value.keys():
                if isinstance(item_key, str):
                    names.add(item_key)
    return names


def _is_cord_server(server_entry: dict[str, Any]) -> bool:
    for key in ("name", "id", "server", "serverName"):
        value = server_entry.get(key)
        if value == "cord":
            return True
        if isinstance(value, dict):
            nested_name = value.get("name")
            if nested_name == "cord":
                return True
    return False


def _preflight_cord_mcp(proc: subprocess.Popen[str]) -> None:
    """Verify app-server loaded the 'cord' MCP server and required tools."""
    cursor: str | None = None
    request_id = 90
    cord_found = False
    cord_tools: set[str] = set()

    while True:
        params: dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor

        _send(
            proc,
            {
                "id": request_id,
                "method": "mcpServerStatus/list",
                "params": params,
            },
        )

        while True:
            message = _read_message(proc)

            if _handle_server_request(proc, message):
                continue

            if "id" not in message:
                continue

            if "error" in message:
                raise RuntimeError(
                    f"MCP preflight RPC failed: {_format_rpc_error(message)}"
                )

            if message["id"] != request_id:
                continue

            result = message.get("result", {})
            if not isinstance(result, dict):
                raise RuntimeError(
                    "MCP preflight failed: malformed mcpServerStatus/list result"
                )

            data = result.get("data", [])
            if isinstance(data, list):
                for entry in data:
                    if not isinstance(entry, dict):
                        continue
                    if _is_cord_server(entry):
                        cord_found = True
                        cord_tools.update(_extract_tool_names(entry))

            next_cursor = result.get("nextCursor")
            cursor = next_cursor if isinstance(next_cursor, str) and next_cursor else None
            break

        if cursor is None:
            break
        request_id += 1

    if not cord_found:
        raise RuntimeError(
            "MCP preflight failed: app-server did not report a 'cord' MCP server in mcpServerStatus/list."
        )

    missing = sorted(REQUIRED_CORD_TOOLS - cord_tools)
    if missing:
        raise RuntimeError(
            "MCP preflight failed: 'cord' MCP server is missing required tools: "
            + ", ".join(missing)
        )


def _run_turn(
    prompt: str,
    model: str | None,
    project_dir: Path,
    mcp_command: str,
    mcp_args: list[str],
) -> str:
    proc = _start_app_server(project_dir, mcp_command, mcp_args)
    last_agent_item_id: str | None = None
    agent_text_by_item: dict[str, str] = {}
    agent_delta_by_item: dict[str, str] = {}
    turn_id: str | None = None
    thread_id: str | None = None

    try:
        _send(
            proc,
            {
                "id": 0,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "cord_app_server",
                        "title": "Cord App Server Runtime",
                        "version": "0.1.0",
                    }
                },
            },
        )
        _send(proc, {"method": "initialized", "params": {}})
        _preflight_cord_mcp(proc)

        thread_start_params: dict[str, Any] = {
            "cwd": str(project_dir.resolve()),
            "approvalPolicy": "never",
            "sandbox": "danger-full-access",
        }
        if model:
            thread_start_params["model"] = model

        _send(
            proc,
            {
                "id": 1,
                "method": "thread/start",
                "params": thread_start_params,
            },
        )

        while True:
            message = _read_message(proc)

            if _handle_server_request(proc, message):
                continue

            if "id" in message:
                msg_id = message["id"]
                if "error" in message:
                    raise RuntimeError(
                        f"JSON-RPC request {msg_id} failed: {_format_rpc_error(message)}"
                    )

                if msg_id == 1:
                    thread_id = (
                        message.get("result", {})
                        .get("thread", {})
                        .get("id")
                    )
                    if not thread_id:
                        raise RuntimeError("thread/start did not return thread.id")

                    _send(
                        proc,
                        {
                            "id": 2,
                            "method": "turn/start",
                            "params": {
                                "threadId": thread_id,
                                "input": [{"type": "text", "text": prompt}],
                            },
                        },
                    )
                    continue

                if msg_id == 2:
                    turn_id = (
                        message.get("result", {})
                        .get("turn", {})
                        .get("id")
                    )
                    continue

                continue

            method = message.get("method")
            params = message.get("params", {})

            if method == "item/agentMessage/delta":
                item_id = params.get("itemId")
                delta = params.get("delta")
                if isinstance(item_id, str) and isinstance(delta, str):
                    agent_delta_by_item[item_id] = agent_delta_by_item.get(item_id, "") + delta
                    last_agent_item_id = item_id
                continue

            if method == "item/completed":
                item = params.get("item", {})
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "agentMessage":
                    item_id = item.get("id")
                    text = item.get("text")
                    if isinstance(item_id, str) and isinstance(text, str):
                        agent_text_by_item[item_id] = text
                        last_agent_item_id = item_id
                continue

            if method == "turn/completed":
                turn = params.get("turn", {})
                if not isinstance(turn, dict):
                    continue

                completed_turn_id = turn.get("id")
                if isinstance(turn_id, str) and isinstance(completed_turn_id, str):
                    if completed_turn_id != turn_id:
                        continue

                status = turn.get("status")
                if status == "failed":
                    turn_error = turn.get("error", {})
                    if isinstance(turn_error, dict):
                        msg = turn_error.get("message")
                        raise RuntimeError(f"turn/start failed: {msg or 'unknown error'}")
                    raise RuntimeError("turn/start failed")

                if status in ("completed", "interrupted"):
                    break

        if last_agent_item_id:
            if last_agent_item_id in agent_text_by_item:
                return agent_text_by_item[last_agent_item_id].strip()
            if last_agent_item_id in agent_delta_by_item:
                return agent_delta_by_item[last_agent_item_id].strip()

        if agent_text_by_item:
            return list(agent_text_by_item.values())[-1].strip()
        if agent_delta_by_item:
            return list(agent_delta_by_item.values())[-1].strip()

        return ""
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Cord node via Codex App Server")
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--mcp-command", required=True)
    parser.add_argument("--mcp-arg", action="append", default=[])
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args(sys.argv[1:])
    prompt = args.prompt_file.read_text().strip()

    try:
        result = _run_turn(
            prompt=prompt,
            model=args.model,
            project_dir=args.project_dir,
            mcp_command=args.mcp_command,
            mcp_args=args.mcp_arg,
        )
        if result:
            print(result)
        return 0
    except Exception as exc:
        print(f"codex-app-server worker error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
