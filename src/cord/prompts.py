"""Prompt assembly for agent invocations."""

from __future__ import annotations

from cord.db import CordDB


def build_agent_prompt(db: CordDB, node_id: str) -> str:
    """Build the full prompt for an agent invocation."""
    node = db.get_node(node_id)
    if not node:
        return ""

    parts = []

    # 1. Identity and goal
    parts.append(f"You are node {node_id} in a coordination tree.")
    parts.append(f"Your goal: {node['goal']}")
    parts.append("")

    # Goal chain for context
    goal_chain = db.get_goal_chain(node_id)
    if len(goal_chain) > 1:
        parts.append("Goal chain:")
        for i, (nid, goal) in enumerate(goal_chain):
            indent = "  " * i
            marker = " <- your task" if nid == node_id else ""
            parts.append(f"  {indent}{nid} \"{goal}\"{marker}")
        parts.append("")

    # 2. Injected results from dependencies
    blocked_by = node["blocked_by"]
    if blocked_by:
        results = db.get_completed_results(blocked_by)
        if results:
            parts.append("Results from completed dependencies:")
            parts.append("")
            for dep_id, result in results.items():
                dep = db.get_node(dep_id)
                dep_label = f"{dep_id} \"{dep['goal']}\"" if dep else dep_id
                parts.append(f"--- {dep_label} ---")
                parts.append(result)
                parts.append("")

    # 3. Fork context injection
    if node["node_type"] == "fork":
        _inject_fork_context(db, node, parts)

    # 4. Node's own prompt
    if node.get("prompt"):
        parts.append("Your task:")
        parts.append(node["prompt"])
        parts.append("")

    # 5. MCP tool instructions
    parts.append("You have MCP tools available for coordination:")
    parts.append("- spawn(goal, prompt, returns, blocked_by): Create a child task (scoped context — child only sees its prompt)")
    parts.append("- fork(goal, prompt, returns, blocked_by): Create a child that inherits completed sibling results")
    parts.append("- complete(result): Mark your task done with a result")
    parts.append("- read_tree(): View the full coordination tree")
    parts.append("")
    parts.append("WORKFLOW:")
    parts.append("1. Assess whether your task has independent parts")
    parts.append("2. If yes: spawn/fork children, then call complete()")
    parts.append("3. If no: do the work, then call complete()")
    parts.append("")
    parts.append("spawn = child with clean context. fork = child that sees completed sibling results.")
    parts.append("blocked_by = child waits for listed nodes to complete before starting.")
    parts.append("")
    parts.append("IMPORTANT: When you are done, you MUST call the `complete` tool with your result.")
    parts.append("")

    # 6. Output format instructions
    returns = node.get("returns") or "text"
    parts.append(_output_instructions(returns))

    return "\n".join(parts)


def build_synthesis_prompt(db: CordDB, node_id: str) -> str:
    """Build prompt for synthesis phase (after children complete)."""
    node = db.get_node(node_id)
    if not node:
        return ""

    parts = []

    parts.append(f"You are node {node_id}: \"{node['goal']}\"")
    parts.append("")
    parts.append("Your child tasks have completed. Here are their results:")
    parts.append("")

    children = db.get_children(node_id)
    for child in children:
        if child["status"] == "complete" and child.get("result"):
            parts.append(f"--- {child['node_id']} \"{child['goal']}\" ---")
            parts.append(child["result"])
            parts.append("")

    if node.get("prompt"):
        parts.append("Original instructions:")
        parts.append(node["prompt"])
        parts.append("")

    parts.append("Synthesize the results from your child tasks into your final output.")
    parts.append("")
    parts.append("IMPORTANT: When you are done, you MUST call the `complete` tool with your result.")
    parts.append("")

    returns = node.get("returns") or "text"
    parts.append(_output_instructions(returns))

    return "\n".join(parts)


def _inject_fork_context(db: CordDB, node: dict, parts: list[str]) -> None:
    """For fork nodes, inject all available context from siblings."""
    parent_id = node.get("parent_id")
    if not parent_id:
        return

    siblings = db.get_children(parent_id)
    sibling_results = []
    for sib in siblings:
        if sib["node_id"] == node["node_id"]:
            continue
        if sib["status"] == "complete" and sib.get("result"):
            sibling_results.append(sib)

    if sibling_results:
        parts.append("Inherited context (results from sibling tasks):")
        parts.append("")
        for sib in sibling_results:
            parts.append(f"--- {sib['node_id']} \"{sib['goal']}\" ---")
            parts.append(sib["result"])
            parts.append("")


def _output_instructions(returns: str) -> str:
    instructions = {
        "text": "Output your result as plain text.",
        "list": "Output ONLY a JSON array. No markdown formatting, no explanation.",
        "structured": "Output ONLY valid JSON. No markdown formatting, no explanation.",
        "file": "Write your result to a file and output the file path.",
        "boolean": "Output ONLY 'true' or 'false'. No explanation.",
        "approval": "Output ONLY 'approved' or 'rejected'. No explanation.",
    }
    return instructions.get(returns, f"Output your result (expected type: {returns}).")
