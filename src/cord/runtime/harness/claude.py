"""Claude CLI harness implementation."""

from __future__ import annotations

from pathlib import Path

from cord.runtime.harness.base import (
    MCP_TOOLS,
    AgentHarness,
    AgentLaunchRequest,
    LaunchSpec,
    generate_mcp_config,
    node_file_slug,
    write_json_file,
)


class ClaudeHarness(AgentHarness):
    """Launch agents through Claude Code CLI."""

    def build_launch_spec(self, request: AgentLaunchRequest) -> LaunchSpec:
        proj = request.project_dir
        config_dir = request.db_path.parent / ".cord"
        config_path = config_dir / f"mcp-{node_file_slug(request.node_id)}.json"
        mcp_config = generate_mcp_config(request.db_path, request.node_id, proj)
        write_json_file(config_path, mcp_config)

        cmd = [
            "claude",
            "-p",
            request.prompt,
            "--model",
            request.model,
            "--mcp-config",
            str(config_path),
            "--allowedTools",
            " ".join(MCP_TOOLS),
            "--dangerously-skip-permissions",
            "--max-budget-usd",
            str(request.max_budget_usd),
        ]
        cwd = request.work_dir or proj
        return LaunchSpec(cmd=cmd, cwd=cwd)
