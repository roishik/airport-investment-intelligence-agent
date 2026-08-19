# Architecture — file by file

What each file's job is, and how a request moves through them. For *why*
a file looks the way it does, see `DECISIONS_SUMMARY.md` (organized by
subject) or `DECISIONS.md` (the full build log). For methodology and
tradeoffs, see `DESIGN_DOC.md`.

## How a request flows

**A typed question:** browser → `POST /chat/stream` (`app/main.py`) →
`run_agent()` (`app/agent_loop.py`), which loops: ask the LLM provider
for the next step, dispatch any tool call it requests through
`TOOL_REGISTRY` (`app/tools.py`), feed the tool's JSON result back, repeat
until the model answers with no more tool calls or `max_turns` is hit.
Each tool call fetches data via `app/dataset.py`, hands it to a pure
module (`scoring.py`, `analytics.py`, `entity_resolution.py`,
`runway_geometry.py`) to compute, and returns a per-component breakdown —
never a bare number. `main.py` pushes each completed tool call to the
browser over SSE as it happens; the final answer streams down as one
`done` event. Guardrails (`app/guardrails.py`) wrap every tool result
before it re-enters the prompt.

**A spoken question:** browser mic → local endpointing
(`static/voice.js`) → `POST /voice/transcribe` (`app/voice_api.py`) →
text. From there it is indistinguishable from a typed question — it goes
through the *same* `/chat/stream` call above. The reply comes back as
text, gets synthesized sentence-by-sentence via `POST /voice/speak`, and
plays in the browser; a barge-in calls `POST /voice/interrupt`, which
truncates the stored transcript (`app/conversation.py`) to what was
actually heard.

## `app/` — the agent

