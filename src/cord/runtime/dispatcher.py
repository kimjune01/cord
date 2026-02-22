"""Launch claude CLI processes for cord nodes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


MCP_TOOLS = [
    "mcp__cord__read_tree",
    "mcp__cord__read_node",
    "mcp__cord__create",
    "mcp__cord__ask",
    "mcp__cord__stop",
    "mcp__cord__complete",
    "mcp__cord__pause",
    "mcp__cord__resume",
    "mcp__cord__modify",
]


def generate_mcp_config(db_path: Path, agent_id: str, project_dir: Path) -> dict:
    """Generate MCP config that spawns a stdio server for this agent."""
    return {
        "mcpServers": {
            "cord": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory", str(project_dir.resolve()),
                    "cord-mcp-server",
                    "--db-path", str(db_path.resolve()),
                    "--agent-id", agent_id,
                ],
            }
        }
    }


def launch_agent(
    db_path: Path,
    node_id: str,
    prompt: str,
    work_dir: Path | None = None,
    max_budget_usd: float = 2.0,
    model: str = "sonnet",
    project_dir: Path | None = None,
) -> subprocess.Popen[str]:
    """Launch a claude CLI process for a node."""
    proj = project_dir or db_path.parent
    mcp_config = generate_mcp_config(db_path, node_id, proj)

    config_dir = db_path.parent / ".cord"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"mcp-{node_id.lstrip('#')}.json"
    config_path.write_text(json.dumps(mcp_config, indent=2))

    cmd = [
        "claude",
        "-p", prompt,
        "--model", model,
        "--mcp-config", str(config_path),
        "--allowedTools", " ".join(MCP_TOOLS),
        "--dangerously-skip-permissions",
        "--max-budget-usd", str(max_budget_usd),
    ]

    cwd = str(work_dir) if work_dir else str(proj)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )

    return process
