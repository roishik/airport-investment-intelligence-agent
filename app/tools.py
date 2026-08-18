"""
tools.py — example tool(s) the agent can call.

The point of this file: the LLM never sees a KPI it has to compute. It
only ever sees numbers app/scoring.py already computed, PLUS the raw
inputs, so it can talk about them without ever being trusted to do the
arithmetic. Every tool below returns a per-component breakdown (raw
value, normalized score, weight, contribution) — never a bare number.

In a real rep, replace `_MOCK_DATASET` and `fetch_item_metrics` with an
actual public-API call (requests/httpx, with a timeout and real error
handling). Nothing else here — the shape tools return to the LLM — should
need to change. Keep TOOL_SCHEMAS' descriptions explicit about "call this
tool, don't estimate" — that instruction earns its keep at the tool level,
not just in the system prompt.
"""
from __future__ import annotations

from typing import Any, Callable

from app.analytics import (
    SUPPORTED_OPERATIONS,
    DerivedMetricResult,
    FactorInput,
    aggregate,
    build_derived_metric,
    filter_items,
    known_attribute_keys,
)
from app.entity_resolution import resolve
from app.scoring import (
    PRIORITY_EMPHASIS_FACTOR,
    Criterion,
    apply_priority_emphasis,
    find_weight_flip_point,
    rank_items,
    scale_criterion_weight,
    sensitivity_analysis,
)

# Stand-in for "call a public API and get back structured data." Kept as
# an in-memory dict here so the WHOLE app — agent loop, tools,
# scoring, chat UI — is runnable offline with zero network dependency and
# zero API keys. Swap fetch_item_metrics()'s body for a real HTTP call
# when you wire up the real assignment; see README "Tool error handling".
_MOCK_DATASET: dict[str, dict[str, float]] = {
    "option_a": {"cost": 120.0, "quality": 8.5, "lead_time_days": 3},
    "option_b": {"cost": 90.0, "quality": 6.0, "lead_time_days": 7},
    "option_c": {"cost": 150.0, "quality": 9.2, "lead_time_days": 1},
}

# Categorical attributes, kept SEPARATE from the numeric metrics above:
# these are what you filter/subset on, not what you score on. Mixing the
# two in one dict is how a categorical value ends up accidentally
# normalized as if it were a KPI.
_MOCK_ATTRIBUTES: dict[str, dict[str, str]] = {
    "option_a": {"region": "north", "tier": "premium", "status": "active"},
    "option_b": {"region": "south", "tier": "standard", "status": "active"},
    "option_c": {"region": "north", "tier": "premium", "status": "retired"},
}

# Per-item sub-records — the granularity a "what share of X is Y?"
# question needs. A composite score can't answer that: it's a count over
# a subset of one entity's own rows, not a ranking across entities. This
# is the shape behind the brief's "percentage of long haul flights out of
# Anchorage" question.
_MOCK_RECORDS: dict[str, list[dict[str, Any]]] = {
    "option_a": [
        {"category": "long_haul", "units": 40.0},
        {"category": "short_haul", "units": 60.0},
        {"category": "long_haul", "units": 20.0},
    ],
    "option_b": [
        {"category": "short_haul", "units": 90.0},
        {"category": "long_haul", "units": 10.0},
    ],
    "option_c": [
        {"category": "long_haul", "units": 75.0},
        {"category": "short_haul", "units": 25.0},
    ],
}

# Inputs to the derived/modeled metric (A5). Deliberately NOT a stored
# "unmet_demand" column — the whole point is that the answer exists in no
# dataset and has to be computed from observable proxies, with its
# assumptions visible. See app/analytics.py:estimate_unmet_demand.
_MOCK_DEMAND_INPUTS: dict[str, dict[str, float]] = {
    "option_a": {"served_units": 120.0, "capacity_units": 130.0, "turnaways": 25.0, "waitlist": 18.0},
    "option_b": {"served_units": 100.0, "capacity_units": 180.0, "turnaways": 2.0, "waitlist": 1.0},
    "option_c": {"served_units": 100.0, "capacity_units": 105.0, "turnaways": 40.0, "waitlist": 30.0},
}

