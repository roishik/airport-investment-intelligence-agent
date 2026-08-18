# Design / architecture document

The brief asks this document to explain three things: **scoring
methodology**, **key tradeoffs**, and **where/how AI is used**. Those are
sections 2, 4 and 3 below, in that order of importance.

---

## 1. What the agent does

This is a conversational tool for an airport-investment analyst asking
where terminal expansion or renovation is most likely to pay off, across
the full 515-airport FAA Commercial Service Enplanements universe. It
answers four distinct question shapes — filtered ranking, pairwise
comparison, single-entity aggregate, and a modelled causal quantity — by
calling deterministic Python functions and explaining their output; it
never computes a score, a percentage, or a ranking itself. It deliberately
does **not** model expansion *feasibility* (land, permitting, political
consent), does not use live operational status (weather, ground stops) as
a scoring input, and does not claim to know which airport is "truly"
best when the data doesn't decisively say so — the top of a ranking is
reported as tied when it is, not smoothed into a false winner.

### The four question shapes

The brief's examples are four different query archetypes, not four
phrasings of one. The tool surface exists to cover all four:

| Shape | Example | Primitive | Why it can't reuse the ranking path |
|---|---|---|---|
| Filtered ranking | New England expansion candidates | `find_items` → `compare_items` | — |
| Pairwise + ambiguous entity | LA vs Santa Ana congestion | `resolve_entity` → `compare_items` | "LA" is genuinely ambiguous; the resolver has to be able to say so |
| Single-entity aggregate | % long-haul out of Anchorage | `aggregate_records` | It's a share over one airport's own rows, not a comparison across airports |
| Derived + causal | Unmet demand at SFO, and why | `estimate_derived_metric` | The quantity is in no dataset; it has to be modelled, with its assumptions attached |

---

## 2. Scoring methodology

Five criteria, weights 25/25/20/15/15, applied to a default ranking
scoped to FAA hub class L/M/S (144 of 515 airports — see §4's "what was
deliberately not built" for why the other 371 are excluded from ranking,
not from the dataset). Bounds are the 5th/95th percentile of the eligible
set, measured 2026-08-18 and frozen as constants in `app/tools.py` rather
than recomputed per query, so a ranking is reproducible across runs.

### The framing problem this had to solve

The brief asks for airports where *"renovations will be most profitable
based on **increased** flight and passenger capacity."* That is a
question about **headroom** — unrealized capacity — not about current
size. A composite score over present-day traffic ranks the biggest
airports first and says nothing about whether expanding them returns
anything. The criteria below are chosen to proxy *unrealized* capacity
for that reason.

### Criteria

| Criterion | Weight | Bounds | Direction | Source | Defence |
|---|---|---|---|---|---|
| `traffic_growth` | 25 | −0.079 → 0.138 | higher better | FAA CY2024→CY2025 % change | Is pressure already rising? The cleanest headroom signal — r≈−0.02 with raw enplanements, i.e. genuinely independent of size. |
| `regional_demand_growth` | 25 | −0.0025 → 0.0241 | higher better | Census county population CAGR, 2022→2025 | Is the region itself growing? The only demand-side signal in the set; r≈0.10–0.18 with size — the fix for the "ranks by current size" failure the brief's framing punishes. |
| `catchment_monopoly` | 20 | 10.7 → 100.6 mi | higher better | Nearest scheduled-service competitor distance (haversine, computed against the full 515) | Can demand escape to another airport? r≈−0.06 with size — independent. |
| `capacity_pressure` | 15 | 201,439 → 7,823,094 | higher better | Enplanements ÷ air-carrier runway count | The only available congestion proxy, and what Q2 (LAX vs. SNA) reads from — but it correlates **r=0.89** with `absolute_scale`, so it is deliberately held to the lowest tier of weight and disclosed here rather than presented as independent. |
| `absolute_scale` | 15 | 564,368 → 26,519,646 | higher better | FAA CY2025 preliminary enplanements | "Size of the prize" — kept, but capped well under the ≤25% ceiling this design set for itself, so it cannot dominate. |

Net effect: the two genuinely decorrelated, forward-looking criteria
(`traffic_growth` + `regional_demand_growth`) carry **50%** of the
weight; the two size-flavoured ones (`capacity_pressure` +
`absolute_scale`, themselves correlated with each other) carry **30%**.
Sanity check that this works as intended: **LAX ranks 67th of 144**, not
1st — a pure size-ranking would put it first every time.

