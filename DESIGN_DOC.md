# Design / architecture document

The brief asks this document to explain three things: **scoring
methodology**, **key tradeoffs**, and **where/how AI is used**. Those are
sections 2, 4 and 3 below, in that order of importance.

---

## 1. What the agent does

> **TODO(P6)** — one paragraph: the question it answers, for whom, and
> what it deliberately does not do.

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

> **TODO(P6)** — the criteria, their weights, their normalization bounds,
> and the argument for each. This is the most-defended section in the
> document; write it in full.

### The framing problem this had to solve

The brief asks for airports where *"renovations will be most profitable
based on **increased** flight and passenger capacity."* That is a
question about **headroom** — unrealized capacity — not about current
size. A composite score over present-day traffic ranks the biggest
airports first and says nothing about whether expanding them returns
anything. The criteria below are chosen to proxy *unrealized* capacity
for that reason.

### Criteria

> **TODO(P6)** — table: criterion, weight, bounds, direction, source
> field, and the one-sentence defence of each.

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

> **TODO(P6)** — paste the real `weight_robustness_report` output: the
> flip point, the Kendall tau, and what it means for how confidently the
> top of the ranking should be read.

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

> **TODO(P6)** — which model, why that tier, and what the swap costs.

---

## 4. Key tradeoffs

> **TODO(P6)** — the domain-specific ones. The structural ones are below
> and are already true.

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

### Snapshotted data with stated staleness, not live-only

> **TODO(P6)** — the real argument once the sources are settled: which
> data is fetched live, which is a dated snapshot, and why that split.

### What was deliberately not built

> **TODO(P6)** — the scope cuts, each with its reason. An honest cut list
> is worth more than a longer feature list.

---

## 5. How this would be evaluated

`evals/` is a runnable harness, not a written plan: 23 seeded tasks
across correctness, missing-data handling, self-computation refusal,
prompt injection, explanation quality and loop robustness, with
deterministic graders plus an LLM judge validated against hand labels.
`--compare` diffs a run against a previous one, which is what makes
"is v2 of this prompt better than v1" an answerable question rather than
an opinion. See `evaluation_plan.md`.

> **TODO(P8)** — paste the final run's headline numbers.
