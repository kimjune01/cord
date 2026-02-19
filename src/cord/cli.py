"""CLI for cord: cord run "goal" [options]."""

from __future__ import annotations

import sys
from pathlib import Path

from cord.runtime.engine import Engine


def main() -> None:
    """CLI entry point: cord run "goal" [--budget <usd>] [--model <model>]."""
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print("Usage:")
        print('  cord run "goal description" [--budget <usd>] [--model <model>]')
        print('  cord run plan.md [--budget <usd>] [--model <model>]')
        sys.exit(0)

    command = args[0]

    if command == "run":
        if len(args) < 2:
            print('Usage: cord run "goal description" [--budget <usd>] [--model <model>]', file=sys.stderr)
            sys.exit(1)

        goal_arg = args[1]
        goal_path = Path(goal_arg)
        if goal_path.exists() and goal_path.is_file():
            goal = goal_path.read_text().strip()
        else:
            goal = goal_arg

        budget = 2.0
        if "--budget" in args:
            idx = args.index("--budget")
            if idx + 1 < len(args):
                budget = float(args[idx + 1])

        model = "sonnet"
        if "--model" in args:
            idx = args.index("--model")
            if idx + 1 < len(args):
                model = args[idx + 1]

        engine = Engine(goal, max_budget_usd=budget, model=model)
        engine.run()

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Commands: run", file=sys.stderr)
        sys.exit(1)