### Normalization and missing data

Every criterion is min-max normalized into `[0, 1]` against explicit
bounds declared alongside it, so a score is always interpretable as
"where in the stated range does this sit."

Real public aviation data is ragged — small airports are not required to
report everything large ones do. Rather than failing an airport because
one field is absent, `scoring.py` **drops the absent component and
renormalizes the remaining weights over what is actually present**, then
reports `covered_weight` and `missing_criteria` alongside the score so
the gap is visible rather than hidden. Below a coverage threshold
(default 0.5, exclusive) the airport is **excluded from the ranking
entirely** and listed separately, because a score built on scraps is
worse than an honest omission.

### Weight sensitivity — how much do the weights actually matter?

Real output of `weight_robustness_report(ELIGIBLE_IDS)` against the live
144-airport set, 2026-08-18:

```
baseline_top: BNA (Nashville, 0.6343)  — runner-up: DEN (Denver, 0.6317)
most_sensitive_criterion: catchment_monopoly (flips winner at 0.95x)

criterion                current_weight  flip_factor
traffic_growth           25              0.90
regional_demand_growth   25              0.90
catchment_monopoly       20              0.95
capacity_pressure        15              1.05
absolute_scale           15              1.05
```

**The headline finding is not a defect to explain away: the #1 slot is
not decisive.** BNA and DEN are 0.42% apart, and every one of the five
weights flips the winner at a 5–10% change — there is no weight in this
configuration that could move by 10% without changing which airport
leads. That is the honest answer to "why these weights": the *ranking's
overall shape* is what the weights are defending, not a specific #1.

`analyze_weight_sensitivity`, run on each criterion at 0.5× and 2.0×
(same live set):

| Criterion | ×0.5 τ | ×0.5 top changed? | ×2.0 τ | ×2.0 top changed? |
|---|---|---|---|---|
| `traffic_growth` | 0.839 | BNA→DEN | 0.765 | BNA→PVU |
| `catchment_monopoly` | 0.836 | BNA→DEN | 0.770 | no |
| `absolute_scale` | 0.915 | no | 0.874 | BNA→DEN |

Kendall tau stays **0.77–0.92** even when a single criterion's weight is
halved or doubled — the overall ordering is far more stable than the top
slot, which is the real defence: the weighting judgement is load-bearing
but not fragile. **Consequence for the product, not just the writeup:**
`compare_items` reports `tied_at_top`/`decisive` explicitly whenever the
top two scores are within 0.005 of each other (the same margin the BNA/
DEN pair sits inside), and the system prompt (rule 6) requires the model
to present a tie as a tie — BNA and DEN tie *for opposite reasons* (BNA
wins on growth + monopoly, DEN on scale + capacity pressure), and saying
so is a real finding about the domain, not something to paper over.

Weights chosen by judgment deserve to be challenged, so the challenge is
built in. `sensitivity_analysis()` re-runs the ranking under scaled
weights and reports per-airport rank and score deltas plus Kendall tau
against the baseline; `find_weight_flip_point()` returns the smallest
multiplier on a given criterion that changes the winner. If the winner
flips at 0.9×, the honest presentation is "these two are tied", and the
tool says so instead of leaving it to intuition.

---

## 3. Where and how AI is used

The dividing line: **the LLM decides what to look up and how to say it.
Python decides every number.**

| Decision | Made by | Enforced how |
|---|---|---|
| Which tool to call, with which arguments | LLM | tool schemas |
| What an ambiguous name refers to | Deterministic resolver proposes candidates with confidence and a `decisive` verdict; the LLM either accepts it or asks the user | `entity_resolution.py` returns, never decides |
| Normalization, weighting, ranking, aggregates, derived metrics | **Python only** | `scoring.py` / `analytics.py` are pure — zero I/O, zero LLM imports |
| The wording of the explanation | LLM | constrained to the breakdown the tool returned |
| Whether a number may be stated at all | Python | tools return per-component breakdowns; `NEVER_COMPUTE_RULE` in the system prompt forbids the model from doing arithmetic |

Two mechanisms make "the LLM never invents a number" true rather than
merely requested:

