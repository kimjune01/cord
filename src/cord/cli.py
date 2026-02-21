"""CLI for cord: cord run "goal" [options]."""

from __future__ import annotations

import sys
from pathlib import Path

from cord.runtime.engine import Engine
from cord.runtime.harness.factory import resolve_harness


USAGE_LINE = (
    'cord run "goal description" [--budget <usd>] [--model <model>] [--amp|--claude]'
)


def _parse_run_args(args: list[str]) -> tuple[str, float, str, bool, bool]:
    """Parse `cord run` options in any order."""
    goal: str | None = None
    budget = 2.0
    model = "sonnet"
    force_amp = False
    force_claude = False

    i = 0
    while i < len(args):
        arg = args[i]

        if arg == "--budget":
            if i + 1 >= len(args):
                raise ValueError("--budget requires a numeric value")
            budget = float(args[i + 1])
            i += 2
            continue

        if arg == "--model":
            if i + 1 >= len(args):
                raise ValueError("--model requires a value")
            model = args[i + 1]
            i += 2
            continue

        if arg == "--amp":
            force_amp = True
            i += 1
            continue

        if arg == "--claude":
            force_claude = True
            i += 1
            continue

        if arg.startswith("--"):
            raise ValueError(f"Unknown option for run: {arg}")

        if goal is not None:
            raise ValueError(f"Unexpected extra argument: {arg}")

        goal = arg
        i += 1

    if not goal:
        raise ValueError(f"Usage: {USAGE_LINE}")

    return goal, budget, model, force_amp, force_claude


def main() -> None:
    """CLI entry point: cord run "goal" [options]."""
    args = sys.argv[1:]

    pre_force_amp = False
    pre_force_claude = False
    while args and args[0] in ("--amp", "--claude"):
        if args[0] == "--amp":
            pre_force_amp = True
        else:
            pre_force_claude = True
        args = args[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print("Usage:")
        print(f"  {USAGE_LINE}")
        print("  cord run plan.md [--budget <usd>] [--model <model>] [--amp|--claude]")
        sys.exit(0)

    command = args[0]

    if command == "run":
        try:
            goal_arg, budget, model, run_force_amp, run_force_claude = _parse_run_args(
                args[1:]
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        force_amp = pre_force_amp or run_force_amp
        force_claude = pre_force_claude or run_force_claude

        goal_path = Path(goal_arg)
        if goal_path.exists() and goal_path.is_file():
            goal = goal_path.read_text().strip()
        else:
            goal = goal_arg

        try:
            harness = resolve_harness(force_amp=force_amp, force_claude=force_claude)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)

        engine = Engine(goal, max_budget_usd=budget, model=model, harness=harness)
        engine.run()

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Commands: run", file=sys.stderr)
        sys.exit(1)
