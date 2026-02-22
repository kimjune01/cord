# RFC: Cord

    Status:     Draft
    Author:     June Kim
    Created:    2026-02-18
    Version:    0.4.0

## Abstract

This document specifies Cord, a coordination protocol for
agent trees. Agents — implemented as Claude Code CLI
processes — execute tasks, create subtasks, and return typed
results. A SQLite database is the shared coordination state.
Agents interact with it through MCP tools.

The protocol introduces four primitives (`goal`, `task`,
`serial`, `ask`) and a single context-flow mechanism: `needs`.
When creating a child task, the parent lists which completed
nodes' results should be injected into the child's prompt.
This replaces the earlier `spawn`/`fork` distinction with
explicit context selection.

## 1. Motivation

Existing agent orchestration systems fall into two categories:

1. **Imperative frameworks** (LangGraph, AutoGen, OpenAI Swarm) —
   coordination logic is embedded in application code. No single
   artifact describes the work. Hard to inspect, modify, or
   hand off mid-execution.

2. **Declarative workflow DSLs** (Serverless Workflow, Argo, Airflow) —
   designed for deterministic microservice orchestration, not for
   intelligent agents that may need to restructure their own work,
   ask clarifying questions, or operate with varying degrees of
   shared context.

No existing system provides:

- **Explicit context selection** — the parent decides which
  results flow to each child via a single `needs` parameter.
- **Native elicitation** — agents asking humans, parents, or
  children as part of the coordination structure.
- **Runtime self-modification** — agents adding subtasks and
  restructuring their own subtree during execution.
- **Human-in-the-loop** through the same interface as agents.

Cord addresses these gaps with a minimal set of primitives designed
for coordinating LLM-based agents on a single machine.

## 2. Overview

### 2.1 System Architecture

    ┌─────────────────────────────────────────────┐
    │              SQLite Database                 │
    │     (coordination state, WAL mode)           │
    └──────────────────┬──────────────────────────┘
                       │ read/write
                       ▼
    ┌─────────────────────────────────────────────┐
    │                 Engine                       │
    │  (scheduler, process manager, TUI)           │
    └──────────────────┬──────────────────────────┘
                       │ launches
              ┌────────┴────────┐
              │  Claude Code    │
              │  CLI processes  │
              │  (one per node) │
              └────────┬────────┘
                       │ MCP (stdio)
              ┌────────┴────────┐
              │  MCP Servers    │
              │  (one per agent,│
              │   stdio transport│
              │   → SQLite)     │
              └─────────────────┘

### 2.2 Design Constraints

- **Single machine.** The SQLite database and agent processes
  are local. Distributed execution is out of scope.
- **Agents are Claude Code CLI instances.** The execution model
  is bound to capabilities available in Claude Code.
- **Database is truth.** The engine holds no persistent state
  beyond what is in SQLite. A crashed engine recovers by
  re-reading the database.

## 3. Coordination State

### 3.1 Storage

The coordination state is stored in a SQLite database (WAL mode
for concurrent access). The database contains two tables:

- **nodes** — all nodes in the coordination tree with their
  type, goal, status, prompt, result, and parent reference.
- **dependencies** — `needs` relationships between nodes.

Node IDs are auto-generated integers, displayed as `#1`, `#2`, etc.

### 3.2 Input

The root goal can be provided as:

- A **string** — `cord run "Build a competitive analysis"`
- A **file** — `cord run plan.md` (file contents become the goal)

The root agent decomposes the goal into subtasks by calling
`create()` via MCP tools. There is no input file format —
agents build the tree programmatically.

### 3.3 Nodes

Every entry in the coordination tree is a node. Every node has:

- **ID** — auto-generated, unique (e.g. `#1`, `#2`). Never reused.
- **Type** — one of the four primitives (Section 4).
- **Goal** — short human-readable description.
- **Prompt** — full instructions for the executing agent.
- **Status** — current lifecycle state (Section 6).
- **Returns** — expected result type (Section 5).
- **Result** — output from the agent on completion.
- **Parent** — reference to parent node (NULL for root).
- **Needs** — list of node IDs whose results are required.
- **Children** — derived from parent references.

## 4. Primitives

The protocol has four node types.

### 4.1 `goal`

The root-level objective. A coordination tree has exactly one
root goal. The goal decomposes into children via agent action.

### 4.2 `task`

Creates a child task. The parent specifies which completed
nodes' results should be injected into the child's prompt
via the `needs` parameter.

Properties:

- `needs` controls both execution ordering and context.
  The task won't start until all needed nodes complete.
- Full results from needed nodes are injected into the prompt.
- If no `needs` are specified, the task runs immediately with
  only its own prompt.

### 4.3 `serial`

An ordered sequence of children. Each child starts only after the
previous one completes. Dependencies are implicit by ordering.

### 4.4 `ask`

Elicitation primitive. An agent requests input from a target
(human, parent, or children).

## 5. Result Types

### 5.1 Type Declaration