1. **Tools never return a bare score.** Every result carries raw value,
   normalized score, weight, and contribution per component. The model
   always has the arithmetic in hand, so it never needs to reconstruct it.
2. **The model cannot invent an identifier.** It has no way to enumerate
   airport IDs from memory — `find_items` and `resolve_entity` are the
   only routes to one, and both come from the dataset.

### Model choice

Default: **OpenAI `gpt-4o-mini`** (`LLM_PROVIDER=openai`) — small,
cheap, fast, and it's a genuine tool-calling model, which is the one
capability this whole design leans on; the task never needs the model's
own reasoning to be deep, only its tool selection and language to be
reliable. Real cost from the P4 eval run: 23 tasks, both the agent and
an independent LLM-judge grading pass, **$0.0205 total**.

Two swap paths, both real, not hypothetical:

- **`LLM_PROVIDER=anthropic`** (`claude-haiku-4-5`) — same tier,
  implemented against the documented Messages API tool-use shape, but
  not smoke-tested against a live key this build.
- **`LLM_PROVIDER=groq`** (`llama-3.3-70b-versatile`) — the free-tier
  path so a reviewer with no paid key can still see the real
  tool-calling agent run, not just `mock`'s scripted stand-in. Groq's
  API is wire-compatible with OpenAI's, so `GroqLLMProvider` is a thin
  subclass of `OpenAILLMProvider` — only the endpoint, default model,
  and key differ.

The swap cost, in both cases, is one environment variable plus a
credential — `app/agent_loop.py`, `app/main.py`, and `app/cli.py` never
change. That guarantee is enforced by construction, not just claimed:
every provider implements the same single-method `LLMProvider` protocol
(`app/providers/llm/base.py` — `name`, `model`, `chat()`) and the agent
loop only ever calls `provider.chat(messages, tools)`.

### 3a. Voice — the bonus, built twice on purpose

The brief calls a chat interface the requirement and voice the bonus.
There are two voice paths here, and the duplication is deliberate rather
than indecision.

**Path one: browser-native, zero credentials.** One-shot dictation via
`SpeechRecognition`, replies read aloud via `speechSynthesis`. No server
involvement, no key, no cost. It exists because "voice needs an API key
you have not set" should never be the same sentence as "voice does not
work at all" — anyone who opens this page gets *something*. Browser
support is stated rather than hidden: Chrome, Edge and Safari have
`SpeechRecognition`, Firefox does not, and both controls disable
themselves with an explanatory tooltip instead of failing on click.

**Path two: conversation mode.** An open microphone, endpointing in the
browser, real speech models on the server, spoken replies, and barge-in.
This is the one that is actually a conversation.

| Stage | Where | What |
|---|---|---|
| Capture, resample to 16 kHz | Browser | `static/voice.js` |
| Endpointing (energy VAD) | Browser | 200 ms to open, 800 ms of silence to close, 300 ms pre-roll |
| Transcription | Server | `POST /voice/transcribe` → `gpt-4o-mini-transcribe` |
| The turn itself | Server | **the existing `/chat/stream`** — same tools, same guardrails, same scoring |
| Synthesis | Server | `POST /voice/speak` → `gpt-4o-mini-tts`, one chunk at a time |
| Barge-in | Both | browser stops audio; `POST /voice/interrupt` fixes the transcript |

**The transcript goes through the existing chat endpoint.** There is no
`/voice/chat`. A spoken question gets the identical tool surface,
guardrails, deterministic scoring, and live tool log as a typed one, so
every claim in this document stays true when you talk to the agent
instead of typing at it. Voice is a modality here, not a second agent.

**Why the browser does the listening.** The conventional design streams
audio to the server over a WebSocket and detects turns there. Three
reasons not to: barge-in gets *faster*, because the microphone and the
speaker are both in the browser and stopping playback costs zero network
round-trips; nothing is uploaded during silence; and server-side frame
energy wants numpy, in a project whose dependency list is four packages.
What it costs is listed in §4 under what was not built.