| File | Job |
|---|---|
| `agent_loop.py` | The loop itself (~70 lines): ask the provider → dispatch tool calls → feed results back → repeat. No framework. Owns turn-limiting (`max_turns`) and guardrail wrapping. |
| `system_prompt.py` | The prompt as a plain string constant, not a template. Carries `NEVER_COMPUTE_RULE` and `NEVER_INVENT_IDS_RULE` as named constants so their presence is unit-testable, plus the numbered rules for which tool answers which question shape. |
| `tools.py` (1675 lines, the largest file) | The tool surface — see the table below. Fetches data via `dataset.py`, calls the pure modules to compute, and shapes every return value as a per-component breakdown the model can quote but never has to calculate. |
| `scoring.py` | Deterministic ranking. **Zero I/O, zero LLM calls, zero imports of network/env-reading libraries** — enforced by convention and checked by a mutation test. `rank_items()`, `Criterion.normalize()`, percentile-clip normalization, weight renormalization over available criteria. |
| `analytics.py` | The three query shapes that aren't ranking: `find_items` (filter), `aggregate_records` (category share), `estimate_derived_metric`/`estimate_unmet_demand` (a modeled quantity with a causal breakdown). Same purity rules as `scoring.py`. |
| `entity_resolution.py` | Free-text → item id, deterministically. Jaro-Winkler + Soundex blend, a `MIN_FUZZY_QUERY_LENGTH` guard, a metro-area layer (`METRO_AIRPORTS`) for queries like "LA" that aren't a single airport, and a restricted edit-distance fallback for short code-shaped queries ("LBG"). Returns `decisive: bool` — the model must ask rather than silently guess when it's `False`. |
| `runway_geometry.py` | Computes parallel-runway separation and arrival-capacity degradation from public runway-end coordinates, per airport. Feeds `estimate_unmet_demand`'s weather-suppressed-throughput term. Zero I/O, zero LLM. |
| `dataset.py` | The one place that reads `data/` off disk, so every other module above stays pure and testable with no fixtures. Builds the in-memory candidate tables, per-item metrics, and `METRO_AIRPORTS`. |
| `guardrails.py` | `wrap_untrusted()` fences any fetched/external text before it re-enters the prompt; `scan_for_injection()` is the deterministic regex pre-filter. No second LLM call — see `DECISIONS_SUMMARY.md` §5. |
| `conversation.py` | In-memory chat history, shared by text and voice. `truncate_last_reply()` is the barge-in operation: rewrites a stored reply down to the sentence-prefix that was actually spoken. Generation-tracked so a `/reset` mid-turn can't be silently undone. |
| `config.py` | Env loading. The `*_PROVIDER` selector pattern (`LLM_PROVIDER`, `STT_PROVIDER`, `TTS_PROVIDER`), model names, and `_find_shared_env()` — walks up from the app directory to find the nearest `.env`, regardless of nesting depth. |
| `main.py` | FastAPI app. Routes: `GET /` (serves `static/index.html`), `GET /health`, `POST /chat` (single JSON response), `POST /chat/stream` (SSE — the one the UI actually uses), `POST /reset`. Mounts the voice routes. |
| `voice_api.py` | `GET /voice/health`, `POST /voice/transcribe`, `POST /voice/speak`, `POST /voice/interrupt`. The server-side half of conversation mode — browser does VAD/endpointing, server does STT/TTS and barge-in truncation. |
| `cli.py` | Terminal chat loop, `python -m app.cli`. Same agent loop, prints each tool call as it happens. |
| `providers/llm/` | `base.py` (interface: `chat()` returns text or tool calls), `mock_llm.py` (scripted, zero network — the default), `openai_llm.py` (REST, not the SDK — keeps vendor surface to one file), `anthropic_llm.py`, `groq_llm.py` (subclasses `openai_llm.py`; Groq's API is wire-compatible). Selected by `LLM_PROVIDER` via `__init__.py`'s factory. |
| `providers/stt/` | `base.py`, `openai_stt.py` (REST transcription endpoint). |
| `providers/tts/` | `base.py`, `openai_tts.py` (default — same key the app already needs), `google_tts.py` (second implementation, proving the interface is real, not a one-off). |

### The tool surface

Every tool the agent can call, and the question shape it answers:

| Tool | Answers | Reads from |
|---|---|---|
| `find_items` | "which airports match X" (filter) | `dataset.py` |
| `compare_items` | "compare/rank these airports" — the eligibility gate lives here | `scoring.py` |
| `rank_by_priorities` | "I care about growth over congestion" (stated priorities → reweighted score) | `scoring.py` |
| `analyze_weight_sensitivity` | "how much would changing weight X matter" | `scoring.py` |
| `weight_robustness_report` | "how stable is the ranking" (near-ties, tau) | `scoring.py` |
| `list_criteria` | "what are your weights" (no items needed) | `scoring.py` constants |
| `resolve_entity` | "LA", "the Anchorage one", "Ankorage" → item id(s) | `entity_resolution.py` |
| `get_item_metrics` | raw metrics for one item, no scoring | `dataset.py` |
| `aggregate_records` | "% of X that are Y" (category share) | `analytics.py` |
| `estimate_derived_metric` | "unmet demand at SFO, and why" (modeled, with a factor breakdown) | `analytics.py`, `runway_geometry.py` |
| `get_live_airport_status` | live operational status (closures/delays) — deliberately outside the scored path | `nasstatus.faa.gov`, real-time |

## `data/`

Committed, not generated at request time — `app/dataset.py` reads these
directly. `refresh_data.py` rebuilds all of them from the five public
sources listed in `DECISIONS_SUMMARY.md` §2; every fetch is idempotent
and keyless.

`raw_data/` is exactly what was fetched from each external source, untouched.
`processed_data/` is everything `refresh_data.py` builds or derives from
it — `app/dataset.py` only ever reads from `processed_data/`.

> **This branch (`deploy`) omits `data/raw_data/`.** It's never read at
> runtime — only `refresh_data.py` reads it, to rebuild `processed_data/`.
> Trimmed here to shrink the deploy image; `raw_data/` is present on `main`
> and is re-fetched fresh by `refresh_data.py` regardless.

| File | Contents |
|---|---|
| `raw_data/airports.csv`, `raw_data/runways.csv` | OurAirports bulk export — identity, geo, runway geometry |
| `raw_data/faa_cy2024_enplanements.xlsx`, `raw_data/faa_cy2025_enplanements_preliminary.xlsx` | FAA Commercial Service Enplanements |
| `raw_data/bts_anc_origin_summary.json` | Raw BTS T-100 pull for ANC (one-time `curl`, see `DECISIONS.md`) |
| `processed_data/census_county_population.json` | Census PEP Vintage 2025 county totals, two growth windows |
| `processed_data/airport_counties.json` | Airport → county FIPS join (via Census Geocoder) |
| `processed_data/anc_traffic_mix.json` | Built domestic/international departure share for ANC |
| `processed_data/candidates.json` | The built, joined table `dataset.py` actually loads — one row per airport, `_meta` block documents provenance and known limitations |
| `refresh_data.py` | Fetch-and-rebuild pipeline for everything above (stays at `data/`, alongside the two subfolders, not inside either) |

## `evals/` — the eval harness

Real, runnable — not a written plan. `evals/README.md` has the full
numbers; this is the file map.

| File | Job |
|---|---|
| `types.py` | The named anatomy: `Task`, `Trial`, `Trace`, `Outcome`, `Grader`, `Suite` — real dataclasses/ABCs, not dicts. |
| `runner.py` | Executes one `Trial` against a real provider, turns it into a graded `TrialResult`. |
| `suite.py` | A `Suite` is a list of `Task`s run for real, producing a `SuiteResult`. |
| `report.py` | Renders a `SuiteResult` as markdown (the brief's test-matrix format) and JSON. |
| `run_evals.py` | CLI entrypoint — `python -m evals.run_evals --provider mock\|openai`. |
| `tasks/seed_tasks.py` | The 26 seeded failure-mode tasks. |
| `tasks/fixtures.py` | Eval-only tools (e.g. the prompt-injection payload fixture) — not part of the shipped agent. |
| `graders/deterministic.py` | Code-based graders — fast, cheap, reproducible, but only catch what they're written to check. |
| `graders/llm_judge.py` | Model-based grading for open-ended quality (does an explanation cite real reasoning, without fabricating numbers) that no regex can check. |
| `judge_calibration_data.py`, `judge_validation.py` | The hand-labeled set the judge is checked against, and the agreement script (90% agreement, see `evals/README.md`). |
| `results/` | Committed real runs: one mock, one `openai`, one judge-validation report. Cited by exact filename from `DESIGN_DOC.md` and `evaluation_plan.md` — regenerate, don't rename. |

## `tests/` — pytest suite (296 tests)

Mirrors `app/` roughly one-to-one (`test_scoring.py`, `test_analytics.py`,
`test_entity_resolution.py`, `test_agent_loop.py`, `test_guardrails.py`,
`test_conversation.py`, `test_config.py`, `test_voice_api.py`,
`test_voice_client.py`), plus `test_tools_domain.py` and
`test_tools_uncovered.py` for the tool surface, `test_graders.py` for the
eval harness's own graders, and `test_markdown_renderer.py`, which runs
the shipped `static/markdown.js` under `node` (skips cleanly if `node`
isn't installed — `pytest` stays zero-setup either way).

## `static/` — the web UI

| File | Job |
|---|---|
| `index.html` | Single page: chat panel + live tool-call log + voice controls. Zero build step, zero new dependencies. |
| `markdown.js` | Escape-first markdown renderer for the agent's replies (see `DECISIONS_SUMMARY.md` §5 for why escape-first is a security property, not styling). |
| `voice.js` | Mic capture, local endpointing, playback, barge-in detection. |

## `scripts/` — one-off utilities, not part of the app or the test suite

| File | Job |
|---|---|
| `run_example_questions.py` | Runs the brief's four example questions end-to-end and prints the full transcript — the fastest way to see the agent work without opening the UI. |
| `smoke_test.py` | Manual end-to-end check against a real provider — not part of `pytest`. |
| `calibrate_resolver.py` | Picked `entity_resolution.py`'s relevance threshold from labeled data, not from feel. |

## Docs — which one to open

`README.md`, `DESIGN_DOC.md`, `DECISIONS.md`, `ASSUMPTIONS.md`, and
`evaluation_plan.md` are at the repo root — the brief's required
deliverables. This file and its sibling below live in `docs/`, since
neither is something the brief asks for; they're navigation aids for
whoever (Roi included) needs to find a specific file or decision fast.

| File | For |
|---|---|
| `README.md` (root) | Quickstart, layout, how to run it |
| `DESIGN_DOC.md` (root) | Scoring methodology, where AI is used, key tradeoffs — the brief's required design doc |
| `DECISIONS.md` (root) | The full build-order log — every decision, every rejected alternative, every number |
| `ASSUMPTIONS.md` (root) | Every data gap, unit conversion, staleness date |
| `evaluation_plan.md` (root) | The eval test matrix and real run results |
| `docs/DECISIONS_SUMMARY.md` | This file's sibling — every decision, by subject, a few sentences each |
| `docs/ARCHITECTURE.md` | This file |
