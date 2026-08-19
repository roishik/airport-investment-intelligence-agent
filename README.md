# Airport Investment Intelligence Agent

An AI agent that helps analysts identify US airports where modernization
investment is most likely to pay off — by ranking and comparing airports
on **deterministic, inspectable scoring logic**, and using an LLM only to
choose tools, resolve what the user meant, and explain numbers it never
computed.

**Headline finding:** under the default headroom-weighted criteria, the
biggest airport does not automatically win — LAX ranks **67th of 144**
eligible airports, and the actual top two (Nashville and Denver) are
0.30% apart, with every one of the five weights able to flip that order
at a 5% change. See `DESIGN_DOC.md` §2 for the full sensitivity
analysis.

## Run it

```bash
git clone https://github.com/roishik/airport-investment-intelligence-agent.git
cd airport-investment-intelligence-agent
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
```

Now edit `.env` and add your key: `OPENAI_API_KEY=sk-...`.
`LLM_PROVIDER=openai` is already set — that's the only required edit;
everything else in `.env.example` is optional (see the note below).
Then:

```bash
.venv/bin/uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**. That's the real tool-calling agent
against `gpt-4o-mini` — including voice (open mic, spoken replies,
barge-in), which reuses the same `OPENAI_API_KEY` rather than needing a
second credential.

> **No key on hand, or want to see it run first?** `LLM_PROVIDER`
> defaults to `mock`, so `.venv/bin/pytest -q` (305 tests) and
> `.venv/bin/python -m app.cli` both work with zero setup, no network,
> no key. `LLM_PROVIDER=anthropic`, or `=groq` (a free key, no credit
> card, from [console.groq.com/keys](https://console.groq.com/keys)),
> are drop-in alternatives to OpenAI for the agent itself — set the
> provider and its key in `.env`, nothing else changes. Voice's own
> `TTS_PROVIDER=google` is a similar optional swap; see `.env.example`
> for which variable each one needs.

## Layout

```
app/        the agent: loop, tools, scoring, entity resolution, web + voice routes
data/       committed dataset app/dataset.py reads — refresh with refresh_data.py
evals/      runnable eval harness — 26 seeded failure-mode tasks
tests/      pytest suite (305 tests)
static/     the web UI — chat, live tool-call log, voice controls
scripts/    one-off utilities (example-question runner, smoke test, calibration)
```

**The brief's required design/architecture document is
[`DESIGN_DOC.md`](DESIGN_DOC.md)** — scoring methodology (§2), where and
how AI is used (§3), key tradeoffs (§4). Alongside it:
[`ASSUMPTIONS.md`](ASSUMPTIONS.md) (every data gap, unit conversion and
staleness date) and [`evaluation_plan.md`](evaluation_plan.md).

For navigation: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) is the
file-by-file map and how a request flows through it; why things were
built this way is in
[`docs/DECISIONS_SUMMARY.md`](docs/DECISIONS_SUMMARY.md) (by subject) or
[`DECISIONS.md`](DECISIONS.md) (the full build-order log).

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

`DESIGN_DOC.md` §"Where and how AI is used" is the canonical version,
with the enforcement mechanism for each row. Short version:

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

26 seeded tasks across correctness, missing-data, self-computation,
injection, explanation-quality and robustness, with deterministic graders
plus an LLM judge that was itself validated against hand labels. See
`evals/README.md` and `evaluation_plan.md`.

## Voice

Voice is the brief's bonus. There are two paths, and which one you get
depends only on whether a key is configured.

**Without any key** — the mic button dictates your question, and the
"Voice replies" toggle reads answers aloud. Both use the browser's own
Web Speech API: no server, no cost. Chrome, Edge and Safari support
speech recognition; Firefox does not, and the controls disable
themselves with an explanation rather than failing on click.

**With `OPENAI_API_KEY` set** — the waveform button starts *conversation
mode*: an open microphone, real speech models, spoken replies, and
barge-in. Talk; it hears you stop and answers. Talk over it and it stops
mid-sentence.

```bash
OPENAI_API_KEY=sk-...     # the same key the agent already uses
```

No second credential: speech-to-text and text-to-speech both default to
OpenAI precisely so that anyone who can run the agent can also talk to
it. `GET /voice/health` reports whether voice is available and, if not,
which variable is missing — the UI reads it and puts the reason on the
disabled button.

The spoken turn goes through **the same `/chat/stream` endpoint as a
typed one**: same tools, same guardrails, same deterministic scoring,
same live tool-call log. Voice is a modality, not a second agent.

Barge-in does three things, and the third is the one worth looking at:
it stops playback, abandons anything not yet played, and then rewrites
the stored reply to only the sentences you actually heard
(`app/conversation.py`). Without that last step the model believes it
said things you never heard, and the next answer is built on a
conversation that did not happen.

Switching the voice vendor is one variable, like every other provider
here — `TTS_PROVIDER=google` plus `GCP_TTS_API_KEY` uses Google Neural2
instead. See `DESIGN_DOC.md` §3a for the full architecture and the
trade-offs, including what the energy-based endpointing cannot do.

## Scope and limitations

`ASSUMPTIONS.md` is the canonical version — every data gap, unit
conversion, and staleness date is there. Highlights:

- Ranked set is FAA hub class L/M/S (144 of 515 airports); the full 515
  remain queryable by name, just not ranked by default — percentage
  growth on a near-zero base (e.g. a 37,951-passenger field posting
  +126,403% YoY) makes an unfiltered ranking meaningless.
- Data is snapshotted (FAA enplanements, OurAirports, Census population),
  not live — refresh with `data/refresh_data.py`. The one live call
  (FAA NAS Status) is deliberately kept **outside** the scored path.
- Expansion *feasibility* (land, permitting, political consent) is not
  modeled at all — the ranking answers "where is the demand pressure,"
  not "where can you actually build."
- Q3's "long haul" is answered as a domestic-vs-international departure
  share, a stated proxy — no public dataset carries per-route distance
  outside the bot-blocked TranStats portal.
- No FAA ASPM/OPSNET or BTS On-Time Performance delay data (both blocked
  behind logins/bot-walls) — congestion leans on capacity/utilization
  proxies, not measured delay minutes.
- No persistent multi-user history or auth — in-memory, single-session.
- Voice transcribes and synthesizes per utterance, not streaming per
  token; endpointing is energy-based, so it cannot tell an interruption
  from a backchannel ("mm-hmm" while the agent talks will stop it).

## Tests

```bash
.venv/bin/pytest -q     # 305 passing
```

No network, no API key, no mocking of the pure modules — `scoring.py`,
`analytics.py` and `entity_resolution.py` are pure functions and are
tested as such. The voice endpoints are tested against fake providers, so
they need no credentials either.

Two test files (`test_markdown_renderer.py`, `test_voice_client.py`)
exercise the shipped JavaScript by running it under `node`, and **skip
cleanly if `node` is not installed** — adding an npm toolchain to a
four-package Python project would have cost more than it returns, and
`pytest` must stay green on a bare clone with zero setup.
