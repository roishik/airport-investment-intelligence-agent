# Decision log

One line per non-obvious choice, in build order, with why — written
**as** the choice was made, not reconstructed afterwards. Anyone reading
this should be able to reconstruct the reasoning without asking me.

The first section is architectural decisions that predate the specific
domain work; the second is the assignment itself, in the order the
choices actually happened.

## Architecture decisions

- **Hand-rolled agent loop, no framework** (`app/agent_loop.py`, ~70
  lines). At this size a framework's abstractions cost more to reason
  about than the loop they replace, and the loop is where termination,
  guardrail wrapping, and the reasoning trace all live — the three things
  worth being able to point at. See README "Why no framework."
- **`app/scoring.py` has zero I/O and zero LLM calls, on purpose.** It's
  the one file that has to be defensible as "not only LLM output" —
  keeping it pure means it's fully unit-testable with no mocking and no
  network.
- **Tools return per-component breakdowns (raw value, normalized score,
  weight, contribution), never a bare score**, so the LLM explains a
  number it never computed. Enforced at two levels: the tool's return
  shape (`app/tools.py`) and the system prompt's `NEVER_COMPUTE_RULE`
  (`app/system_prompt.py`).
- **`LLM_PROVIDER` defaults to `mock`, not `openai`.** Cloning this repo
  and running `pytest` or `python -m app.cli` works with zero setup — no
  key, no account, no auth debugging. A reviewer should be able to run it
  in under a minute.
- **LLM provider calls are non-streaming.** The agent loop needs the
  complete `tool_calls` list before it can decide what to do next, so
  streaming the model's tokens buys nothing on a tool-calling turn — see
  `openai_llm.py`'s docstring.
- **Chat UI is a single static HTML page + one FastAPI endpoint**, not a
  build-tooled frontend. UI polish is not what this brief asks for, and
  the tool-call log matters more than the styling.
- **Guardrails are a deterministic regex pre-filter, not a second LLM
  call.** An "is this an injection?" LLM call would be slower,
  non-deterministic, and itself attackable — see `app/guardrails.py` for
  what a production version would add instead.
- **Tool errors are caught and returned as `{"error": ...}` data**, never
  allowed to crash the loop or get silently swallowed. The model is told
  about the failure and is expected to say so, per system-prompt rule 5.
- **`max_turns` (default 6) hard-stops the loop and raises
  `MaxTurnsExceeded`** rather than looping forever if a provider keeps
  requesting tools. A hand-rolled loop has to enforce this itself.

## Assignment decisions (in build order)

<!-- Format: **[HH:MM] decision** — why. Rejected: alternative, and why not. -->
