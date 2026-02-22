"""Claude CLI runtime adapter."""

from __future__ import annotations

from cord.runtime.harness.base import (
    MCP_TOOLS,
    AgentLaunchRequest,
    LaunchPlan,
    RuntimeAdapter,
    RuntimeCapabilities,
    generate_mcp_config,
    node_file_slug,
    require_binary,
    write_json_file,
)


class ClaudeAdapter(RuntimeAdapter):
    name = "claude"
    default_model = "sonnet"
    capabilities = RuntimeCapabilities(
        supports_model=True,
        supports_budget=True,
        supports_allowed_tools=True,
        requires_mcp_config=True,
    )

    def preflight(self, request: AgentLaunchRequest) -> None:
        del request
        require_binary("claude", self.name)

    def plan(self, request: AgentLaunchRequest) -> LaunchPlan:
        proj = request.project_dir
        resolved_model = request.model or self.default_model or "sonnet"

        config_dir = request.db_path.parent / ".cord"
        config_path = config_dir / f"mcp-{node_file_slug(request.node_id)}.json"
        mcp_config = generate_mcp_config(request.db_path, request.node_id, proj)
        write_json_file(config_path, mcp_config)

        cmd = [
            "claude",
            "-p",
            request.prompt,
            "--model",
            resolved_model,
            "--mcp-config",
            str(config_path),
            "--allowedTools",
            " ".join(MCP_TOOLS),
            "--dangerously-skip-permissions",
            "--max-budget-usd",
            str(request.max_budget_usd),
        ]

        cwd = request.work_dir or proj
        return LaunchPlan(cmd=cmd, cwd=cwd)