**Barge-in is three steps, and the third is the one that matters.**
Stop playing. Stop synthesizing what has not played. Then rewrite the
stored reply to only the sentences the user actually heard
(`app/conversation.py`). The first two are what the user perceives; the
third is what keeps the next turn coherent. Without it the model believes
it said five sentences that were never audible, and a follow-up like
"what was the third one?" answers from text nobody heard. Truncation is
sentence-granular because sentences are the unit that gets synthesized
and played — word-level would need per-word timing that neither provider
returns from its plain synthesis endpoint. The UI redraws the interrupted
reply to match, so the screen and the transcript never disagree.

**Both speech providers are OpenAI, and that is a cost-of-entry decision
rather than a preference.** The app already needs an OpenAI key to run
against a real model, so speech in and speech out add zero new
credentials: a reviewer who can run the agent at all can also talk to it.
A second TTS vendor (`TTS_PROVIDER=google`, Neural2) is implemented
anyway, because an interface with exactly one implementation has never
been tested as an interface — two makes "we could move to ElevenLabs or
Cartesia" a statement about work already proven possible.

**What the energy VAD cannot do**, stated rather than discovered: it
cannot tell a genuine interruption from a backchannel. "Mm-hmm" while the
agent is talking will stop it. The barge-in threshold is deliberately
harder to trip than the turn-start threshold (350 ms and +6 dB, versus
200 ms) because a false barge-in cuts the agent off mid-answer and a
late one only costs a moment — but the underlying limitation is a
property of energy VAD, and the fix is a semantic turn detector, not a
better threshold.

**Echo cancellation is load-bearing.** With an open microphone next to a
speaker, the agent's own voice would trip the barge-in detector
continuously. `getUserMedia`'s `echoCancellation` constraint is what
makes this usable on laptop speakers rather than headphones only.

---
---

## 4. Key tradeoffs

### Ranking eligibility capped at FAA hub class L/M/S, not the full 515

Bought: a ranking that survives contact with real data. Scoring all 515
airports put Jack Edwards National (+126,403% YoY on 37,951 passengers)
and Adak Airport (2,524 passengers, ranked above SFO) into the top 50 —
percentage growth on a near-zero base is noise, not signal. Paid: a
fast-growing airport just below the primary-airport line is invisible to
the default ranking and has to be asked about by name (`find_items`/
`resolve_entity` still reach it — this is a ranking filter, not a data
cut). Chose FAA's own classification over a self-picked enplanements
floor specifically so the defence is "I used the regulator's line," not
"I chose a round number."

### `capacity_pressure` kept despite its 0.89 correlation with `absolute_scale`

Bought: the only available congestion proxy, and the one Q2 (LAX vs.
SNA) actually reads from — dropping it would leave that question with no
input at all. Paid: it is not the independent signal it looks like, so
keeping it risked silently reintroducing the "ranks by size" failure the
whole criteria design exists to avoid. Mitigated by weight (15%, tied for
lowest) and by disclosure — the correlation is stated in `DECISIONS.md`,
in this document's §2 table, and would be the first thing volunteered
under questioning, not the first thing found.

### Snapshotted data with stated staleness, not live-only

Every scored criterion is a snapshot, fetched once and rebuilt on demand
by `data/refresh_data.py`, never on the request path — enplanements,
population, and runway geometry do not change fast enough to justify a
live call, and a live dependency on four separate government APIs on the
scoring path would make every chat message as reliable as the flakiest
of the four. The one genuinely live call, FAA NAS Status, is kept
**outside** the scored path entirely and labelled as such in its own
tool response (`scope_note`) — a ground stop this afternoon is weather or
an equipment outage, not evidence about a decade-scale capital decision.
Staleness dates, by source: OurAirports (fetched 2026-08-18, changes
rarely), FAA enplanements (CY2025 preliminary + CY2024 final, ~6-month
lag at origin), Census PEP (Vintage 2025, revised annually), BTS T-100
(monthly grain through 2026-04). All four are keyless — rebuilding
`data/` from scratch needs no credentials at all.

### Hand-rolled agent loop, no framework

Bought: control over termination, guardrail placement, and the reasoning
trace; a stack trace that stays inside this repo; no dependency whose
behaviour I'd be guessing at. Paid: no free multi-agent handoff, no
durable state, no built-in retry policy. That's the right trade at this
size and the wrong one the moment a second agent or a human review queue
enters the picture.

### Deterministic scoring, not an LLM judgment call