# item_id -> every text a user might plausibly use to refer to it. The id
# itself is included so an exact-id query still resolves through the same
# path (no special case). In a real rep this comes from the dataset's own
# name/alias columns — e.g. an airport's IATA code, ICAO code, official
# name, and city — NOT from a hand-written list.
#
# Deliberately populated with names that collide ("option A" vs "option
# alpha" both plausibly meaning option_a; "the cheap one" matching
# nothing well) so the ambiguity path is exercised by the offline
# offline path rather than only appearing once real data lands.
_ENTITY_CATALOG: dict[str, list[str]] = {
    "option_a": ["option_a", "Option A", "Alpha", "the alpha option"],
    "option_b": ["option_b", "Option B", "Bravo", "the bravo option"],
    "option_c": ["option_c", "Option C", "Charlie", "the charlie option"],
}

# Example criteria — replace with the real assignment's KPIs. Bounds are
# the min-max normalization window (see Criterion.normalize in scoring.py),
# not a hard validity range; values outside them just clamp to 0 or 1.
DEFAULT_CRITERIA: list[Criterion] = [
    Criterion(name="cost", weight=1.0, lower_bound=80, upper_bound=160, higher_is_better=False),
    Criterion(name="quality", weight=2.0, lower_bound=0, upper_bound=10, higher_is_better=True),
    Criterion(name="lead_time_days", weight=1.0, lower_bound=0, upper_bound=10, higher_is_better=False),
]


class UnknownItemError(KeyError):
    pass


def fetch_item_metrics(item_id: str) -> dict[str, float]:
    """Stand-in for a public-API call. Raises UnknownItemError for unknown
    ids — replace with real HTTP error handling (timeouts, 4xx/5xx,
    retries) in the real assignment. The agent loop treats any exception
    raised here as a tool error, reports it in the tool log, and never
    fabricates a result — see agent_loop.py."""
    if item_id not in _MOCK_DATASET:
        raise UnknownItemError(f"unknown item_id={item_id!r}; known ids: {list(_MOCK_DATASET)}")
    return dict(_MOCK_DATASET[item_id])


