"""Compatibility wrappers around runtime harness utilities."""

from __future__ import annotations

import subprocess
from pathlib import Path

from cord.runtime.harness.base import MCP_TOOLS, AgentLaunchRequest, generate_mcp_config
from cord.runtime.harness.claude import ClaudeHarness


def launch_agent(
    db_path: Path,
    node_id: str,
    prompt: str,
    work_dir: Path | None = None,
    max_budget_usd: float = 2.0,
    model: str = "sonnet",
    project_dir: Path | None = None,
) -> subprocess.Popen[str]:
    """Launch a Claude subprocess for a node."""
    proj = project_dir or db_path.parent
    request = AgentLaunchRequest(
        db_path=db_path,
        node_id=node_id,
        prompt=prompt,
        work_dir=work_dir,
        max_budget_usd=max_budget_usd,
        model=model,
        project_dir=proj,
    )
    return ClaudeHarness().launch(request)
