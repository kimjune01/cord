"""Tests for CLI argument parsing and backend flags."""

from __future__ import annotations

import pytest

import cord.cli as cli


class _FakeEngine:
    def __init__(self, goal: str, max_budget_usd: float, model: str, harness):
        self.goal = goal
        self.max_budget_usd = max_budget_usd
        self.model = model
        self.harness = harness
        self.ran = False

    def run(self) -> None:
        self.ran = True


def test_backend_flag_before_command(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_resolve_harness(*, force_amp: bool, force_claude: bool):
        captured["flags"] = (force_amp, force_claude)
        return "HARNESS"

    def _fake_engine(goal: str, max_budget_usd: float, model: str, harness):
        captured["engine_args"] = (goal, max_budget_usd, model, harness)
        return _FakeEngine(goal, max_budget_usd, model, harness)

    monkeypatch.setattr(cli, "resolve_harness", _fake_resolve_harness)
    monkeypatch.setattr(cli, "Engine", _fake_engine)
    monkeypatch.setattr(cli.sys, "argv", ["cord", "--amp", "run", "Print ok"])

    cli.main()

    assert captured["flags"] == (True, False)
    assert captured["engine_args"] == ("Print ok", 2.0, "sonnet", "HARNESS")


def test_missing_run_goal_exits(monkeypatch):
    monkeypatch.setattr(cli.sys, "argv", ["cord", "run", "--amp"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
