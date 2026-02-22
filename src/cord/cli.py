"""CLI for cord: cord run "goal" [options]."""

from __future__ import annotations

import sys
from pathlib import Path

from cord.runtime.engine import Engine
from cord.runtime.harness.registry import (
    default_model_for_runtime,
    default_runtime,
    runtime_names,
)


RUNTIME_FLAG_ALIASES = {
    "--amp": "amp",
    "--claude": "claude",
    "--codex": "codex-app-server",
}


def _parse_run_args(args: list[str]) -> tuple[str, float, str | None, str]:
    """Parse run args in any order."""
    goal: str | None = None
    budget = 2.0
    model: str | None = None
    runtime = default_runtime()

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

        if arg == "--runtime":
            if i + 1 >= len(args):
                raise ValueError("--runtime requires a value")
            runtime = args[i + 1]
            i += 2
            continue

        if arg in RUNTIME_FLAG_ALIASES:
            runtime = RUNTIME_FLAG_ALIASES[arg]
            i += 1
            continue

        if arg.startswith("--"):
            raise ValueError(f"Unknown option for run: {arg}")

        if goal is not None:
            raise ValueError(f"Unexpected extra argument: {arg}")
        goal = arg
        i += 1

    if not goal:
        raise ValueError("Missing goal. Provide text or a goal file path.")

    supported = set(runtime_names())
    if runtime not in supported:
        raise ValueError(
            f"Unknown runtime: {runtime}. Expected one of: {', '.join(runtime_names())}"
        )

    if model is None:
        model = default_model_for_runtime(runtime)

    return goal, budget, model, runtime


def main() -> None:
    """CLI entry point: cord run "goal" [--budget <usd>] [--model <model>] [--runtime <runtime>]."""
    args = sys.argv[1:]

    runtime_hint = "|".join(runtime_names())
    if not args or args[0] in ("-h", "--help", "help"):
        print("Usage:")
        print(
            f'  cord run "goal description" [--budget <usd>] [--model <model>] [--runtime <{runtime_hint}>]'
        )
        print(
            f'  cord run plan.md [--budget <usd>] [--model <model>] [--runtime <{runtime_hint}>]'
        )
        print("  cord --amp run \"goal description\"")
        print("  cord --claude run \"goal description\"")
        print("  cord --codex run \"goal description\"")
        sys.exit(0)

    preselected_runtime: str | None = None
    while args and args[0] in RUNTIME_FLAG_ALIASES:
        preselected_runtime = RUNTIME_FLAG_ALIASES[args[0]]
        args = args[1:]

    command = args[0]

    if command == "run":
        try:
            goal_arg, budget, model, runtime = _parse_run_args(args[1:])
            if preselected_runtime:
                runtime = preselected_runtime
                if "--model" not in args:
                    model = default_model_for_runtime(runtime)
        except ValueError as exc:
            print(
                str(exc),
                file=sys.stderr,
            )
            sys.exit(1)

        goal_path = Path(goal_arg)
        if goal_path.exists() and goal_path.is_file():
            goal = goal_path.read_text().strip()
        else:
            goal = goal_arg

        engine = Engine(
            goal,
            max_budget_usd=budget,
            model=model,
            runtime=runtime,
        )
        engine.run()

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Commands: run", file=sys.stderr)
        sys.exit(1)
