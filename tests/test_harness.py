"""Tests for runtime harness selection and command construction."""

from __future__ import annotations

import json

import pytest

from cord.runtime.harness.amp import AmpHarness
from cord.runtime.harness.base import AgentLaunchRequest, MCP_TOOLS
from cord.runtime.harness.claude import ClaudeHarness
from cord.runtime.harness.factory import select_backend


def _which_map(available: set[str]):
    def _which(binary: str) -> str | None:
        return f"/usr/local/bin/{binary}" if binary in available else None

    return _which


class TestHarnessSelection:
    def test_auto_detect_prefers_amp(self):
        backend = select_backend(which=_which_map({"amp", "claude"}))
        assert backend == "amp"

    def test_explicit_flag_precedence(self):
        backend = select_backend(force_claude=True, which=_which_map({"amp", "claude"}))
        assert backend == "claude"

    def test_conflicting_flags_rejected(self):
        with pytest.raises(ValueError, match="--claude or --amp"):
            select_backend(
                force_claude=True, force_amp=True, which=_which_map({"amp", "claude"})
            )

    def test_no_backend_available_rejected(self):
        with pytest.raises(ValueError, match="No supported agent CLI"):
            select_backend(which=_which_map(set()))


class TestHarnessCommands:
    def test_claude_command_generation(self, tmp_path):
        db_path = tmp_path / "cord.db"
        request = AgentLaunchRequest(
            db_path=db_path,
            node_id="#12",
            prompt="Do the task",
            model="opus",
            max_budget_usd=3.5,
            project_dir=tmp_path,
        )

        spec = ClaudeHarness().build_launch_spec(request)

        assert spec.cmd[0] == "claude"
        assert "--mcp-config" in spec.cmd
        assert "--allowedTools" in spec.cmd
        assert " ".join(MCP_TOOLS) in spec.cmd
        assert "--dangerously-skip-permissions" in spec.cmd
        assert "--max-budget-usd" in spec.cmd
        assert "3.5" in spec.cmd

        config_idx = spec.cmd.index("--mcp-config") + 1
        config_path = spec.cmd[config_idx]
        assert config_path.endswith("mcp-12.json")

    def test_amp_command_generation(self, tmp_path, monkeypatch):
        db_path = tmp_path / "cord.db"
        default_settings_path = tmp_path / "amp-default-settings.json"
        default_settings_path.write_text(
            json.dumps(
                {
                    "amp.permissions": [
                        {"tool": "Bash", "action": "ask"},
                    ]
                }
            )
        )
        monkeypatch.setenv("AMP_SETTINGS_FILE", str(default_settings_path))

        request = AgentLaunchRequest(
            db_path=db_path,
            node_id="#7",
            prompt="Do the task",
            project_dir=tmp_path,
        )

        spec = AmpHarness().build_launch_spec(request)

        assert spec.cmd[0] == "amp"
        assert spec.cmd[1] == "-x"
        assert "--mcp-config" in spec.cmd
        assert "--settings-file" in spec.cmd
        assert "--no-color" in spec.cmd
        assert spec.env is not None
        assert spec.env["TERM"] == "dumb"

        settings_idx = spec.cmd.index("--settings-file") + 1
        settings_path = spec.cmd[settings_idx]
        mcp_idx = spec.cmd.index("--mcp-config") + 1
        mcp_path = spec.cmd[mcp_idx]
        settings = json.loads((tmp_path / ".cord" / "amp-settings-7.json").read_text())
        mcp_config = json.loads((tmp_path / ".cord" / "mcp-7.json").read_text())

        assert settings_path.endswith("amp-settings-7.json")
        assert mcp_path.endswith("mcp-7.json")
        assert "cord" in mcp_config
        assert settings["amp.tools.enable"] == MCP_TOOLS
        assert settings["amp.permissions"] == [{"tool": "Bash", "action": "ask"}]
