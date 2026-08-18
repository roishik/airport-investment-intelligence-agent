# Airport Investment Intelligence Agent

An AI agent that helps analysts identify US airports where modernization
investment is most likely to pay off — by ranking and comparing airports
on **deterministic, inspectable scoring logic**, and using an LLM only to
choose tools, resolve what the user meant, and explain numbers it never
computed.

> **TODO(P8)** — replace this line with the headline finding once the
> real criteria and dataset land.

## Run it in one minute, with no API key

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                     # 181 tests, no key, no network
.venv/bin/python -m app.cli             # terminal chat, mock LLM
.venv/bin/uvicorn app.main:app --reload # web chat at http://127.0.0.1:8000
```

That works because `LLM_PROVIDER` defaults to `mock`. To use a real
model, copy `.env.example` to `.env` and set:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

`LLM_PROVIDER=anthropic` works the same way. **No paid key?**
`LLM_PROVIDER=groq` + a free key from
[console.groq.com/keys](https://console.groq.com/keys) (no credit card)
gets you the real tool-calling agent, not just the mock stand-in — see
`app/providers/llm/groq_llm.py`. Nothing outside `app/config.py` and
`app/providers/llm/` changes when you swap.

## Layout

```
app/
  scoring.py            pure deterministic ranking — zero I/O, zero LLM
  analytics.py          pure filter / aggregate / derived-metric contracts
  entity_resolution.py  pure fuzzy name -> id matching with a confidence bar
  tools.py              the tool surface: fetches data, calls the pure
                          modules, returns per-component breakdowns
  guardrails.py         untrusted-data wrapping + injection pre-filter
  system_prompt.py      the "never compute a number yourself" contract
  agent_loop.py         the hand-rolled loop (~70 lines, no framework)
  config.py             env loading + provider selection
  providers/llm/        swappable backends: mock | openai | anthropic | groq
  main.py               FastAPI web chat (one page, one endpoint)
  cli.py                terminal chat
static/index.html       the web UI: chat + live tool-call log + voice (Web Speech API)
evals/                  runnable eval harness — 23 seeded failure-mode tasks
tests/                  pytest suite
```

## The four question shapes

The brief's example questions are four genuinely different query shapes,
and each maps to a different primitive. This is why the tool surface
looks the way it does:

| Question shape | Example | Primitive |
|---|---|---|
| Filtered ranking | "Which airports in New England are strong candidates for terminal expansion?" | `find_items` → `compare_items` |
| Pairwise comparison with an ambiguous name | "Compare LA and Santa Ana congestion levels." | `resolve_entity` → `compare_items` |
| Single-entity aggregate | "What percentage of flights out of Anchorage are long haul?" | `aggregate_records` |
| Derived quantity + causal explanation | "What is the unmet flight demand at SFO, and why?" | `estimate_derived_metric` |

The third and fourth are the interesting ones: **neither is a ranking**.
A composite score cannot answer "what share of one airport's flights are
long haul", and "unmet demand" is a quantity that exists in no dataset by
construction — nobody records the passengers they never saw. Those needed
their own code paths, deliberately separate from `scoring.py`.

## Where the LLM is, and where it is not

> **TODO(P8)** — expand into the full table; `DESIGN_DOC.md` §"Where and
> how AI is used" is the canonical version.

| Decision | Made by |
|---|---|
| Which tool to call, with what arguments | **LLM** |
| What the user meant by an ambiguous name | Deterministic resolver proposes with confidence; **LLM** picks or asks |
| Every score, weight, normalization, ranking, aggregate | **Python** (`scoring.py`, `analytics.py`) — never the LLM |
| The wording of the explanation | **LLM**, constrained to numbers the tools returned |

The system prompt forbids the model from computing any number itself, and
every tool returns a per-component breakdown (raw value, normalized
score, weight, contribution) so it always has the arithmetic in hand and
never needs to invent it.

## Why no framework

The agent loop is a plain `while` loop over one provider-agnostic
`chat()` call, with tool dispatch, guardrail wrapping, and turn-limiting
done by hand in about seventy lines.

- **Control.** The three things most worth being able to point at —
  guaranteed termination, treating tool output as untrusted, and the
  reasoning trace — all live in that loop. Under a framework they'd be
  configuration spread across someone else's abstractions.
- **Debuggability.** When a tool call goes wrong, the stack trace is
  seventy lines of local code, not a framework internals tour.
- **Honesty.** At this size a framework buys orchestration features this
  agent doesn't use, in exchange for a dependency whose behaviour I'd be
  guessing at.

This would change with multi-agent handoff, durable state, or human
review queues. It hasn't yet.

## Guardrails — what this is and isn't

Every tool result is wrapped in an explicit `<untrusted_data>` fence
before it enters the message history, and scanned by a deterministic
regex pre-filter for common injection phrasings. Both are tested.

**What it is:** the minimum "tool output is data, not instructions"
discipline, made visible, logged, and testable.

**What it isn't:** a classifier, an allow-listed tool surface, or
output-side data-loss checks. A production version would add all three,
plus a model-based detector for the paraphrased attacks a regex misses.

## Evals

```bash
.venv/bin/python -m evals.run_evals                        # mock provider
.venv/bin/python -m evals.run_evals --provider openai      # real key from .env
```

23 seeded tasks across correctness, missing-data, self-computation,
injection, explanation-quality and robustness, with deterministic graders
plus an LLM judge that was itself validated against hand labels. See
`evals/README.md` and `evaluation_plan.md`.

## Scope and limitations

> **TODO(P8)** — data sources, staleness dates, coverage gaps, and every
> deliberate scope cut. `ASSUMPTIONS.md` is the canonical version.

## Tests

```bash
.venv/bin/pytest -q     # 153 passing
```

No network, no API key, no mocking of the pure modules — `scoring.py`,
`analytics.py` and `entity_resolution.py` are pure functions and are
tested as such.
