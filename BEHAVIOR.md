# Claude Code MCP Behavior Analysis

Results from 15 tests against a minimal Cord MCP server.
Tested: Claude Code 2.1.37, 2026-02-18.

## Summary

| # | Test | Pass | Notes |
|---|------|------|-------|
| 1 | read_tree | YES | Called unprompted when asked about state |
| 2 | Self-decomposition (spawn) | YES | Created 5 nodes with correct blocked_by deps |
| 3 | Fork vs spawn choice | YES | Correctly chose fork for context-heavy, spawn for stateless |
| 4 | ask (human elicitation) | YES | Used all params: target, question, options, default, timeout |
| 5 | Goal chain injection | YES | Read tree for context, produced substantive output |
| 6 | Authority violation (stop sibling) | YES | Got rejected, escalated via ask parent instead |
| 7 | Authority (stop own child) | YES | Succeeded immediately |
| 8 | Modify pending node | YES | Changed goal and prompt |
| 9 | Answer elicitation | YES | Read tree first, then answered with exact value |
| 10 | Complex decomposition (deps) | YES | 6 nodes, 3 parallel → analysis → draft → review |
| 11 | Result reference awareness | YES | Read results from completed node, explained data flow |
| 12 | Pause + resume | YES | Both calls in sequence |
| 13 | Error handling (modify active) | INTERESTING | Tried modify, failed, tried pause+modify, failed, then stop+respawn |
| 14 | Stdout as structured JSON | YES | Clean JSON, no markdown wrapping, no tool calls needed |
| 15 | Ask parent (agent-to-agent) | YES | Correct target, good question framing |

**15/15 passed.** No failures. One notably interesting behavior (test 13).

---

## Key Findings

### 1. Tool discovery is reliable

Claude calls `read_tree()` as its first action in almost every test (12 of 15).
It understands the tree structure from JSON and reasons about it correctly.
It never needed to be told which tools exist — MCP tool descriptions were sufficient.

### 2. Self-decomposition works naturally

When told to decompose, Claude:
- Creates sensible subtask breakdowns (3-6 nodes)
- Uses `blocked_by` correctly for dependencies
- Writes detailed prompts for each child node
- Reads the tree after creating nodes to verify

It does NOT need special prompting to decompose. The instruction
"break this into subtasks" + access to `spawn()` is enough.

### 3. Fork vs spawn distinction is understood

When given a scenario with both context-heavy and stateless subtasks,
Claude correctly chose:
- `fork` for the analysis that needs accumulated research context
- `spawn` for the price-fetching task that just needs tickers

It explained the reasoning using the exact mental model from the spec
(contractor vs team member, restart cost, context inheritance).

### 4. Authority model works through error + adaptation

Claude doesn't preemptively check authority — it tries the action and
handles the error. In test 6, when `stop(#a2)` was rejected:
1. It acknowledged the authority boundary
2. It escalated by creating an `ask parent` node
3. It explained to the user why it couldn't act directly

This is actually the ideal behavior — the agent tries, fails gracefully,
and uses the correct escalation path.

### 5. Error recovery is aggressive (test 13)

When asked to modify an active node (which is invalid), Claude:
1. Tried `modify` → rejected (active)
2. Tried `pause` then `modify` → rejected (paused, not pending)
3. Tried `stop` then `spawn` a replacement

It found a workaround (cancel + respawn) without being told the pattern.
This is creative but potentially dangerous — the agent destroyed a running
task to work around a constraint. The runtime should decide whether this
is acceptable, not the agent.

**Implication:** Authority scoping must prevent agents from stopping
siblings, but agents CAN stop their own parent's children if they have
the authority. The runtime needs to be the guardrail, not Claude's judgment.

### 6. Stdout as result works cleanly

Test 14 confirmed Claude can output raw JSON without markdown wrapping
when explicitly told to. The output was valid JSON, parseable, and
matched the requested schema. No tool calls were made — the output
IS the result.

**Caveat:** Claude naturally wants to add explanation. The prompt must
be explicit: "Output ONLY the JSON." The runtime's prompt construction
should enforce this for typed results.

### 7. Elicitation covers all targets

- `ask human` — test 4: created with options, default, timeout
- `ask parent` — test 6 (emergent!) and test 15: correct target, good framing
- Both used options correctly

Claude frames questions well for the target audience. Parent-directed
questions included context about why the information is needed.

### 8. Goal chain injection provides situational awareness

Test 5 showed the agent understood its place in the hierarchy from the
injected goal chain. It read the tree for additional context (good habit).
The output was appropriate for a leaf-node task — focused execution,
not coordination.

**Note:** The agent also did web searches to produce the analysis,
showing it uses its full tool suite alongside Cord tools naturally.

---

## Behavioral Patterns Observed

### Read-before-act
Claude reads the tree before almost every action. This is defensive
and correct — it wants to understand state before mutating it. The
runtime should expect frequent `read_tree` / `read_node` calls.

### Verify-after-write
In tests 2, 3, and 10, Claude called `read_tree()` AFTER creating
nodes to verify they were created correctly. This is a self-checking
behavior.

### Escalation over violation
When authority was denied (test 6), Claude escalated through
the proper channel (`ask parent`) rather than finding a workaround.
This validates the authority model design.

### Aggressive workarounds on constraint errors (test 13)
When a constraint prevented the desired action, Claude tried alternative
approaches (pause, then stop+respawn). This is resourceful but the
runtime must be the ultimate authority on what's allowed.

---

## Implications for Runtime Design

### Prompt construction matters
- For typed results (especially `structured`), the prompt MUST include
  "Output ONLY the result, no explanation" or similar.
- Goal chain injection works as-is — just prepend to the prompt.
- Agent ID should be stated in the prompt ("You are node #X") for
  authority-aware behavior.

### MCP tool descriptions are sufficient
Claude doesn't need a manual. The tool name + description + parameter
names are enough for correct usage. Keep descriptions concise and accurate.

### blocked_by is natural
Claude uses `blocked_by` without special explanation. It maps to how
it already thinks about task dependencies. The parameter name is intuitive.

### The returns field is underused
Claude put descriptive strings in `returns` (e.g. "Structured competitor
profiles with key metrics") instead of type enums ("structured", "list").
The runtime should validate and coerce, or the tool description should
constrain the enum more tightly.

### read_tree frequency
Expect 1-3 `read_tree` calls per agent invocation. This is the most
frequently called tool. Optimize it — the tree should be fast to serialize
and the response should be compact.

---

## What We Didn't Test

- **Session resume (fork context)** — `--resume` flag for inheriting
  conversation context. Needs a real multi-turn test.
- **Concurrent agents** — multiple Claude processes hitting the MCP
  server simultaneously.
- **Large trees** — behavior with 50+ nodes in the tree.
- **Result injection** — passing `#a1.result` into a child's context
  at dispatch time.
- **Process exit codes** — confirming exit 0 vs non-zero mapping.
- **Long-running tasks** — agent that works for 5+ minutes.
- **Budget limits** — `--max-budget-usd` interaction with task complexity.
