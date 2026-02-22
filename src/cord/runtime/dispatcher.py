"""Compatibility wrappers around runtime adapters."""

from __future__ import annotations

import subprocess
from pathlib import Path

from cord.runtime.harness.base import (
    MCP_TOOLS,
    AgentLaunchRequest,
    generate_mcp_config,
)
from cord.runtime.harness.registry import create_adapter, default_model_for_runtime


def launch_agent(
    db_path: Path,
    node_id: str,
    prompt: str,
    work_dir: Path | None = None,
    max_budget_usd: float = 2.0,
    model: str | None = "sonnet",
    project_dir: Path | None = None,
    runtime: str = "claude",
) -> subprocess.Popen[str]:
    """Launch a node agent using the selected runtime adapter."""
    proj = project_dir or db_path.parent
    resolved_model = model if model is not None else default_model_for_runtime(runtime)
    request = AgentLaunchRequest(
        db_path=db_path,
        node_id=node_id,
        prompt=prompt,
        work_dir=work_dir,
        max_budget_usd=max_budget_usd,
        model=resolved_model,
        project_dir=proj,
    )
    adapter = create_adapter(runtime)
    return adapter.launch(request)
