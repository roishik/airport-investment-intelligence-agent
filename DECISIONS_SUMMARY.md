# Decisions, by subject

`DECISIONS.md` is the full build log — one entry per non-obvious choice,
in the order it happened, with the rejected alternatives. It's the
record of *how* this got built and the raw material for defending any
individual line of code under questioning.

This file is the fast read: the same decisions, organized by subject
instead of by clock time, a few sentences each. Each bullet ends with a
pointer (`DECISIONS.md §...`) to the full entry if you need the "why
not X" detail, the numbers behind a claim, or the exact rejected
alternatives.

## 1. Agent loop & architecture

- **Hand-rolled loop, no framework** (`app/agent_loop.py`, ~70 lines).
  The point of this assignment is full control over the reasoning loop,
  tool dispatch, and data flow — not the biggest agent that can be
  built, but one where every component's purpose can be explained.
  → `DECISIONS.md` "Architecture decisions"
- **LLM calls are non-streaming.** The loop needs the complete
  `tool_calls` list before it can decide what to do next; streaming
  tokens on a tool-calling turn buys nothing. Streaming exists instead
  at the *tool-call log* level (`/chat/stream`, SSE) — see §7.
  → `DECISIONS.md` "Architecture decisions", "P5"
- **`LLM_PROVIDER` defaults to `mock`.** Cloning and running `pytest` or
  `python -m app.cli` needs zero setup — no key, no account. Mock is
  also the right default for tests that don't need an LLM at all: no
  reason to pay for or depend on a real model when nothing is being
  tested about it.
  → `DECISIONS.md` "Architecture decisions"
- **Tool errors are caught and returned as `{"error": ...}` data**, never
  allowed to crash the loop or vanish silently. The model is told about
  the failure and expected to say so. A raised (not caught) error means
  the bug is in this code, not in the world the tool is describing.
  → `DECISIONS.md` "Architecture decisions"
- **`max_turns` (default 6) hard-stops the loop**, and `MaxTurnsExceeded`
  carries the partial transcript and tool log rather than raising bare —
  a demo that trips the ceiling gets an honest partial answer, not a
  blank screen and an HTTP 500.
  → `DECISIONS.md` "Architecture decisions", "P3"

## 2. Data pipeline

- **Five keyless public sources, no fixed refresh built (deferred, not
  skipped):** OurAirports (identity/geo/runways), FAA Commercial Service
  Enplanements (volume + hub class), US Census PEP county population
  (the only demand-side signal), BTS T-100 Segment Summary filtered to
  ANC (Q3's long-haul proxy), FAA NAS Status (live operational color,
  outside the scored path). None need an account or a credential.
  → `DECISIONS.md` "Data pipeline — consolidated summary"
- **Scope grew from a curated 27 airports to the full FAA 515-airport
  universe, Roi's call.** The brief's four questions are illustrative,
  not the whole intended scope — a 27-airport set answers a demo, not a
  general-purpose tool. This surfaced (and fixed) a silent join bug: FAA
  LocIDs were colliding with *foreign* airports sharing the same
  3-letter code (14 airports, incl. Michigan resolving to Istanbul).
  → `DECISIONS.md` "Assignment decisions" [14:53], [17:46]
- **Q3's "long haul %" is a domestic/international departure-share
  proxy, not a true distance threshold — stated as a proxy, not hidden.**
  The real per-route BTS T-100 microdata is bot-blocked on every public
  endpoint checked (confirmed via the Socrata API, not just the visible
  catalog page). A working alternative (`transtats.bts.gov`'s direct
  PREZIP file URLs, unblocked) was found post-submission-prep and
  evaluated but not integrated this close to the deadline — see
  `DECISIONS.md`'s final section.
  → `DECISIONS.md` "Assignment decisions" [14:28], [15:38]
- **Regional demand uses county population, not city or CBSA** — county
  gives an exact FIPS join via geocoding with no boundary definitions to
  invent. Known and stated limitation: county ≠ catchment (Boston's
  Suffolk County is ~792k against a ~4.9M real metro catchment) — this
  is a growth-*trend* signal, never a market-size one.
  → `DECISIONS.md` "Assignment decisions" [17:46]
- **Two population growth windows reported (2020→2025 and 2022→2025),
  not one.** The full window bakes in the pandemic migration shock as if
  it were a trend (SFO reads −0.50%/yr full-window, +0.51%/yr recent).
  Reporting a single number would present a window artifact as a
  structural finding.
  → `DECISIONS.md` "Assignment decisions" [17:46]
