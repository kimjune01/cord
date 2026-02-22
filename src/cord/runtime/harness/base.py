"""Base types and shared helpers for runtime adapters."""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
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


@dataclass(frozen=True)
class RuntimeCapabilities:
    """Describes what options a runtime adapter supports."""

    supports_model: bool = True
    supports_budget: bool = True
    supports_allowed_tools: bool = True
    requires_mcp_config: bool = True


@dataclass(frozen=True)
class AgentLaunchRequest:
    """Launch inputs for a single node agent process."""

    db_path: Path
    node_id: str
    prompt: str
    project_dir: Path
    work_dir: Path | None = None
    max_budget_usd: float = 2.0
    model: str | None = None


@dataclass(frozen=True)
class LaunchPlan:
    """Resolved subprocess launch plan."""

    cmd: list[str]
    cwd: Path
    env: dict[str, str] | None = None


class RuntimeAdapter(ABC):
    """Runtime-specific adapter that builds and launches agent subprocesses."""

    name: str = "unknown"
    default_model: str | None = None
    capabilities: RuntimeCapabilities = RuntimeCapabilities()

    def preflight(self, request: AgentLaunchRequest) -> None:
        """Optional synchronous checks before process launch."""
        del request

    @abstractmethod
    def plan(self, request: AgentLaunchRequest) -> LaunchPlan:
        """Build runtime-specific launch plan."""

    def launch(self, request: AgentLaunchRequest) -> subprocess.Popen[str]:
        self.preflight(request)
        launch_plan = self.plan(request)
        return subprocess.Popen(
            launch_plan.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(launch_plan.cwd),
            env=launch_plan.env,
        )


def node_file_slug(node_id: str) -> str:
    """Filesystem-safe slug for a node id like #12 -> 12."""
    return node_id.lstrip("#")


def write_json_file(path: Path, payload: dict) -> Path:
    """Write JSON payload to disk, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def generate_mcp_config(db_path: Path, agent_id: str, project_dir: Path) -> dict:
    """Generate MCP config that launches the Cord stdio server for a node."""
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

