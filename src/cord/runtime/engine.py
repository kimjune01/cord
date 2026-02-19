"""Main runtime loop for cord execution."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from cord.db import CordDB
from cord.prompts import build_agent_prompt, build_synthesis_prompt
from cord.runtime.dispatcher import launch_agent
from cord.runtime.process_manager import ProcessManager


class Engine:
    """Main execution engine for cord.

    Creates a root goal in SQLite, launches agents, polls for completions.
    """

    def __init__(
        self,
        goal: str,
        db_path: Path | None = None,
        poll_interval: float = 2.0,
        max_budget_usd: float = 2.0,
        model: str = "sonnet",
        project_dir: Path | None = None,
    ):
        self.goal = goal
        self.project_dir = (project_dir or Path.cwd()).resolve()
        self.db_path = db_path or (self.project_dir / ".cord" / "cord.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Fresh DB for each run
        if self.db_path.exists():
            self.db_path.unlink()
        self.poll_interval = poll_interval
        self.max_budget_usd = max_budget_usd
        self.model = model
        self.process_manager = ProcessManager()
        self.db = CordDB(self.db_path)
        self._last_tree_hash = ""

    def run(self) -> None:
        """Run the engine to completion."""
        self._log(f"cord run: {self.goal}")
        self._log("")

        # Create root goal node
        root_id = self.db.create_node(
            node_type="goal",
            goal=self.goal,
            status="active",
        )

        # Launch root agent
        self._launch_node(root_id)
        self._print_tree()

        try:
            self._main_loop()
        except KeyboardInterrupt:
            self._log("\nInterrupted. Cancelling all agents...")
            self.process_manager.cancel_all()
            for node in self.db.all_nodes():
                if node["status"] == "active":
                    self.db.update_status(node["node_id"], "cancelled")
            self._print_tree()

    def _main_loop(self) -> None:
        while True:
            if self.db.is_tree_complete():
                self._print_tree()
                self._log("Done.")
                break

            # Poll completions
            completions = self.process_manager.poll_completions()
            for node_id, return_code, stdout in completions:
                self._handle_completion(node_id, return_code, stdout)

            # Launch ready nodes
            ready = self.db.find_ready_nodes()
            active = self.process_manager.active_node_ids

            for node in ready:
                nid = node["node_id"]
                if nid in active:
                    continue
                if node["node_type"] == "ask":
                    self._handle_ask(node)
                else:
                    self._launch_node(nid)

            self._print_tree()

            # Stuck check
            if self.process_manager.active_count == 0 and not ready:
                pending = [n for n in self.db.all_nodes() if n["status"] == "pending"]
                if pending:
                    self._log(f"Stuck: {len(pending)} pending nodes with unmet dependencies")
                break

            time.sleep(self.poll_interval)

    def _launch_node(self, node_id: str) -> None:
        prompt = build_agent_prompt(self.db, node_id)
        self.db.update_status(node_id, "active")

        process = launch_agent(
            self.db_path,
            node_id,
            prompt,
            max_budget_usd=self.max_budget_usd,
            model=self.model,
            project_dir=self.project_dir,
        )
        self.process_manager.register(node_id, process)

    def _handle_completion(self, node_id: str, return_code: int, stdout: str) -> None:
        node = self.db.get_node(node_id)
        if not node:
            return

        if return_code == 0:
            # Agent completed — check if it already called complete() via MCP
            refreshed = self.db.get_node(node_id)
            if refreshed and refreshed["status"] != "complete":
                # Agent exited without calling complete(), use stdout as result
                self.db.complete_node(node_id, stdout.strip()[:500])

            self._check_synthesis(node_id)
        else:
            if node["status"] != "complete":
                self.db.update_status(node_id, "failed")

    def _check_synthesis(self, completed_node_id: str) -> None:
        """Check if a parent needs synthesis after a child completes."""
        node = self.db.get_node(completed_node_id)
        if not node or not node["parent_id"]:
            return

        parent_id = node["parent_id"]
        children = self.db.get_children(parent_id)

        all_done = all(
            c["status"] in ("complete", "failed", "cancelled")
            for c in children
        )
        if not all_done:
            return

        # Don't synthesize if no children
        if not children:
            return

        successful = [c for c in children if c["status"] == "complete"]
        if not successful:
            self.db.update_status(parent_id, "failed")
            return

        parent = self.db.get_node(parent_id)
        if not parent:
            return

        # Relaunch parent for synthesis
        self.db.update_status(parent_id, "active")
        prompt = build_synthesis_prompt(self.db, parent_id)
        process = launch_agent(
            self.db_path,
            parent_id,
            prompt,
            max_budget_usd=self.max_budget_usd,
            model=self.model,
            project_dir=self.project_dir,
        )
        self.process_manager.register(parent_id, process)

    def _handle_ask(self, node: dict) -> None:
        """Handle an ask node: prompt the human, read input, store answer."""
        self.db.update_status(node["node_id"], "active")
        self._print_tree()

        # Display question
        bold = "\033[1m"
        cyan = "\033[36m"
        reset = "\033[0m"
        dim = "\033[2m"

        print(f"\n{cyan}{bold}? {node['goal']}{reset}", file=sys.stderr)
        if node.get("prompt") and node["prompt"] != node["goal"]:
            # Show options/default from prompt
            for line in node["prompt"].split("\n"):
                if line != node["goal"]:
                    print(f"  {dim}{line}{reset}", file=sys.stderr)
        print(file=sys.stderr)

        try:
            answer = input(f"{cyan}> {reset}").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""

        if not answer and node.get("prompt") and "Default:" in node["prompt"]:
            # Extract default
            for line in node["prompt"].split("\n"):
                if line.startswith("Default:"):
                    answer = line.split(":", 1)[1].strip()

        self.db.complete_node(node["node_id"], answer or "(no answer)")
        self._check_synthesis(node["node_id"])

    # -- TUI --

    def _print_tree(self) -> None:
        """Clear screen and print the colored status tree."""
        tree = self.db.get_tree()
        if not tree:
            return

        # Simple change detection
        h = hash(str(tree))
        if h == self._last_tree_hash:
            return
        self._last_tree_hash = h

        lines = [f"\033[2J\033[H\033[1mcord run\033[0m", ""]
        self._render_node(tree, 0, lines)
        lines.append("")
        active = self.process_manager.active_node_ids
        if active:
            lines.append(f"\033[90m  running: {', '.join(sorted(active))}\033[0m")
        print("\n".join(lines), file=sys.stderr)

    def _render_node(self, node: dict, depth: int, lines: list[str]) -> None:
        prefix = "  " * depth
        color, icon = _status_style(node["status"])
        reset = "\033[0m"
        dim = "\033[2m"
        bold = "\033[1m"

        lines.append(
            f"  {prefix}{color}{icon} {bold}{node['node_id']}{reset} "
            f"{color}[{node['status']}]{reset} "
            f"{dim}{node['node_type'].upper()}{reset} {node['goal']}"
        )

        if node.get("blocked_by"):
            deps = ", ".join(node["blocked_by"])
            lines.append(f"  {prefix}  {dim}blocked-by: {deps}{reset}")

        if node.get("result"):
            preview = node["result"][:60].replace("\n", " ")
            if len(node["result"]) > 60:
                preview += "..."
            lines.append(f"  {prefix}  {dim}result: {preview}{reset}")

        for child in node.get("children", []):
            self._render_node(child, depth + 1, lines)

    def _log(self, message: str) -> None:
        print(message, file=sys.stderr)


def _status_style(status: str) -> tuple[str, str]:
    return {
        "pending":   ("\033[90m", "○"),
        "active":    ("\033[34m", "●"),
        "complete":  ("\033[32m", "✓"),
        "failed":    ("\033[31m", "✗"),
        "cancelled": ("\033[33m", "⊘"),
        "waiting":   ("\033[36m", "?"),
    }.get(status, ("\033[0m", "?"))