# ── OpenAI-style tool schemas (Anthropic provider converts these; see
#    app/providers/llm/anthropic_llm.py) ────────────────────────────────────
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "compare_items",
            "description": (
                "Fetch metrics for the given item ids and rank them using the "
                "deterministic scoring function. Returns, for every ranked "
                "item, its total score and a per-criterion breakdown (raw "
                "value, normalized score, weight, contribution), plus a "
                "separate 'excluded' list of items that had too little data "
                "to score fairly (see covered_weight/missing_criteria on "
                "each) — mention exclusions to the user rather than ignoring "
                "them. Always call this tool for any ranking or comparison "
                "question — never estimate or guess a score or ranking "
                "yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Item ids to compare, e.g. ['option_a', 'option_b'].",
                    }
                },
                "required": ["item_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_item_metrics",
            "description": (
                "Fetch raw metrics for a single item id, with no scoring "
                "applied. Use this for factual questions about one item that "
                "don't require a ranking or comparison."
            ),
            "parameters": {
                "type": "object",
                "properties": {"item_id": {"type": "string"}},
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_entity",
            "description": (
                "Turn a user's free-text reference to a thing ('the alpha "
                "one', a partial or misspelled name) into concrete item ids. "
                "ALWAYS call this before compare_items or get_item_metrics "
                "when the user named something in words rather than giving an "
                "exact id — never guess or invent an id yourself. Returns "
                "candidates with a confidence and a per-signal breakdown, plus "
                "a 'decisive' flag. If decisive is false, you MUST NOT silently "
                "pick the top candidate: either ask the user which one they "
                "meant, or state plainly which one you assumed and why before "
                "continuing. If candidates is empty, say nothing matched — do "
                "not substitute a similar-sounding item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The user's own words for the item, e.g. 'the alpha option'.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_items",
            "description": (
                "Find every item matching a set of attribute filters (all "
                "filters must match — AND, not OR). Use this whenever the user "
                "describes a GROUP rather than naming items ('the ones in the "
                "north region', 'all premium tier'). NEVER list ids from "
                "memory to build such a group — call this. Returns the "
                "matching ids plus the attribute keys that actually exist, so "
                "you can tell the user when they asked about a field the "
                "dataset doesn't have."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "description": (
                            "Attribute name -> required value, e.g. "
                            "{'region': 'north', 'tier': 'premium'}. Matching is "
                            "case-insensitive."
                        ),
                        "additionalProperties": {"type": "string"},
                    }
                },
                "required": ["filters"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_records",
            "description": (
                "Compute a deterministic aggregate (share, mean, count, sum) "
                "over ONE item's sub-records, optionally restricted to a "
                "category. This is the tool for single-entity statistics like "
                "'what percentage of X's volume is long haul?' — that is NOT a "
                "ranking question, so do not use compare_items for it. "
                "'share' is computed on units/magnitude; the record counts are "
                "returned too, so if the user meant share-by-count you can give "
                "that instead. Never compute a percentage yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": list(SUPPORTED_OPERATIONS),
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional record category to restrict to, e.g. 'long_haul'.",
                    },
                },
                "required": ["item_id", "operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_derived_metric",
            "description": (
                "Estimate a MODELLED quantity that exists in no dataset — "
                "currently 'unmet_demand' — and return it with the contributing "
                "factors, their magnitudes, the model's assumptions, a "
                "confidence level, and a caveat. Use this for 'what is the "
                "unmet demand at X, and why?'-shaped questions. When explaining "
                "the 'why', use ONLY the returned factors and their magnitudes; "
                "never invent a cause. Always report the confidence and caveat "
                "— this is a model output, not an observation, and presenting "
                "it as a measured fact is wrong."
            ),
            "parameters": {
                "type": "object",
                "properties": {"item_id": {"type": "string"}},
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_by_priorities",
            "description": (
                "Rank items with the weighting adjusted to priorities the user "
                "stated in their own words ('I care about being fast and "
                "cheap', 'quality matters most, budget is flexible'). Map their "
                "words onto criterion NAMES and pass those; you do not choose "
                "how much to reweight — the tool applies a fixed factor. "
                "Returns BOTH the default ranking and the adjusted one, plus an "
                "'assumption_to_state' string. You MUST tell the user which "
                "criteria you emphasized and that it reflects your reading of "
                "their words — never present a reweighted ranking as if it were "
                "the neutral one. If the user states priorities but names no "
                "items, call find_items or ask which items they mean first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                    "emphasize": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Criterion names the user cares MORE about, e.g. ['cost', 'lead_time_days'].",
                    },
                    "deemphasize": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Criterion names the user cares LESS about.",
                    },
                },
                "required": ["item_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_weight_sensitivity",
            "description": (
                "Re-rank the given items with ONE criterion's weight scaled by "
                "a factor, and report what moved: whether the winner changed, "
                "how far each item shifted, and a Kendall tau rank-correlation "
                "(1.0 = order unchanged). Call this when the user asks why a "
                "weight was chosen, what happens if it's wrong, or how "
                "sensitive the ranking is. Report the result honestly even "
                "when it shows the ranking is fragile."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                    "criterion": {"type": "string", "description": "Which criterion's weight to perturb."},
                    "factor": {
                        "type": "number",
                        "description": "Multiplier on that weight; 0.5 halves it, 2.0 doubles it.",
                    },
                },
                "required": ["item_ids", "criterion", "factor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "weight_robustness_report",
            "description": (
                "For every criterion, find the smallest weight multiplier that "
                "would change the top-ranked item. Use this to answer 'how "
                "confident are you in this ranking?' or 'which weight matters "
                "most?'. A flip factor near 1.0 means the result hangs on that "
                "weight and the top items should be described as close rather "
                "than as a clear winner — say so plainly when that's the case."
            ),
            "parameters": {
                "type": "object",
                "properties": {"item_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["item_ids"],
            },
        },
    },
]


def compare_items(
    item_ids: list[str], criteria: list[Criterion] | None = None, coverage_threshold: float = 0.5
) -> dict[str, Any]:
    criteria = criteria or DEFAULT_CRITERIA
    items = {item_id: fetch_item_metrics(item_id) for item_id in item_ids}
    result = rank_items(items, criteria, coverage_threshold=coverage_threshold)
    return {
        "criteria": [
            {"name": c.name, "weight": c.weight, "higher_is_better": c.higher_is_better}
            for c in criteria
        ],
        "coverage_threshold": coverage_threshold,
        "ranking": [
            {
                "rank": r.rank,
                "item_id": r.item_id,
                "total_score": round(r.total_score, 4),
                "covered_weight": round(r.covered_weight, 4),
                "missing_criteria": list(r.missing_criteria),
                "components": [
                    {
                        "criterion": comp.criterion,
                        "raw_value": comp.raw_value,
                        "normalized_score": round(comp.normalized_score, 4),
                        "weight": round(comp.weight, 4),
                        "contribution": round(comp.contribution, 4),
                    }
                    for comp in r.components
                ],
            }
            for r in result.ranked
        ],
        # Items with SOME data but too little of it to score fairly, per
        # coverage_threshold — surfaced explicitly rather than silently dropped,
        # so the LLM can tell the user "N excluded, here's why" instead of
        # producing a ranking that quietly omits them with no explanation.
        "excluded": [
            {
                "item_id": e.item_id,
                "covered_weight": round(e.covered_weight, 4),
                "missing_criteria": list(e.missing_criteria),
                "reason": e.reason,
            }
            for e in result.excluded
        ],
    }


def get_item_metrics(item_id: str) -> dict[str, Any]:
    return {"item_id": item_id, "metrics": fetch_item_metrics(item_id)}


def resolve_entity(query: str) -> dict[str, Any]:
    """Free-text name -> candidate item ids, with confidence and a
    decisive/ambiguous verdict.

    Zero matches is a normal outcome of a fuzzy search, not a caller
    mistake, so it comes back as an empty candidate list with
    decisive=false — NOT as an exception. That's the deliberate contrast
    with fetch_item_metrics's UnknownItemError, where being handed an id
    that doesn't exist really is a bug worth naming loudly.
    """
    result = resolve(query, _ENTITY_CATALOG)
    return {
        "query": result.query,
        "decisive": result.decisive,
        "candidates": [
            {
                "item_id": c.item_id,
                "matched_text": c.matched_text,
                "confidence": c.confidence,
                "signals": dict(c.signals),
            }
            for c in result.candidates
        ],
    }


def find_items(filters: dict[str, str]) -> dict[str, Any]:
    """Attribute filter -> matching ids. Also returns the attribute keys
    that actually exist, so an unknown field reads as "there is no such
    field" rather than as "nothing matched" — those are different
    answers and conflating them misleads the user."""
    matched = filter_items(_MOCK_ATTRIBUTES, filters)
    known_keys = known_attribute_keys(_MOCK_ATTRIBUTES)
    unknown_keys = [k for k in filters if k.casefold() not in known_keys]
    return {
        "filters": dict(filters),
        "item_ids": list(matched),
        "match_count": len(matched),
        "known_attribute_keys": list(known_keys),
        # Non-empty means the caller filtered on a field that doesn't
        # exist, so item_ids is empty for a REASON — not because nothing
        # in the dataset qualifies.
        "unknown_filter_keys": unknown_keys,
    }


def aggregate_records(item_id: str, operation: str, category: str | None = None) -> dict[str, Any]:
    """Single-entity statistic over sub-records. Not a ranking, and
    deliberately a separate code path from scoring.py — a share is a
    count over one entity's own rows, with no weights and nothing to
    normalize."""
    if item_id not in _MOCK_RECORDS:
        raise UnknownItemError(f"unknown item_id={item_id!r}; known ids: {list(_MOCK_RECORDS)}")

    result = aggregate(
        _MOCK_RECORDS[item_id],
        operation=operation,
        value_field="units",
        group_by_field="category" if category is not None else None,
        group_value=category,
    )
    value = result.value
    # NaN is not JSON-serializable in a way any consumer handles well, and
    # "undefined" is the honest word for mean-of-nothing or share-of-zero.
    is_defined = value == value
    return {
        "item_id": item_id,
        "operation": result.operation,
        "category": result.group_value,
        "value": round(value, 6) if is_defined else None,
        "defined": is_defined,
        # The arithmetic, exposed — so the model explains a number it
        # never computed, same contract as compare_items' components.
        "matching_records": result.matching_records,
        "total_records": result.total_records,
        "matching_units": result.matching_units,
        "total_units": result.total_units,
        # The other reading of "what percentage", so the model can offer
        # it if the user meant share-by-count rather than share-by-volume.
        "share_by_record_count": (
            round(result.matching_records / result.total_records, 6) if result.total_records else None
        ),
    }


# ── The DOMAIN model behind estimate_derived_metric ──────────────────────
# This is example code: "unmet demand" is one assignment's modelled
# quantity, not a generic feature. Replace this whole section with the
# real assignment's derived metric and keep app/analytics.py untouched —
# that module holds only the generic contract (factors summing to the
# value, mandatory assumptions/caveat/confidence).
#
# Weight applied to waitlist entries when converting them into implied
# demand. Below 1.0 because a waitlist entry is WEAKER evidence than a
# turnaway: people join several waitlists and some would not have
# converted. A stated judgement call, not a measurement — exactly the
# number a reviewer should push on, and the honest answer is "it's a
# judgement call, and here's the sensitivity."
WAITLIST_CONVERSION_RATE = 0.5

# Utilization at or above which the entity is treated as
# capacity-constrained, meaning observed demand is suppressed BY the
# constraint and turnaway/waitlist signals become credible evidence of
# latent demand.
CAPACITY_CONSTRAINED_UTILIZATION = 0.85


def estimate_unmet_demand(
    served_units: float,
    capacity_units: float,
    turnaways: float,
    waitlist: float,
) -> DerivedMetricResult:
    """Model demand that exists but was not served — present in no dataset
    by construction, since nobody records the customers they never saw.

    Model: unmet = turnaways + (waitlist * WAITLIST_CONVERSION_RATE),
    reported alongside utilization, which is what makes the number
    *credible* rather than merely arithmetic.

    THE OBJECTION TO HAVE AN ANSWER FOR — "how do you know that's unmet
    demand and not just a capacity ceiling?" They are not rival theories;
    they're the same phenomenon from two sides. A capacity ceiling is the
    CAUSE, unmet demand the EFFECT measured through it. That's exactly
    why utilization gates confidence:

      - Utilization >= CAPACITY_CONSTRAINED_UTILIZATION: turnaways are
        consistent with a binding capacity limit, so the estimate is
        credible and the honest framing is "demand capacity could not
        absorb" — the ceiling is the mechanism, not a competing story.
      - Utilization below it: turnaways happened with capacity to spare,
        so capacity is NOT the constraint and something else is (schedule
        mismatch, pricing, peak staffing). Same arithmetic, same number,
        much weaker claim — confidence drops and the caveat says why.
    """
    utilization = served_units / capacity_units if capacity_units else float("nan")

    # Clamped at zero: a negative turnaway count is bad data, not negative
    # demand, and must not quietly reduce the estimate.
    contributions = [
        FactorInput(
            name="observed_turnaways",
            magnitude=max(0.0, turnaways),
            source_field="turnaways",
            explanation=(
                "Requests explicitly refused or unfulfilled. Counted at full weight — "
                "a turnaway is demand that presented itself and was measured, not inferred."
            ),
        ),
        FactorInput(
            name="waitlist_converted",
            magnitude=max(0.0, waitlist) * WAITLIST_CONVERSION_RATE,
            source_field="waitlist",
            explanation=(
                f"Waitlist entries discounted by WAITLIST_CONVERSION_RATE="
                f"{WAITLIST_CONVERSION_RATE}. Weaker evidence than a turnaway: people join "
                "multiple waitlists and some would not have converted, so counting them at "
                "full weight would overstate."
            ),
        ),
    ]

    # NaN-safe: an unknown utilization must not read as "constrained".
    capacity_constrained = utilization == utilization and utilization >= CAPACITY_CONSTRAINED_UTILIZATION

    if capacity_constrained:
        confidence = "medium"
        caveat = (
            f"Utilization is {utilization:.0%}, at or above the "
            f"{CAPACITY_CONSTRAINED_UTILIZATION:.0%} threshold where capacity plausibly binds, "
            "so turnaways are consistent with demand that capacity could not absorb. The "
            "capacity ceiling is the mechanism producing this number, not a competing "
            "explanation for it. Not a measurement of true latent demand: anyone who never "
            "attempted a request because the constraint is well known is invisible here, so "
            "this is a LOWER BOUND."
        )
    else:
        confidence = "low"
        caveat = (
            f"Utilization is only {utilization:.0%}, BELOW the "
            f"{CAPACITY_CONSTRAINED_UTILIZATION:.0%} capacity-constrained threshold. Turnaways "
            "occurred with capacity to spare, so capacity is not the binding constraint and "
            "this figure should not be read as 'demand we could serve by expanding.' A "
            "schedule/peak mismatch, pricing, or staffing is the more likely cause. Same "
            "arithmetic, much weaker claim."
        )

    return build_derived_metric(
        metric="unmet_demand",
        unit="units",
        contributions=contributions,
        assumptions=(
            f"Waitlist entries converted at {WAITLIST_CONVERSION_RATE:.0%}; a judgement call, "
            "not a measured conversion rate, and the estimate moves roughly linearly with it.",
            "Turnaways and waitlist entries are assumed to be distinct populations. If the "
            "source system waitlists everyone it turns away, this double-counts.",
            "Demand suppressed before it was ever expressed is not captured, so the figure is "
            "a lower bound on true unmet demand.",
        ),
        confidence=confidence,
        caveat=caveat,
    )


def estimate_derived_metric(item_id: str) -> dict[str, Any]:
    """A modelled quantity plus the factors that produced it. The number
    never travels without its assumptions, confidence, and caveat."""
    if item_id not in _MOCK_DEMAND_INPUTS:
        raise UnknownItemError(f"unknown item_id={item_id!r}; known ids: {list(_MOCK_DEMAND_INPUTS)}")

    inputs = _MOCK_DEMAND_INPUTS[item_id]
    result = estimate_unmet_demand(
        served_units=inputs["served_units"],
        capacity_units=inputs["capacity_units"],
        turnaways=inputs["turnaways"],
        waitlist=inputs["waitlist"],
    )
    return {
        "item_id": item_id,
        "metric": result.metric,
        "value": round(result.value, 4),
        "unit": result.unit,
        "confidence": result.confidence,
        "caveat": result.caveat,
        "assumptions": list(result.assumptions),
        "observed_inputs": dict(inputs),
        "factors": [
            {
                "name": f.name,
                "magnitude": round(f.magnitude, 4),
                "share_of_total": round(f.share_of_total, 4),
                "source_field": f.source_field,
                "explanation": f.explanation,
            }
            for f in result.factors
        ],
    }


def rank_by_priorities(
    item_ids: list[str], emphasize: list[str] | None = None, deemphasize: list[str] | None = None
) -> dict[str, Any]:
    """Rank items with the weights adjusted to the user's stated
    priorities ("I care about being fast and cheap").

    Returns BOTH the default ranking and the adjusted one, deliberately.
    Handing back only the adjusted list would let a reweighting change
    the answer invisibly — the user asked for their priorities to be
    honored, not for the default result to be quietly replaced. Showing
    both makes the effect of their own stated preference legible, and
    makes it obvious when the preference changed nothing.
    """
    emphasize = emphasize or []
    deemphasize = deemphasize or []
    items = {item_id: fetch_item_metrics(item_id) for item_id in item_ids}

    adjusted_criteria = apply_priority_emphasis(
        DEFAULT_CRITERIA, emphasize=emphasize, deemphasize=deemphasize
    )
    default_result = rank_items(items, DEFAULT_CRITERIA)
    adjusted_result = rank_items(items, adjusted_criteria)

    def as_rows(result: Any) -> list[dict[str, Any]]:
        return [
            {
                "rank": r.rank,
                "item_id": r.item_id,
                "total_score": round(r.total_score, 4),
                "components": [
                    {
                        "criterion": c.criterion,
                        "raw_value": c.raw_value,
                        "normalized_score": round(c.normalized_score, 4),
                        "weight": round(c.weight, 4),
                        "contribution": round(c.contribution, 4),
                    }
                    for c in r.components
                ],
            }
            for r in result.ranked
        ]

    default_top = default_result.ranked[0].item_id if default_result.ranked else None
    adjusted_top = adjusted_result.ranked[0].item_id if adjusted_result.ranked else None

    return {
        "emphasized": emphasize,
        "deemphasized": deemphasize,
        "emphasis_factor": PRIORITY_EMPHASIS_FACTOR,
        "default_weights": {c.name: c.weight for c in DEFAULT_CRITERIA},
        "adjusted_weights": {c.name: c.weight for c in adjusted_criteria},
        "default_ranking": as_rows(default_result),
        "adjusted_ranking": as_rows(adjusted_result),
        "priorities_changed_the_winner": default_top != adjusted_top,
        "assumption_to_state": (
            f"Ranked with {', '.join(emphasize) or 'no criteria'} weighted "
            f"{PRIORITY_EMPHASIS_FACTOR}x higher"
            + (f" and {', '.join(deemphasize)} weighted lower" if deemphasize else "")
            + ", based on the priorities you described. Tell the user this — the "
            "weighting reflects an interpretation of their words, not a fact about the data."
        ),
    }


def analyze_weight_sensitivity(item_ids: list[str], criterion: str, factor: float) -> dict[str, Any]:
    """Re-rank with one criterion's weight scaled by `factor`, and report
    what actually moved. Answers "what happens if this weight is wrong?"
    with evidence instead of reassurance."""
    items = {item_id: fetch_item_metrics(item_id) for item_id in item_ids}
    scaled = scale_criterion_weight(DEFAULT_CRITERIA, criterion, factor)
    overrides = {c.name: c.weight for c in scaled if c.name == criterion}
    result = sensitivity_analysis(items, DEFAULT_CRITERIA, overrides)

    return {
        "criterion": criterion,
        "factor": factor,
        "baseline_weights": dict(result.baseline_weights),
        "perturbed_weights": dict(result.perturbed_weights),
        "top_item": {
            "before": result.baseline_top,
            "after": result.perturbed_top,
            "changed": result.top_changed,
        },
        # Kendall tau: +1 means the order is untouched, lower means churn.
        # One number for "did this weight actually matter", which is more
        # honest than eyeballing two lists that look similar.
        "kendall_tau": round(result.kendall_tau, 4),
        "items_moved": result.items_moved,
        "max_rank_movement": result.max_rank_movement,
        # A weight change alters covered_weight too, so items can enter or
        # leave the ranking entirely — not just move within it.
        "items_entered_ranking": list(result.items_entered),
        "items_left_ranking": list(result.items_left),
        "changes": [
            {
                "item_id": c.item_id,
                "rank_before": c.baseline_rank,
                "rank_after": c.perturbed_rank,
                "rank_delta": c.rank_delta,
                "score_before": round(c.baseline_score, 4) if c.baseline_score is not None else None,
                "score_after": round(c.perturbed_score, 4) if c.perturbed_score is not None else None,
            }
            for c in result.changes
        ],
    }


def weight_robustness_report(item_ids: list[str]) -> dict[str, Any]:
    """For every criterion, the smallest weight multiplier that changes
    the winner. A criterion with a flip point close to 1.0 is one the
    result HANGS ON; one that never flips within the search range is not
    load-bearing and its exact weight barely matters.

    This is the tool for "how confident are you in this ranking?" — and
    it can legitimately return "not very", which is the point.
    """
    items = {item_id: fetch_item_metrics(item_id) for item_id in item_ids}
    baseline = rank_items(items, DEFAULT_CRITERIA)

    findings = []
    for criterion in DEFAULT_CRITERIA:
        flip = find_weight_flip_point(items, DEFAULT_CRITERIA, criterion.name)
        findings.append(
            {
                "criterion": criterion.name,
                "current_weight": criterion.weight,
                "flip_factor": flip,
                "interpretation": (
                    f"No weight multiplier up to 10x changes the winner — this criterion's "
                    f"exact weight is not load-bearing."
                    if flip is None
                    else f"Scaling this weight by {flip}x changes the top-ranked item. "
                    + (
                        "That is a small change, so the ranking is SENSITIVE to this weight "
                        "and the top result should be presented as close, not decisive."
                        if abs(flip - 1.0) <= 0.5
                        else "That is a large change, so the ranking is robust to this weight."
                    )
                ),
            }
        )

    tightest = min(
        (f for f in findings if f["flip_factor"] is not None),
        key=lambda f: abs(float(f["flip_factor"]) - 1.0),  # type: ignore[arg-type]
        default=None,
    )

    return {
        "baseline_top": baseline.ranked[0].item_id if baseline.ranked else None,
        "baseline_ranking": [
            {"rank": r.rank, "item_id": r.item_id, "total_score": round(r.total_score, 4)}
            for r in baseline.ranked
        ],
        "criteria": findings,
        "most_sensitive_criterion": tightest["criterion"] if tightest else None,
        "summary": (
            "No single weight change up to 10x alters the winner; the ranking is robust."
            if tightest is None
            else f"The result is most sensitive to {tightest['criterion']!r}, which flips the "
            f"winner at {tightest['flip_factor']}x its current weight."
        ),
    }


# Dispatch table used by agent_loop.py: tool name -> callable(args_dict).
# Kept as a plain dict, not a decorator/registry framework — this is the
# entire "tool registry" a hand-rolled loop needs.
TOOL_REGISTRY: dict[str, Callable[[dict[str, Any]], Any]] = {
    "compare_items": lambda args: compare_items(item_ids=args["item_ids"]),
    "get_item_metrics": lambda args: get_item_metrics(item_id=args["item_id"]),
    "resolve_entity": lambda args: resolve_entity(query=args["query"]),
    "find_items": lambda args: find_items(filters=args["filters"]),
    "aggregate_records": lambda args: aggregate_records(
        item_id=args["item_id"], operation=args["operation"], category=args.get("category")
    ),
    "estimate_derived_metric": lambda args: estimate_derived_metric(item_id=args["item_id"]),
    "analyze_weight_sensitivity": lambda args: analyze_weight_sensitivity(
        item_ids=args["item_ids"], criterion=args["criterion"], factor=args["factor"]
    ),
    "weight_robustness_report": lambda args: weight_robustness_report(item_ids=args["item_ids"]),
    "rank_by_priorities": lambda args: rank_by_priorities(
        item_ids=args["item_ids"],
        emphasize=args.get("emphasize"),
        deemphasize=args.get("deemphasize"),
    ),
}