- **Missing data is handled by renormalizing weights across available
  criteria, never by dropping the item or crashing.** 14 of 515 airports
  (Puerto Rico + island territories) have no population figure; they
  still rank on their remaining criteria. This is `scoring.py`'s
  missing-data fix earning its keep on real ragged data.
  → `DECISIONS.md` "Assignment decisions" [17:46]

## 3. Scoring & criteria (the defended artifact)

- **Ranking eligibility is capped at FAA hub class L/M/S (144 of 515
  airports) — a ranking filter, not a data cut.** Scoring all 515 put
  airports with a few thousand annual passengers into the top 50 purely
  as percentage-growth artifacts (one at +126,403% YoY on 37,951
  passengers). Chose FAA's own hub classification over an invented
  enplanements floor: "I used the regulator's definition of a primary
  airport," not a number picked to make the output look right.
  → `DECISIONS.md` "P2 — criteria and weights"
- **Five criteria, weights 25/25/20/15/15:** `traffic_growth`,
  `regional_demand_growth`, `catchment_monopoly`, `capacity_pressure`,
  `absolute_scale`. Forward-looking signals carry 50%, size-flavored
  ones 30% — the brief asks where investment is most profitable based
  on *increased* capacity, a headroom question, not a size question.
  Sanity check: LAX ranks 69th of 144, not 1st.
  → `DECISIONS.md` "P2 — criteria and weights"
- **`capacity_pressure` kept despite r=0.89 correlation with
  `absolute_scale`, disclosed rather than hidden.** It's the most direct
  available congestion proxy and the only thing Q2 (LAX vs. SNA
  congestion) has to read from — removing it would leave that question
  unanswerable. Mitigation: both held to 30% combined, correlation
  stated in `DESIGN_DOC.md`.
  → `DECISIONS.md` "P2 — criteria and weights"
- **The #1 slot is not decisive, and the ranking says so.** Nashville and
  Denver are 0.41% apart at the top, and the winner flips at a 10%
  weight change on `traffic_growth` — for opposite reasons (Nashville
  wins on growth, Denver on scale). `weight_robustness_report` and
  `analyze_weight_sensitivity` surface this explicitly rather than
  implying a decisive winner. Kendall tau stays 0.76–0.91 across halving
  or doubling any single criterion — the ordering as a whole is far more
  stable than the top slot.
  → `DECISIONS.md` "P2 — criteria and weights"
- **Normalization is symmetric percentile clipping (5th/95th of the
  eligible 144) for all five criteria, not log-transforms for the
  skewed ones.** One consistent rule across every criterion is easier to
  defend than five bespoke ones.
  → `DECISIONS.md` "P2 — criteria and weights"

## 4. Tools & entity resolution

- **Every tool returns a per-component breakdown (raw value, normalized
  score, weight, contribution), never a bare score** — so the LLM
  explains a number it never computed. Enforced at two levels: the
  tool's return shape (`app/tools.py`) and the system prompt's
  `NEVER_COMPUTE_RULE`.
  → `DECISIONS.md` "Architecture decisions"
- **The eligibility gate (§3) lives inside `compare_items` itself, not
  in a filter the model has to remember to pass.** It leaked once: asked
  for New England candidates without the filter, a 3,145-passenger
  airport came back ranked 4th — the exact failure the gate exists to
  prevent. General lesson: a correctness rule the model has to remember
  is not a rule, it's a suggestion. Ineligible airports are returned
  with a reason, not silently dropped — the user asked about them.
  → `DECISIONS.md` "P3 — wiring real data into the agent"
- **`resolve_entity` needed a metro layer and a short-code edit-distance
  fallback, found by using the agent, not by reading the code.** "LA"
  is not an airport (it's 5 of them — `METRO_AIRPORTS`, the one
  hand-written lookup in the file, because no public column encodes
  shared metro markets). "LBG" (a transposition of the real "LGB") came
  back empty because Jaro-Winkler's match window collapses at length 3
  — fixed narrowly with a restricted edit-distance fallback gated to
  code-shaped queries only, to avoid reopening the false-positive case
  that motivated the original length guard.
  → `DECISIONS.md` "P3", "Two bugs found using the shipped agent"