The `returns` field specifies the expected result type. This
creates a contract: the child knows what to produce, and
output format instructions are injected into the prompt.

### 5.2 Built-in Types

| Type         | Description                                  |
|--------------|----------------------------------------------|
| `text`       | Free-form text. Reports, summaries, prose.   |
| `boolean`    | Yes/no decision.                             |
| `list`       | Ordered collection of items (JSON array).    |
| `structured` | Key-value object (JSON). Schema in prompt.   |
| `file`       | Path to a generated artifact.                |
| `approval`   | Human sign-off. Used with `ask`.             |

### 5.3 Result Storage and Flow

When a node completes (via the `complete` MCP tool), the engine:

1. Stores the result in the database.
2. Updates the node status to `complete`.
3. Checks if any `needs` dependencies are now satisfied
   and dispatches newly unblocked nodes.
4. Checks if all siblings are done; if so, relaunches the
   parent for synthesis.

Downstream nodes access dependency results through prompt
injection — the engine includes completed dependency results
in the agent's prompt at launch time.

## 6. Node Lifecycle

    pending --> active --> complete
                  |
                  ├──> paused --> pending  (via resume)
                  |
                  ├──> cancelled
                  |
                  └──> failed

- **pending** — not yet started. Dependencies may be unmet.
- **active** — agent is executing.
- **paused** — agent halted. Can be modified and resumed.
- **complete** — agent returned a result via `complete()`.
- **cancelled** — stopped by signal or user.
- **failed** — agent process exited with non-zero code.

The `paused` state enables in-place modification of running work.
An agent can `pause` a child (killing its process), `modify` its
goal or prompt, then `resume` it (returning it to `pending` for
relaunch). This replaces the destructive stop-and-respawn pattern.

Every transition is written to the database by the engine.

## 7. Context Flow

Context flows through the tree via the `needs` parameter. When
creating a child task, the parent lists which nodes' results
should be injected into the child's prompt.

This is a **selection** mechanism, not a compression mechanism.
The child receives the full results from each needed node. The
parent decides which results are relevant — the child gets
exactly what it needs, nothing more.

### 7.1 Context Rot

If a child would need results from many nodes, the parent should
create an intermediate task to synthesize them first. Each level
of tree depth is a natural compression boundary:

    #2 "Research A"     ──┐
    #3 "Research B"     ──┼──> #6 "Synthesize research"  ──> #7 "Final report"
    #4 "Research C"     ──┘

Prefer deeper trees over wide fan-ins. Depth compresses.
Width parallelizes.

## 8. Concurrency

Children under a node are **concurrent by default**. Dependencies
between siblings are declared with `needs` (a list of node
IDs that must complete before this node can start).

The engine finds ready nodes by querying the database for
pending nodes whose dependencies are all complete, then
launches them in parallel.

## 9. Authority Model

### 9.1 Agent Authority

Agents have scoped authority over their own subtree:

| Action                             | Allowed |
|------------------------------------|---------|
| Create children under self         | Yes     |
| Complete own node                  | Yes     |
| Stop nodes in own subtree          | Yes     |
| Pause/resume nodes in own subtree  | Yes     |
| Modify nodes in own subtree        | Yes     |
| Stop/pause/modify outside subtree  | No      |

Authority is enforced server-side. Agents that attempt
unauthorized actions receive an error and are guided to
escalate via `ask()`.

### 9.2 Human Authority

Humans have root authority through the CLI.

## 10. MCP Interface

The coordination system exposes itself as an MCP server
(stdio transport, one per agent). Each agent gets MCP tools
scoped to its node ID.

### 10.1 Tools

| Tool                             | Description                      |
|----------------------------------|----------------------------------|
| `read_tree()`                    | Returns full coordination tree   |
| `read_node(node_id)`            | Returns a single node's detail   |
| `create(goal, prompt, ...)`     | Create a child task              |
| `complete(result)`              | Mark own node complete            |
| `stop(node_id)`                 | Cancel a node in own subtree      |
| `pause(node_id)`                | Pause an active node in subtree   |
| `resume(node_id)`               | Resume a paused node in subtree   |
| `modify(node_id, goal, prompt)` | Update a pending/paused node      |
| `ask(question, options, ...)`   | Create an elicitation node        |

### 10.2 MCP Connection

Each Claude Code instance is launched with an MCP config
that connects it to a per-agent MCP server. The server
reads/writes the shared SQLite database:

    // .cord/mcp-1.json (generated by engine)
    {
      "mcpServers": {
        "cord": {
          "command": "uv",
          "args": ["run", "cord-mcp-server",
                   "--db-path", ".cord/cord.db",
                   "--agent-id", "#1"]
        }
      }
    }

The agent does not need to know it is part of a Cord tree.
It sees MCP tools and uses them as needed. The coordination
semantics — authority, typed results, dependency tracking —
are enforced by the MCP server.

## 11. Execution Model

### 11.1 Agent Runtime

Each agent is a Claude Code CLI process. The engine spawns
and manages these processes.

### 11.2 Self-Decomposition