Bought: reproducibility, unit-testability with no mocking, and the
ability to answer "why did this rank first" with arithmetic. Paid: the
criteria are only as good as the judgment that picked them, and that
judgment is mine. Mitigated, not solved, by the sensitivity analysis in
§2 — which quantifies how much the answer depends on those weights
instead of asserting that it doesn't.

### Regex guardrails, not a classifier

Bought: deterministic, fast, testable, and it cannot itself be prompt-
injected. Paid: it misses paraphrased attacks. A production version adds
a model-based detector *on top*, not instead.

### What was deliberately not built

An honest cut list is worth more than a longer feature list:

- **Expansion *feasibility*.** Nothing here knows whether an airport has
  land, an unexpired environmental approval, or political consent — all
  of which can veto a project that scores well. The ranking answers
  "where is the demand pressure," not "where can you actually build."
  `runway_count` is the closest available proxy and it is weak.
- **Delay-based congestion (FAA ASPM/OPSNET, BTS On-Time Performance).**
  Both blocked — ASPM needs an FAA login, BTS is behind the same
  bot-wall as T-100 segment data. The congestion story here leans on
  capacity/utilization proxies, not measured delay minutes.
- **True per-route long-haul data for Q3.** No public BTS table carries
  per-route distance/frequency; the real microdata is TranStats-only and
  bot-blocked. Q3 is answered as a domestic/international departure-share
  proxy instead, with the proxy's limitation stated in the answer itself.
- **A real catchment-area population signal.** `regional_demand_growth`
  is the county the airport physically sits in, not its true catchment —
  a radius-based multi-county aggregate would be the fix, deferred for
  time.
- **Persistent multi-user history or auth.** In-memory, single-session —
  fine for a live demo, not production.
- **Streaming ASR and streaming TTS.** Voice mode transcribes and
  synthesizes per utterance, not per token. A production stack streams
  both, so the first words are transcribed while the user is still
  speaking and the first audio plays while the rest is still being
  generated. Measured against the real endpoint, synthesis is where this
  costs the most: about two seconds, almost independent of length. Half
  of that is hidden by chunking the reply and overlapping requests (§3a),
  but the floor is real and streaming is the fix. Known divergence with a
  named upgrade path, not a gap being hidden.
- **Server-side turn detection.** Endpointing runs in the browser, so the
  server never sees a waveform and cannot apply a semantic turn detector
  — the 2026 state of the art, which decides a turn ended because the
  sentence finished, not because the room went quiet. §3a explains why
  the split is where it is; this is what it costs.
- **A production-grade injection classifier.** The regex guardrail
  catches the literal attack shapes tested against it; a fielded system
  would add a model-based detector *on top*, not instead — see "Regex
  guardrails, not a classifier" above.

---

## 5. How this would be evaluated

`evals/` is a runnable harness, not a written plan: 26 seeded tasks
across correctness, missing-data handling, self-computation refusal,
prompt injection, explanation quality and loop robustness, with
deterministic graders plus an LLM judge validated against hand labels.
`--compare` diffs a run against a previous one, which is what makes
"is v2 of this prompt better than v1" an answerable question rather than
an opinion. See `evaluation_plan.md`.

**Real numbers, 2026-08-18, against the real 515-airport dataset**
(`evals/results/openai_20260818T191158Z.md`,
`evals/results/mock_20260818T191251Z.md`):

| Provider | Pass rate | Avg partial-credit score |
|---|---|---|
| `openai` (gpt-4o-mini) | **24/26 = 92%** | 0.97 |
| `mock` (scripted stand-in, not real reasoning) | 9/26 = 35% | 0.81 |

**Judge-vs-human agreement** (`evals/judge_validation.py`, 10 hand-labeled
examples): **90% binary pass/fail agreement, mean absolute score
difference 0.80** (1–10 scale) — clears the "intern test" ≥80% bar the
research this program is based on treats as "the rubric is specific
enough to automate."

Two real bugs were found and fixed by running this suite against the
real domain data (a `find_items` crash on empty-filter calls, and a
number-parsing gap in the fabrication grader that misread comma
thousands-separators and percent-formatted rates) — see `evals/README.md`
for the detail. One real product gap is still open, not special-cased:
`ambiguous_vague_priorities_growth_not_congestion` — a stated-preference
question that the model answers on default weights instead of calling
`rank_by_priorities`.