- **A category with zero matching rows and an unknown category are
  different failures, and the tool distinguishes them.** Asking for
  ANC's "long haul" share (not a real category) used to return a
  confident, wrong "0%." Fixed with `unknown_category` +
  `known_categories` + a `category_semantics` string telling the model
  which real category is the right proxy and what its limitation is.
  → `DECISIONS.md` "P3 — wiring real data into the agent"
- **`list_criteria()` exists because the agent once refused to state its
  own scoring weights** when asked directly ("proprietary" — nothing in
  the code said that; it had no tool to route a pure methodology
  question to and fell back to a generic corporate-assistant reflex).
  The weights were always real and static; now there's a tool call that
  makes them traceable the same way every other number in this agent
  is.
  → `DECISIONS.md` "Voice — the cheap path, built" [23:17]

## 5. Guardrails & safety

- **Guardrails are a deterministic regex pre-filter, not a second LLM
  call.** An "is this an injection?" model call would be slower,
  non-deterministic, and itself attackable. Full explainability requires
  determinism, and a protection built from another LLM just moves the
  problem instead of solving it.
  → `DECISIONS.md` "Architecture decisions"
- **Tool output is treated as untrusted data on the way in; rendered
  markdown is treated the same way on the way out.** The threat isn't
  the model deciding to attack the page — it's that tool results (public
  data fields this repo doesn't control) get quoted back into replies
  that land in the browser. `static/markdown.js` escapes first, once,
  before any markdown transform runs, so there is no path from reply
  text to live markup; link hrefs are scheme-allowlisted
  (http/https/mailto) since that's the one place an attacker-controlled
  value lands inside an HTML attribute.
  → `DECISIONS.md` "Markdown in the chat panel"
- **Upstream API errors never reach the browser verbatim.** Both speech
  endpoints send a key in an Authorization header; an upstream 4xx body
  can echo request details back. Logged server-side, a flat message
  returned to the client — tested directly against a fake key.
  → `DECISIONS.md` "Voice conversation mode"

## 6. Eval harness (the headline differentiator)

- **26 seeded failure-mode tasks, deterministic + LLM-judge graders,
  judge validated at 90% agreement against hand labels.** A written eval
  *plan* with nothing executable is the common baseline for this kind of
  submission; this one runs. `evals/results/` holds committed, real
  runs (mock and `gpt-4o-mini`), not described-but-not-run numbers.
  → `evaluation_plan.md`, `DECISIONS.md` "P4"
- **A mutation test found the single highest-value bug in the whole
  session, and a manual read never would have.** Squaring
  `scoring.py`'s contribution formula moved LAX's real score by ~0.05
  and left all 257 tests passing — every numeric assertion happened to
  sit at a fixed point of `x²=x` (0, 0.5, or 1.0), or checked ordering
  only. Fixed with a hand-derived arithmetic test at a value that isn't
  one of those three, plus a pin against the real dataset.
  → `DECISIONS.md` "Eval harness integrity"
- **A dedicated review pass found graders that couldn't catch what they
  were named for:** a "ground truth" grader that recomputes the same
  formula it's checking (not independent — its docstring said otherwise,
  now corrected); a number-fabrication grader whose regex silently
  truncated comma-formatted and un-comma'd numbers alike; a judge
  response parser that failed closed, silently, on markdown-wrapped
  scores; an injection task that only checked the payload was flagged,
  not whether the model actually complied with it; two self-computation
  tasks that scored full marks whether the agent worked or was
  completely broken.
  → `DECISIONS.md` "Eval harness integrity, and closing the
  standalone-review gaps"
- **One real, honest finding was left open rather than engineered
  away:** `gpt-4o-mini` over-refuses under "just eyeball it, don't call
  tools" pressure, rather than making a reasonable default query. Not a
  correctness violation (nothing fabricated) — a real usability gap,
  documented in the task notes and `evaluation_plan.md` instead of
  softened out of the suite.
  → `DECISIONS.md` "Eval harness integrity"

## 7. UI & streaming

- **SSE streams the tool-call log, not the model's tokens** — the
  architecture decision that LLM calls are non-streaming (§1) is
  unchanged. What was missing was visibility: on a multi-tool question
  the UI showed nothing for seconds, then dumped the whole log at once.
  One `on_tool_call` hook fires as each tool call finishes; the loop's
  behavior is provably identical whether a caller passes the hook or
  not.
  → `DECISIONS.md` "P5 — free-tier provider + SSE streaming"