An agent MAY decide at runtime to decompose its work. It
reads its goal, judges the complexity, and calls `create()`
to make subtasks. The tree grows organically based on agent
judgment, not only from the initial goal.

### 11.3 Two-Phase Execution

When an agent creates children and then calls `complete()`:

1. The agent's result is stored (decomposition phase done).
2. The engine waits for all children to complete.
3. When all children are done, the engine relaunches the
   parent with a synthesis prompt that includes children's
   results.
4. The parent produces its final synthesized output.

### 11.4 Goal Chain Injection

The engine injects the **goal chain** — the goal of each
ancestor from root to self — into every agent's prompt:

    You are node #4 in a coordination tree.
    Your goal: Evaluate Stripe against identified trends

    Goal chain:
      #1 "Competitive landscape report for fintech"
        #3 "Deep analysis"
          #4 "Evaluate Stripe" <- your task

### 11.5 Agent Lifecycle

1. Engine finds a node ready to execute (status `pending`,
   dependencies satisfied).
2. Engine constructs the agent prompt: identity + goal chain
   + needed results + node prompt + MCP instructions.
3. Engine launches a Claude Code process with the prompt
   and a per-agent MCP config.
4. The agent works — calling MCP tools, creating subtasks.
5. The agent calls `complete(result)` via MCP.
6. The agent process exits. Engine picks up the completion.

### 11.6 Completion Rule

Agents MUST call the `complete` MCP tool with their result.
If the agent process exits without calling `complete`, the
engine falls back to using stdout as the result. Exit code 0
= success, non-zero = failure.

### 11.7 Signal Delivery

| Signal   | Mechanism                                        |
|----------|--------------------------------------------------|
| `CANCEL` | SIGTERM to process. Node → `cancelled`.           |
| `PAUSE`  | SIGTERM to process. Node → `paused`.              |

## 12. Engine

### 12.1 Runtime Loop

1. Check if tree is complete (all nodes terminal). If so, exit.
2. Poll active agent processes for completions.
3. Handle completions: store results, check synthesis triggers.
4. Query database for ready nodes (pending + deps met).
5. Launch agents for ready nodes.
6. Render TUI (colored status tree).
7. Sleep (2s default). Repeat.

### 12.2 TUI

The engine renders a live terminal display showing the
coordination tree with colored status indicators:

    cord run

      ● #1 [active] GOAL Competitive landscape report
        ✓ #2 [complete] TASK Identify competitors
          result: Task complete...
        ● #3 [active] TASK Research trends
        ○ #4 [pending] TASK Deep analysis
          needs: #2, #3

      running: #1, #3

## 13. CLI

    cord run "goal description" [--budget <usd>] [--model <model>]
    cord run plan.md [--budget <usd>] [--model <model>]

- `cord run` creates a fresh SQLite database, creates the root
  goal node, and starts the engine loop.
- If the argument is a file path, its contents are used as the
  root goal.
- `--budget` sets the per-agent budget (default: $2.00).
- `--model` sets the Claude model (default: sonnet).

## 14. Design Principles

1. **Database is truth.** SQLite is the coordination state.
   The engine is stateless. A crashed engine recovers by
   re-reading the database.

2. **Four primitives.** `goal`, `task`, `serial`, `ask`.

3. **`needs` is the context lever.** The parent selects which
   results flow to each child. Full results, no compression.
   Depth compresses through synthesis. Width parallelizes.

4. **Elicitation is native.** Agents can ask humans, parents, or
   children. Questions propagate up the tree.

5. **Authority is scoped.** Agents control their subtree. Humans
   have root access.

6. **Agents build the tree.** There is no input file format.
   The root agent decomposes the goal into subtasks
   programmatically via MCP tools.

7. **Typed results.** Parent declares what it expects. Prompt
   instructions enforce the format.

8. **Single machine.** Local SQLite. Concurrency bounded by
   machine capacity.

## 15. Changelog

### v0.4.0

- Unified `spawn` and `fork` into a single `task` primitive.
- Replaced `blocked_by` with `needs` — a single parameter that
  controls both execution ordering and context injection.
- Removed the fork context injection mechanism (automatic
  sibling result injection). Context selection is now always
  explicit via `needs`.
- Added prompt guidance for context rot: prefer deeper trees
  over wide fan-ins.

### v0.3.0

- Initial protocol specification with five primitives:
  `goal`, `spawn`, `fork`, `serial`, `ask`.
- `spawn` (scoped context) vs `fork` (inherited context) as
  the key context-flow distinction.
- `blocked_by` for dependency ordering.

## 16. Future Work

- **Web UI** — live observation via websocket, replacing TUI.
- **MERGE signal** — notify an agent when a sibling completes.
- **BUDGET signal** — warn agents of resource limits mid-execution.
- **Skills** — reusable templates that expand into subtrees.
- **`for` modifier** — fan-out expansion over a result set.
- **`resolve: any`** — first child to succeed wins.
- **Result type validation** — runtime validates against declared type.
- **Distributed execution** — coordination database on shared storage.
