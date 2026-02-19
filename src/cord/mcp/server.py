"""MCP server for cord — stdio transport, one per agent.

Each claude CLI spawns its own instance via the MCP config.
State is shared through SQLite (WAL mode for concurrent access).
"""

from __future__ import annotations

import json
import sys

from mcp.server.fastmcp import FastMCP

from cord.db import CordDB

# Parse CLI args
agent_id: str | None = None
db_path: str | None = None

for i, arg in enumerate(sys.argv):
    if arg == "--agent-id" and i + 1 < len(sys.argv):
        agent_id = sys.argv[i + 1]
    if arg == "--db-path" and i + 1 < len(sys.argv):
        db_path = sys.argv[i + 1]


def _get_db() -> CordDB:
    if db_path:
        return CordDB(db_path)
    raise RuntimeError("No --db-path specified")


def _node_to_json(node: dict) -> dict:
    """Convert a node dict to a clean JSON-serializable dict."""
    d: dict = {
        "id": node["node_id"],
        "type": node["node_type"],
        "goal": node["goal"],
        "status": node["status"],
    }
    if node.get("prompt"):
        d["prompt"] = node["prompt"]
    if node.get("returns"):
        d["returns"] = node["returns"]
    if node.get("result"):
        d["result"] = node["result"]
    if node.get("blocked_by"):
        d["blocked_by"] = node["blocked_by"]
    if node.get("children"):
        d["children"] = [_node_to_json(c) for c in node["children"]]
    return d


mcp = FastMCP("cord")


@mcp.tool()
def read_tree() -> str:
    """Returns the full coordination tree as JSON."""
    db = _get_db()
    tree = db.get_tree()
    if not tree:
        return json.dumps({"error": "No tree found"})
    return json.dumps(_node_to_json(tree), indent=2)


@mcp.tool()
def read_node(node_id: str) -> str:
    """Returns a single node's details by ID (e.g. '#1')."""
    db = _get_db()
    node = db.get_node(node_id)
    if not node:
        return json.dumps({"error": f"Node {node_id} not found"})
    return json.dumps(_node_to_json(node), indent=2)


@mcp.tool()
def spawn(goal: str, prompt: str = "", returns: str = "text",
          blocked_by: list[str] | None = None) -> str:
    """Create a spawned child node under your node.
    Use blocked_by to declare dependencies on other node IDs (e.g. ['#2', '#3'])."""
    db = _get_db()
    new_id = db.create_node(
        node_type="spawn",
        goal=goal,
        parent_id=agent_id,
        prompt=prompt,
        returns=returns,
        blocked_by=blocked_by,
    )
    return json.dumps({"created": new_id, "goal": goal})


@mcp.tool()
def fork(goal: str, prompt: str = "", returns: str = "text",
         blocked_by: list[str] | None = None) -> str:
    """Create a forked child node (inherits parent context) under your node.
    Use blocked_by to declare dependencies on other node IDs."""
    db = _get_db()
    new_id = db.create_node(
        node_type="fork",
        goal=goal,
        parent_id=agent_id,
        prompt=prompt,
        returns=returns,
        blocked_by=blocked_by,
    )
    return json.dumps({"created": new_id, "goal": goal})


@mcp.tool()
def complete(result: str = "") -> str:
    """Mark your node as complete with a result. Call this when your task is done."""
    if not agent_id:
        return json.dumps({"error": "No agent_id set"})
    db = _get_db()
    db.complete_node(agent_id, result)
    return json.dumps({"completed": agent_id})


@mcp.tool()
def ask(question: str, options: list[str] | None = None,
        default: str | None = None) -> str:
    """Create an ask node to get input from a human or parent agent."""
    db = _get_db()
    prompt_text = question
    if options:
        prompt_text += "\nOptions: " + ", ".join(options)
    if default:
        prompt_text += f"\nDefault: {default}"
    new_id = db.create_node(
        node_type="ask",
        goal=question,
        parent_id=agent_id,
        prompt=prompt_text,
        status="pending",
    )
    return json.dumps({"created": new_id, "question": question})


@mcp.tool()
def stop(node_id: str) -> str:
    """Cancel a node in your subtree."""
    db = _get_db()
    node = db.get_node(node_id)
    if not node:
        return json.dumps({"error": f"Node {node_id} not found"})
    db.update_status(node_id, "cancelled")
    return json.dumps({"cancelled": node_id})


def main():
    """Entry point for cord-mcp-server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
