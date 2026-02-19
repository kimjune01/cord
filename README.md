# Cord

A coordination protocol for trees of Claude Code agents.

One goal in, multiple agents out. They decompose, parallelize, wait on dependencies, and synthesize — all through a shared SQLite database.

## Demo

```
$ cord run "Build a competitive landscape report for fintech" --budget 5.0

cord run

  ● #1 [active] GOAL Build a competitive landscape report for fintech
    ✓ #2 [complete] SPAWN Identify top fintech competitors
      result: Task complete. JSON array with top 10 fintech companies...
    ✓ #3 [complete] SPAWN Research fintech industry trends
      result: Task complete. Compiled trends across regulatory, AI...
    ● #4 [active] FORK Deep competitive analysis
      blocked-by: #2, #3
    ○ #5 [pending] SPAWN Write executive report
      blocked-by: #4

  running: #1, #4
```

The root agent decided to split the work into 4 tasks. #2 and #3 ran in parallel. #4 is a `fork` — it gets the results from both research tasks injected as context. #5 waits for #4. When everything completes, #1 relaunches to synthesize the final report.

No workflow was hardcoded. The agent built this tree at runtime.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated (`claude` command available)
- An Anthropic API key with sufficient credits

## Install

```bash
git clone https://github.com/kimjune01/cord.git
cd cord
uv sync
```

## Usage

```bash
# Give it a goal
cord run "Analyze the pros and cons of Rust vs Go for CLI tools"

# Or point it at a planning doc
cord run plan.md

# Control budget and model
cord run "goal" --budget 5.0 --model opus
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--budget` | 2.0 | Max USD per agent subprocess |
| `--model` | sonnet | Claude model (sonnet, opus, haiku) |

## How it works

```
You                    Engine                 Agents
 │                       │                      │
 │  cord run "goal"      │                      │
 │──────────────────────>│                      │
 │                       │  create root in DB   │
 │                       │  launch root agent   │
 │                       │─────────────────────>│
 │                       │                      │ spawn("#2", ...)
 │                       │                      │ spawn("#3", ...)
 │                       │                      │ complete("decomposed")
 │                       │<─────────────────────│
 │                       │                      │
 │                       │  #2 and #3 ready     │
 │                       │  launch both         │
 │                       │─────────────────────>│ (parallel)
 │                       │                      │ complete("result")
 │                       │<─────────────────────│
 │                       │                      │
 │                       │  all children done   │
 │                       │  relaunch #1 for     │
 │                       │  synthesis            │
 │                       │─────────────────────>│
 │                       │                      │ complete("final report")
 │  TUI: all ✓           │<─────────────────────│
 │<──────────────────────│                      │
```

Each agent gets MCP tools to coordinate:

| Tool | What it does |
|------|-------------|
| `spawn(goal, prompt, returns, blocked_by)` | Create a child task |
| `fork(goal, prompt, returns, blocked_by)` | Create a child that inherits sibling context |
| `complete(result)` | Mark yourself done with a result |
| `read_tree()` | See the full coordination tree |
| `read_node(node_id)` | See a single node's details |
| `ask(question, options)` | Request input |
| `stop(node_id)` | Cancel a node |
| `pause(node_id)` | Pause an active node |
| `resume(node_id)` | Resume a paused node |
| `modify(node_id, goal, prompt)` | Update a pending/paused node |

Agents don't know they're in a coordination tree. They see MCP tools and use them as needed. The protocol — dependency tracking, authority scoping, result injection — is enforced by the MCP server.

## Key concepts

**spawn vs fork** — both create children. `spawn` gives the child a clean slate (just its prompt). `fork` injects completed sibling results into the child's prompt. Use spawn for independent tasks, fork for analysis that builds on prior work.

**blocked-by** — a node lists other node IDs it depends on. The engine won't launch it until all dependencies are complete. Agents set this when calling `spawn()` or `fork()`.

**Two-phase execution** — an agent decomposes (creates children, calls `complete`). The engine waits for children. When all children finish, the engine relaunches the parent with a synthesis prompt that includes children's results.

**Authority** — agents can only create children under themselves and stop nodes in their own subtree. They can't touch siblings or ancestors.

## Project structure

```
src/cord/
    cli.py                  # cord run "goal"
    db.py                   # SQLite (CordDB class, WAL mode)
    prompts.py              # Prompt assembly for agents
    runtime/
        engine.py           # Main loop, TUI
        dispatcher.py       # Launch claude CLI processes
        process_manager.py  # Track subprocesses
    mcp/
        server.py           # MCP tools (one server per agent)
```

~550 lines of source. SQLite is the only dependency beyond the MCP library.

## Tests

```bash
uv run pytest tests/ -v   # 49 tests
```

## Experiments

[`experiments/behavior_compare.py`](experiments/behavior_compare.py) runs 8 behavioral tests against both Opus and Sonnet via Claude Code CLI, comparing how each model uses the Cord MCP tools. Key finding: both models produce identical coordination structures (spawn/fork/blocked_by), and when the server rejects an unauthorized action, both escalate via `ask()` instead of finding workarounds.

The `pause`, `resume`, and `modify` tools were added because Claude independently tried to call them before they existed ([BEHAVIOR.md](BEHAVIOR.md) test 13). We built what the model already expected.

## Costs

Each agent subprocess has its own Claude API budget (set via `--budget`). A simple 2-node task costs ~$0.10. The demo fintech report (4 agents + synthesis) costs ~$2-4. Costs scale with the number of agents and their complexity.

## Limitations

- Single machine only. Agents are local processes.
- No web UI — terminal TUI only.
- No mid-execution message injection (pause/modify/resume requires relaunch).
- Each agent gets its own MCP server process (~200ms startup overhead).
- Claude Code CLI must be installed and authenticated.

## Alternative implementations

This repo is one implementation of the Cord protocol. The protocol itself — five primitives, dependency resolution, authority scoping, two-phase lifecycle — is independent of the backing store, transport, and agent runtime. You could implement Cord with Redis pub/sub, Postgres for multi-machine coordination, HTTP/SSE instead of stdio MCP, or non-Claude agents. See [RFC.md](RFC.md) for the full protocol specification.

## License

MIT
