"""Agent harness base types and shared launch helpers."""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


MCP_TOOLS = [
    "mcp__cord__read_tree",
    "mcp__cord__read_node",
    "mcp__cord__spawn",
    "mcp__cord__fork",
    "mcp__cord__ask",
    "mcp__cord__stop",
    "mcp__cord__complete",
    "mcp__cord__pause",
    "mcp__cord__resume",
    "mcp__cord__modify",
]


@dataclass(frozen=True)
class AgentLaunchRequest:
    """Runtime launch inputs for a single agent subprocess."""

    db_path: Path
    node_id: str
    prompt: str
    project_dir: Path
    work_dir: Path | None = None
    max_budget_usd: float = 2.0
    model: str = "sonnet"


@dataclass(frozen=True)
class LaunchSpec:
    """Resolved subprocess launch settings for a harness."""

    cmd: list[str]
    cwd: Path
    env: dict[str, str] | None = None


def generate_mcp_config(db_path: Path, agent_id: str, project_dir: Path) -> dict:
    """Generate MCP config that spawns a stdio server for this agent."""
    return {
        "mcpServers": {
            "cord": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    str(project_dir.resolve()),
                    "cord-mcp-server",
                    "--db-path",
                    str(db_path.resolve()),
                    "--agent-id",
                    agent_id,
                ],
            }
        }
    }


def write_json_file(path: Path, payload: dict) -> Path:
    """Write JSON payload to disk, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def node_file_slug(node_id: str) -> str:
    """Return a filesystem-safe node id slug."""
    return node_id.lstrip("#")


class AgentHarness(ABC):
    """Backend-agnostic subprocess harness for launching agents."""

    @abstractmethod
    def build_launch_spec(self, request: AgentLaunchRequest) -> LaunchSpec:
        """Return concrete subprocess settings for a request."""

    def launch(self, request: AgentLaunchRequest) -> subprocess.Popen[str]:
        """Launch a subprocess for an agent request."""
        spec = self.build_launch_spec(request)
        return subprocess.Popen(
            spec.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(spec.cwd),
            env=spec.env,
        )
