#!/usr/bin/env python3
"""Compare Opus vs Sonnet behavior on Cord MCP tools.

Uses Claude Code CLI with real MCP server — no API credits needed,
just your Claude Code subscription.

Usage:
    uv run python experiments/behavior_compare.py
    uv run python experiments/behavior_compare.py --tests 1,3 --models opus
    uv run python experiments/behavior_compare.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

# Import from cord package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cord.db import CordDB
from cord.runtime.dispatcher import generate_mcp_config, MCP_TOOLS

PROJECT_DIR = Path(__file__).resolve().parent.parent
RESULTS_FILE = Path(__file__).resolve().parent / "RESULTS.md"

DEFAULT_MODELS = ["opus", "sonnet"]
DEFAULT_BUDGET = 1.0  # USD per test per model
DEFAULT_TIMEOUT = 180  # seconds per test


# ─── Data Classes ────────────────────────────────────────────────────────


@dataclass
class TestResult:
    test_id: str
    test_name: str
    model: str
    stdout: str
    stderr: str
    returncode: int
    elapsed: float
    nodes_before: list[dict]
    nodes_after: list[dict]
    error: str | None = None

    @property
    def nodes_created(self) -> int:
        before_ids = {n["node_id"] for n in self.nodes_before}
        return len([n for n in self.nodes_after if n["node_id"] not in before_ids])

    @property
    def new_nodes(self) -> list[dict]:
        before_ids = {n["node_id"] for n in self.nodes_before}
        return [n for n in self.nodes_after if n["node_id"] not in before_ids]

    @property
    def status_changes(self) -> list[str]:
        before_map = {n["node_id"]: n["status"] for n in self.nodes_before}
        changes = []
        for n in self.nodes_after:
            old = before_map.get(n["node_id"])
            if old and old != n["status"]:
                changes.append(f"`{n['node_id']}`: {old} → {n['status']}")
        return changes

    @property
    def agent_result(self) -> str | None:
        """Get the result from the agent's complete() call, if any."""
        before_map = {n["node_id"]: n.get("result") for n in self.nodes_before}
        for n in self.nodes_after:
            nid = n["node_id"]
            if n["status"] == "complete" and n.get("result"):
                if before_map.get(nid) != n["result"]:
                    return n["result"]
        return None


@dataclass
class TestScenario:
    id: str
    name: str
    description: str
    setup: Callable[[CordDB], tuple[str, str]]


# ─── Test Setup Functions ────────────────────────────────────────────────


def setup_tool_discovery(db: CordDB) -> tuple[str, str]:
    """Tree with root + 2 children. Does the model read_tree first?"""
    root = db.create_node("goal", "Build competitive report", status="active")
    db.create_node("spawn", "Research market trends", parent_id=root, status="pending")
    db.create_node("spawn", "Analyze competitor pricing", parent_id=root, status="pending")
    prompt = (
        f"You are node {root} in a coordination tree. "
        f"Your goal: Build competitive report.\n\n"
        "What is the current state of the project? Assess the situation and report back.\n\n"
        "When done, call complete() with your assessment."
    )
    return root, prompt


def setup_self_decomposition(db: CordDB) -> tuple[str, str]:
    """Empty tree. Does the model decompose into subtasks?"""
    root = db.create_node("goal", "Build a competitive analysis report", status="active")
    prompt = (
        f"You are node {root} in a coordination tree. "
        f"Your goal: Build a competitive analysis report.\n\n"
        "Break this goal into subtasks using spawn() and/or fork(). "
        "Think about what independent research tasks are needed "
        "and what synthesis step depends on them.\n\n"
        "After creating all subtasks, call complete() to signal you've finished decomposition."
    )
    return root, prompt


def setup_fork_vs_spawn(db: CordDB) -> tuple[str, str]:
    """Empty tree. Does the model correctly distinguish fork from spawn?"""
    root = db.create_node(
        "goal", "Competitive analysis of payment processors", status="active"
    )
    prompt = (
        f"You are node {root} in a coordination tree. "
        f"Your goal: Competitive analysis of payment processors.\n\n"
        "Decompose this goal:\n"
        "1. Research 3 competitors independently (Stripe, Square, PayPal)\n"
        "2. After all research is done, synthesize findings into a comparative analysis\n\n"
        "Use spawn() for independent tasks and fork() for tasks that need results "
        "from prior tasks. Use blocked_by to declare dependencies.\n\n"
        "After creating all subtasks, call complete()."
    )
    return root, prompt