- **Single static HTML page, zero build step, zero new dependencies** —
  matches the "no framework" posture everywhere else in the repo. The
  restyle (light canvas, dark code-viewport panels, violet reserved for
  live state) is presentational only; no scoring, tool, eval, or prompt
  behavior changed. Two typefaces (sans for the agent's prose, mono for
  every number and tool call) make the system prompt's core rule — "you
  explain a score, you never compute one" — visible as a design choice.
  → `DECISIONS.md` "UI restyle"

## 8. Voice — two paths, on purpose

- **Browser-native (`SpeechRecognition`/`speechSynthesis`) stays as a
  no-setup fallback; a real conversation mode was added alongside it,
  not instead of it.** "Voice needs a key you haven't set" should never
  mean "voice doesn't work at all" — anyone who opens the page gets
  something.
  → `DECISIONS.md` "Voice — the cheap path, built", "Voice conversation
  mode"
- **Conversation mode reuses `/chat/stream`. There is no `/voice/chat`.**
  A spoken question gets the identical tool surface, guardrails,
  deterministic scoring, and live tool-call log as a typed one — voice
  is a modality, not a second agent that could drift out of sync.
  → `DECISIONS.md` "Voice conversation mode"
- **The browser does VAD and endpointing, not the server** — mainly
  because barge-in has to be instant, and the mic and speaker are both
  already in the browser; routing it through a server adds a network
  round-trip to the single most latency-sensitive interaction in the
  feature.
  → `DECISIONS.md` "Voice conversation mode"
- **Barge-in is three steps, and the third is the one that matters:**
  stop playback, abandon unplayed audio, then rewrite the *stored
  transcript* to only what was actually heard. Without step three the
  model believes it said things nobody heard, and a follow-up gets
  answered from text that was never spoken. This step fails invisibly,
  which is why it has nine dedicated tests while the audio path has
  none.
  → `DECISIONS.md` "Voice conversation mode"
- **Named limitation, stated rather than discovered by a reviewer:**
  energy-based VAD can't distinguish an interruption from a backchannel
  — "mm-hmm" while the agent talks will stop it. The fix is a semantic
  turn detector, not a better threshold.
  → `DECISIONS.md` "Voice conversation mode"

## 9. Testing & verification practice

- **Bugs were found by running the four brief questions and the shipped
  UI, not by reading the code** — the eligibility-gate leak, the "0%
  long haul" false answer, `resolve_entity("LA")` misfiring, and the
  "LBG" empty-result bug were all caught this way. Reading catches
  bugs you already know the shape of; running catches the ones you
  don't.
  → `DECISIONS.md` "P3", "Two bugs found using the shipped agent"
- **296 tests, cold-clone verified with zero keys.** A genuine second
  `git clone` into a scratch directory, fresh venv: `pytest` green, the
  mock CLI runs, the server boots, then all four brief questions
  answered end-to-end against real `gpt-4o-mini` from that same clone.
  → `DECISIONS.md` "Brief conformance — final verification"

## 10. Deliberately not built (scope cuts, not oversights)

- **True per-route BTS T-100 data for Q3.** Bot-blocked on every checked
  public endpoint; a working alternative access pattern was found and
  evaluated post-submission-prep but not integrated this close to the
  deadline (§2).
- **Automated data refresh (cron / one-click).** Fully designed — cadence,
  endpoint, safety model — but doesn't help answer any of the four
  scored questions, so it stayed a design note rather than code.
- **OpenSky Network for true per-flight long-haul %.** Evaluated as the
  best available option if picked up later (free tier, real ADS-B data,
  the only option that reliably sees cargo flights); registration is a
  Roi-only action, so it wasn't started this session.
- **Streaming ASR (Soniox/Speechmatics-style).** A known, honestly-stated
  scope cut — batch `gpt-4o-mini-transcribe` instead, with a named
  upgrade path.
- **Semantic turn detection, dark mode, attachment UI.** Named and
  rejected on purpose — an energy-based VAD's known weakness, a light
  design shipped without a second theme the night before submission, and
  a control for a feature (file attachments) this agent doesn't have.

  → Full detail and rejected alternatives for every item above:
  `DECISIONS.md`. Data gaps and their staleness dates: `ASSUMPTIONS.md`.
