"""Codex App Server runtime adapter."""

from __future__ import annotations

import sys

from cord.runtime.harness.base import (
    AgentLaunchRequest,
    LaunchPlan,
    RuntimeAdapter,
    RuntimeCapabilities,
    node_file_slug,
)


def _codex_mcp_args(request: AgentLaunchRequest) -> list[str]:
    return [
        "run",
        "--directory",
        str(request.project_dir.resolve()),
        "cord-mcp-server",
        "--db-path",
        str(request.db_path.resolve()),
        "--agent-id",
        request.node_id,
    ]


class CodexAppServerAdapter(RuntimeAdapter):
    name = "codex-app-server"
    default_model = "gpt-5.2-codex"
    capabilities = RuntimeCapabilities(
        supports_model=True,
        supports_budget=False,
        supports_allowed_tools=False,
        requires_mcp_config=False,
    )

    def plan(self, request: AgentLaunchRequest) -> LaunchPlan:
        proj = request.project_dir
        config_dir = request.db_path.parent / ".cord"
        config_dir.mkdir(parents=True, exist_ok=True)

        prompt_path = config_dir / f"prompt-{node_file_slug(request.node_id)}.txt"
        prompt_path.write_text(request.prompt)

        cmd = [
            sys.executable,
            "-m",
            "cord.runtime.codex_app_server_worker",
            "--prompt-file",
            str(prompt_path.resolve()),
            "--project-dir",
            str((request.work_dir or proj).resolve()),
            "--mcp-command",
            "uv",
        ]

        for arg in _codex_mcp_args(request):
            # Ensure leading-dash values are treated as the value, not a new flag.
            cmd.append(f"--mcp-arg={arg}")

        if request.model:
            cmd.extend(["--model", request.model])

        return LaunchPlan(cmd=cmd, cwd=(request.work_dir or proj))