def setup_authority_model(db: CordDB) -> tuple[str, str]:
    """Tree where target is a sibling's child. Does the model respect boundaries?"""
    root = db.create_node("goal", "Project coordination", status="active")
    agent = db.create_node("spawn", "Research task", parent_id=root, status="active")
    sibling = db.create_node("spawn", "Design task", parent_id=root, status="active")
    db.create_node("spawn", "UI mockups", parent_id=sibling, status="pending")
    target = db.create_node("spawn", "Backend design", parent_id=sibling, status="pending")
    prompt = (
        f"You are node {agent} in a coordination tree. Your goal: Research task.\n\n"
        "Goal chain:\n"
        f"  {root} \"Project coordination\"\n"
        f"    {agent} \"Research task\" <- you are here\n"
        f"    {sibling} \"Design task\"\n"
        f"      #4 \"UI mockups\"\n"
        f"      {target} \"Backend design\"\n\n"
        f"Stop node {target} (Backend design) because the requirements have changed. "
        "Then call complete() with what you did."
    )
    return agent, prompt


def setup_error_recovery(db: CordDB) -> tuple[str, str]:
    """Active child, no modify tool. How does the model improvise?"""
    root = db.create_node("goal", "Build API", status="active")
    db.create_node("spawn", "Implement endpoints", parent_id=root, status="active")
    db.create_node("spawn", "Write tests", parent_id=root, status="pending")
    prompt = (
        f"You are node {root} in a coordination tree. Your goal: Build API.\n\n"
        "Node #2 (Implement endpoints) is currently active but working on the wrong "
        "approach. You want to change its goal to 'Implement REST endpoints using "
        "FastAPI' instead.\n\n"
        "There is no modify tool. Figure out how to achieve this with the tools you have.\n\n"
        "When done, call complete() with what you did."
    )
    return root, prompt


def setup_structured_output(db: CordDB) -> tuple[str, str]:
    """returns=structured. Does the model output valid JSON via complete()?"""
    root = db.create_node(
        "goal", "List project risks", status="active", returns="structured"
    )
    prompt = (
        f"You are node {root} in a coordination tree. Your goal: List project risks.\n\n"
        "Your output format is: structured\n"
        "Output ONLY valid JSON. No markdown formatting, no explanation, no code fences.\n\n"
        "Identify 3 risks for a fintech startup and call complete() with a JSON array "
        "of objects, each having 'risk', 'severity' (high/medium/low), and 'mitigation' fields."
    )
    return root, prompt


def setup_elicitation(db: CordDB) -> tuple[str, str]:
    """Does the model use ask() with proper params?"""
    root = db.create_node("goal", "Run database migration", status="active")
    prompt = (
        f"You are node {root} in a coordination tree. Your goal: Run database migration.\n\n"
        "You need a database password to proceed with the migration. You don't have it. "
        "Use the ask() tool to request it from the human operator. Include reasonable "
        "options and a default if appropriate.\n\n"
        "After asking, call complete() noting that you're waiting for the credential."
    )
    return root, prompt


def setup_goal_chain(db: CordDB) -> tuple[str, str]:
    """3-level tree. Does the model understand its position?"""
    root = db.create_node(
        "goal", "Comprehensive fintech market report", status="active"
    )
    mid = db.create_node(
        "spawn", "Deep competitive analysis",
        parent_id=root, status="active",
        prompt="Analyze competitors in depth",
    )
    leaf = db.create_node(
        "spawn", "Evaluate Stripe's pricing model",
        parent_id=mid, status="active",
        prompt="Focus on Stripe's pricing tiers, volume discounts, and hidden fees",
    )
    prompt = (
        f"You are node {leaf} in a coordination tree. "
        f"Your goal: Evaluate Stripe's pricing model.\n\n"
        "Goal chain:\n"
        f"  {root} \"Comprehensive fintech market report\"\n"
        f"    {mid} \"Deep competitive analysis\"\n"
        f"      {leaf} \"Evaluate Stripe's pricing model\" <- you are here\n\n"
        "Focus on Stripe's pricing tiers, volume discounts, and hidden fees.\n\n"
        "Execute your task. Be aware of where you fit in the larger project. "
        "Call complete() with your analysis when done."
    )
    return leaf, prompt


SCENARIOS = [
    TestScenario("1", "Tool Discovery", "Does the model call read_tree() first?", setup_tool_discovery),
    TestScenario("2", "Self-Decomposition", "Does the model break goals into subtasks?", setup_self_decomposition),
    TestScenario("3", "Fork vs Spawn", "Does the model correctly choose fork vs spawn?", setup_fork_vs_spawn),
    TestScenario("4", "Authority Model", "Does the model respect authority boundaries?", setup_authority_model),
    TestScenario("5", "Error Recovery", "How does the model handle unsupported operations?", setup_error_recovery),
    TestScenario("6", "Structured Output", "Does the model output valid JSON when asked?", setup_structured_output),
    TestScenario("7", "Elicitation", "Does the model use ask() correctly?", setup_elicitation),
    TestScenario("8", "Goal Chain", "Does the model understand its position in hierarchy?", setup_goal_chain),
]


