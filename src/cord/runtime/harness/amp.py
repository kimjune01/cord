"""Amp CLI runtime adapter."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

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


class AmpAdapter(RuntimeAdapter):
    name = "amp"
    default_model = None
    capabilities = RuntimeCapabilities(
        supports_model=False,
        supports_budget=False,
        supports_allowed_tools=False,
        requires_mcp_config=True,
    )

    def __init__(self) -> None:
        self._warned_model = False
        self._warned_budget = False

    def preflight(self, request: AgentLaunchRequest) -> None:
        del request
        require_binary("amp", self.name)

    def plan(self, request: AgentLaunchRequest) -> LaunchPlan:
        self._warn_option_gaps(request)

        proj = request.project_dir
        config_dir = request.db_path.parent / ".cord"
        slug = node_file_slug(request.node_id)
        mcp_path = config_dir / f"mcp-{slug}.json"
        settings_path = config_dir / f"amp-settings-{slug}.json"

        mcp_config = generate_mcp_config(request.db_path, request.node_id, proj)
        # Amp expects the mcp server map directly rather than wrapped in mcpServers.
        write_json_file(mcp_path, mcp_config["mcpServers"])

        settings = self._load_base_settings()
        existing_enabled = settings.get("amp.tools.enable")
        enabled: list[str] = []
        if isinstance(existing_enabled, list):
            enabled = [v for v in existing_enabled if isinstance(v, str)]
        for tool in MCP_TOOLS:
            if tool not in enabled:
                enabled.append(tool)
        settings["amp.tools.enable"] = enabled
        write_json_file(settings_path, settings)

        cmd = [
            "amp",
            "-x",
            request.prompt,
            "--mcp-config",
            str(mcp_path),
            "--settings-file",
            str(settings_path),
            "--no-color",
        ]

        env = os.environ.copy()
        env["TERM"] = "dumb"
        cwd = request.work_dir or proj
        return LaunchPlan(cmd=cmd, cwd=cwd, env=env)

    def _warn_option_gaps(self, request: AgentLaunchRequest) -> None:
        if request.model and not self._warned_model:
            print(
                "Warning: --model is not supported by amp runtime; ignoring model override.",
                file=sys.stderr,
            )
            self._warned_model = True
        if request.max_budget_usd != 2.0 and not self._warned_budget:
            print(
                "Warning: --budget is not supported by amp runtime; ignoring budget override.",
                file=sys.stderr,
            )
            self._warned_budget = True

    def _load_base_settings(self) -> dict[str, Any]:
        raw_path = os.environ.get("AMP_SETTINGS_FILE")
        settings_path = (
            Path(raw_path).expanduser()
            if raw_path
            else Path.home() / ".config" / "amp" / "settings.json"
        )
        if not settings_path.exists():
            return {}

        try:
            payload = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            print(
                f"Warning: failed to parse Amp settings file: {settings_path}",
                file=sys.stderr,
            )
            return {}

        if not isinstance(payload, dict):
            print(
                f"Warning: Amp settings must be a JSON object: {settings_path}",
                file=sys.stderr,
            )
            return {}

        return payload
