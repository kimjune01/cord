"""Amp CLI harness implementation."""

from __future__ import annotations

import json
import os
import sys
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


class AmpHarness(AgentHarness):
    """Launch agents through Amp CLI."""

    def __init__(self, mode: str | None = None):
        self.mode = mode
        self._warned_model = False
        self._warned_budget = False

    def build_launch_spec(self, request: AgentLaunchRequest) -> LaunchSpec:
        proj = request.project_dir
        config_dir = request.db_path.parent / ".cord"
        slug = node_file_slug(request.node_id)
        mcp_path = config_dir / f"mcp-{slug}.json"
        settings_path = config_dir / f"amp-settings-{slug}.json"

        mcp_config = generate_mcp_config(request.db_path, request.node_id, proj)
        write_json_file(mcp_path, mcp_config["mcpServers"])
        settings = self._load_base_settings()
        settings.pop("amp.tools.disable", None)
        settings["amp.tools.enable"] = MCP_TOOLS
        write_json_file(
            settings_path,
            settings,
        )

        self._warn_option_gaps(request)

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
        if self.mode:
            cmd.extend(["--mode", self.mode])

        env = os.environ.copy()
        env["TERM"] = "dumb"

        cwd = request.work_dir or proj
        return LaunchSpec(cmd=cmd, cwd=cwd, env=env)

    def _warn_option_gaps(self, request: AgentLaunchRequest) -> None:
        if request.model != "sonnet" and not self._warned_model:
            print(
                "Warning: --model is not mapped to Amp CLI; ignoring model override.",
                file=sys.stderr,
            )
            self._warned_model = True

        if request.max_budget_usd != 2.0 and not self._warned_budget:
            print(
                "Warning: --budget is not mapped to Amp CLI; ignoring budget override.",
                file=sys.stderr,
            )
            self._warned_budget = True

    def _load_base_settings(self) -> dict:
        """Load user's default Amp settings so permissions remain intact."""
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