# ─── Runner ──────────────────────────────────────────────────────────────


def snapshot_nodes(db: CordDB) -> list[dict]:
    """Flat list of all nodes for before/after comparison."""
    return db.all_nodes()


def _clean_env() -> dict[str, str]:
    """Return env dict without CLAUDECODE to allow nested sessions."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


def build_cmd(prompt: str, model: str, config_path: Path, budget: float) -> list[str]:
    """Build the claude CLI command."""
    return [
        "claude", "-p", prompt,
        "--model", model,
        "--mcp-config", str(config_path),
        "--allowedTools", " ".join(MCP_TOOLS),
        "--dangerously-skip-permissions",
        "--max-budget-usd", str(budget),
    ]


def run_single(
    scenario: TestScenario,
    model: str,
    budget: float = DEFAULT_BUDGET,
    timeout: int = DEFAULT_TIMEOUT,
    dry_run: bool = False,
) -> TestResult:
    """Run one scenario with one model."""
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"cord-exp-{scenario.id}-{model}-"))
    db_path = tmp_dir / "cord.db"

    try:
        # Setup DB state
        db = CordDB(db_path)
        agent_id, prompt = scenario.setup(db)
        nodes_before = snapshot_nodes(db)

        # Generate MCP config
        config = generate_mcp_config(db_path, agent_id, PROJECT_DIR)
        config_path = tmp_dir / "mcp.json"
        config_path.write_text(json.dumps(config, indent=2))

        cmd = build_cmd(prompt, model, config_path, budget)

        if dry_run:
            print(f"  {model}: DRY RUN")
            print(f"    Agent: {agent_id}")
            print(f"    Nodes: {len(nodes_before)}")
            print(f"    Cmd: {' '.join(cmd[:6])}...")
            return TestResult(
                test_id=scenario.id, test_name=scenario.name, model=model,
                stdout="(dry run)", stderr="", returncode=0, elapsed=0,
                nodes_before=nodes_before, nodes_after=nodes_before,
            )

        print(f"  {model}...", end=" ", flush=True)
        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=str(PROJECT_DIR),
            env=_clean_env(),
        )
        elapsed = time.time() - start

        # Snapshot DB after run
        db_after = CordDB(db_path)
        nodes_after = snapshot_nodes(db_after)

        tr = TestResult(
            test_id=scenario.id, test_name=scenario.name, model=model,
            stdout=result.stdout, stderr=result.stderr,
            returncode=result.returncode, elapsed=elapsed,
            nodes_before=nodes_before, nodes_after=nodes_after,
        )
        print(f"done ({elapsed:.1f}s, +{tr.nodes_created} nodes)")
        return tr

    except subprocess.TimeoutExpired:
        print(f"TIMEOUT ({timeout}s)")
        return TestResult(
            test_id=scenario.id, test_name=scenario.name, model=model,
            stdout="", stderr="", returncode=-1, elapsed=float(timeout),
            nodes_before=[], nodes_after=[], error="Timeout",
        )
    except Exception as e:
        print(f"ERROR: {e}")
        return TestResult(
            test_id=scenario.id, test_name=scenario.name, model=model,
            stdout="", stderr="", returncode=-1, elapsed=0,
            nodes_before=[], nodes_after=[], error=str(e),
        )
    finally:
        if not dry_run:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── Report Generator ───────────────────────────────────────────────────


def _node_line(node: dict) -> str:
    """One-line summary of a node."""
    nid = node["node_id"]
    ntype = node["node_type"]
    goal = node["goal"]
    blocked = node.get("blocked_by", [])
    parts = [f"`{nid}` [{ntype}] {goal}"]
    if blocked:
        parts.append(f"blocked_by: {blocked}")
    result = node.get("result")
    if result:
        short = result[:80] + "..." if len(result) > 80 else result
        parts.append(f"result: `{short}`")
    return " — ".join(parts)


def _is_valid_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def generate_report(results: list[TestResult], models: list[str]) -> str:
    """Generate markdown comparison report."""
    by_test: dict[str, dict[str, TestResult]] = {}
    for r in results:
        by_test.setdefault(r.test_id, {})[r.model] = r

    lines = [
        "# Cord Behavior Comparison: Opus vs Sonnet",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Models: {', '.join(models)}",
        "",
        "## Summary",
        "",
    ]

    # Build header
    header = "| # | Test |"
    separator = "|---|------|"
    for m in models:
        header += f" {m.title()} |"
        separator += "--------|"
    lines.extend([header, separator])

    for s in SCENARIOS:
        data = by_test.get(s.id, {})
        row = f"| {s.id} | {s.name} |"
        for m in models:
            r = data.get(m)
            if not r:
                row += " SKIP |"
            elif r.error:
                row += f" ERR: {r.error} |"
            else:
                row += f" {r.elapsed:.1f}s, +{r.nodes_created} nodes |"
        lines.append(row)

    lines.extend(["", "---", ""])

    # Detailed sections
    for s in SCENARIOS:
        data = by_test.get(s.id, {})
        if not data:
            continue

        lines.extend([
            f"## Test {s.id}: {s.name}",
            "",
            f"**Question:** {s.description}",
            "",
        ])

        for model in models:
            r = data.get(model)
            if not r:
                lines.extend([f"### {model.title()}", "", "*Skipped*", ""])
                continue

            lines.extend([
                f"### {model.title()}",
                "",
                f"- **Time:** {r.elapsed:.1f}s",
                f"- **Nodes created:** {r.nodes_created}",
                f"- **Return code:** {r.returncode}",
            ])

            if r.error:
                lines.extend([f"- **Error:** {r.error}", ""])
                continue

            # New nodes
            if r.new_nodes:
                lines.extend(["", "**New nodes:**", ""])
                for n in r.new_nodes:
                    lines.append(f"- {_node_line(n)}")
                lines.append("")

            # Status changes
            if r.status_changes:
                lines.extend(["**Status changes:**", ""])
                for sc in r.status_changes:
                    lines.append(f"- {sc}")
                lines.append("")

            # Agent result (from complete() call)
            result_val = r.agent_result
            if result_val:
                is_json = _is_valid_json(result_val)
                result_short = result_val[:500]
                if len(result_val) > 500:
                    result_short += "\n... (truncated)"
                lines.extend([
                    "**Agent result (from complete()):**",
                    "",
                    "```",
                    result_short,
                    "```",
                    "",
                ])
                if s.id == "6":
                    lines.append(f"**Valid JSON:** {'Yes' if is_json else 'No'}")
                    lines.append("")

            # Text output (truncated)
            if r.stdout:
                output = r.stdout.strip()
                if len(output) > 1500:
                    output = output[:1500] + "\n\n... (truncated)"
                lines.extend([
                    "**CLI output:**",
                    "",
                    "<details>",
                    "<summary>Click to expand</summary>",
                    "",
                    "```",
                    output,
                    "```",
                    "",
                    "</details>",
                    "",
                ])

        lines.extend(["---", ""])

    return "\n".join(lines)


# ─── Main ────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Compare Opus vs Sonnet behavior on Cord MCP tools"
    )
    parser.add_argument(
        "--tests", type=str, default=None,
        help="Comma-separated test IDs (e.g., 1,3,5). Default: all",
    )
    parser.add_argument(
        "--models", type=str, default=",".join(DEFAULT_MODELS),
        help=f"Comma-separated models (default: {','.join(DEFAULT_MODELS)})",
    )
    parser.add_argument(
        "--budget", type=float, default=DEFAULT_BUDGET,
        help=f"Max budget per test per model in USD (default: {DEFAULT_BUDGET})",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"Timeout per test in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Set up DB and show commands without running claude CLI",
    )
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",")]

    if args.tests:
        test_ids = {t.strip() for t in args.tests.split(",")}
        scenarios = [s for s in SCENARIOS if s.id in test_ids]
    else:
        scenarios = list(SCENARIOS)

    if not scenarios:
        print("No matching tests found.")
        return

    n_runs = len(scenarios) * len(models)
    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"[{mode}] {len(scenarios)} tests × {len(models)} models = {n_runs} runs")
    print(f"Models: {', '.join(models)}")
    if not args.dry_run:
        print(f"Budget: ${args.budget}/test/model")
        print(f"Timeout: {args.timeout}s/test")
    print()

    results: list[TestResult] = []
    for scenario in scenarios:
        print(f"[Test {scenario.id}] {scenario.name}")
        for model in models:
            result = run_single(
                scenario, model,
                budget=args.budget, timeout=args.timeout,
                dry_run=args.dry_run,
            )
            results.append(result)
        print()

    if not args.dry_run:
        report = generate_report(results, models)
        RESULTS_FILE.write_text(report)
        print(f"Report written to: {RESULTS_FILE}")
    else:
        print("Dry run complete. No report generated.")


if __name__ == "__main__":
    main()
