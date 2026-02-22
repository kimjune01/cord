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

    # 2. Results from needed nodes
    needs = node["needs"]
    if needs:
        results = db.get_completed_results(needs)
        if results:
            parts.append("Results from needed nodes:")
            parts.append("")
            for dep_id, result in results.items():
                dep = db.get_node(dep_id)
                dep_label = f"{dep_id} \"{dep['goal']}\"" if dep else dep_id
                parts.append(f"--- {dep_label} ---")
                parts.append(result)
                parts.append("")

    # 3. Node's own prompt
    if node.get("prompt"):
        parts.append("Your task:")
        parts.append(node["prompt"])
        parts.append("")

    # 4. MCP tool instructions
    parts.append("You have MCP tools available for coordination:")
    parts.append("- create(goal, prompt, returns, needs): Create a child task. Use needs to list node IDs it depends on.")
    parts.append("- complete(result): Mark your task done with a result")
    parts.append("- read_tree(): View the full coordination tree")
    parts.append("")
    parts.append("WORKFLOW:")
    parts.append("1. Assess whether your task has independent parts")
    parts.append("2. If yes: create children, then call complete()")
    parts.append("3. If no: do the work, then call complete()")
    parts.append("")
    parts.append("needs = child waits for listed nodes to complete. Their full results are injected into the child's prompt.")
    parts.append("If a child would need results from many nodes, create an intermediate task to synthesize them first.")
    parts.append("Prefer deeper trees over wide fan-ins — each level of depth is a natural compression boundary.")
    parts.append("")
    parts.append("IMPORTANT: When you are done, you MUST call the `complete` tool with your result.")
    parts.append("")

    # 5. Output format instructions
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
