"""
judge_calibration_data.py — the hand-labeled set evals/judge_validation.py
checks the LLM judge against.

10 examples, each a (tool_context, final_text) pair graded against
RUBRIC_EXPLANATION_CITES_REASONING (evals/graders/llm_judge.py) — the
central "does the explanation cite the right reasoning" rubric named in
the brief. `tool_context` in every example is the REAL, literal output
of `app.tools.compare_items(['option_a', 'option_c'])` (verified by
running it directly — see the docstring below) so every example is
grounded in an actual tool result, not an invented one; only
`final_text` varies, deliberately spanning the full 1-10 range so the
judge is tested on hard cases, not just obvious ones.

Ground truth (from `python -c "from app.tools import compare_items;
print(compare_items(['option_a','option_c']))"`, verified 2026-08-07):
  option_a total_score=0.725   (cost 120→0.5, quality 8.5→0.85, lead_time 3→0.7)
  option_c total_score=0.7162  (cost 150→0.125, quality 9.2→0.92, lead_time 1→0.9)
  option_a wins.

Each example is hand-labeled by a human (Roi, acting as the "intern" in
the research brief's intern test: "hand your rubric plus traces to
someone unfamiliar with the project — if their pass/fail matches yours
≥80% of the time, the rubric is specific enough to automate"). The
human's own reasoning is recorded in `human_rationale` so a reviewer can
audit the labels themselves, not just trust them.

`human_pass` uses the SAME threshold (score >= 7) as LLMJudgeGrader's
default `pass_threshold` — see evals/graders/llm_judge.py — so the
binary-agreement number in judge_validation.py is comparing apples to
apples.
"""
from __future__ import annotations

from dataclasses import dataclass

# The real, literal tool output for option_a vs option_c — see module docstring.
TOOL_CONTEXT_A_VS_C = {
    "criteria": [
        {"name": "cost", "weight": 1.0, "higher_is_better": False},
        {"name": "quality", "weight": 2.0, "higher_is_better": True},
        {"name": "lead_time_days", "weight": 1.0, "higher_is_better": False},
    ],
    "ranking": [
        {
            "rank": 1,
            "item_id": "option_a",
            "total_score": 0.725,
            "components": [
                {"criterion": "cost", "raw_value": 120.0, "normalized_score": 0.5, "weight": 0.25, "contribution": 0.125},
                {"criterion": "quality", "raw_value": 8.5, "normalized_score": 0.85, "weight": 0.5, "contribution": 0.425},
                {"criterion": "lead_time_days", "raw_value": 3, "normalized_score": 0.7, "weight": 0.25, "contribution": 0.175},
            ],
        },
        {
            "rank": 2,
            "item_id": "option_c",
            "total_score": 0.7162,
            "components": [
                {"criterion": "cost", "raw_value": 150.0, "normalized_score": 0.125, "weight": 0.25, "contribution": 0.0312},
                {"criterion": "quality", "raw_value": 9.2, "normalized_score": 0.92, "weight": 0.5, "contribution": 0.46},
                {"criterion": "lead_time_days", "raw_value": 1, "normalized_score": 0.9, "weight": 0.25, "contribution": 0.225},
            ],
        },
    ],
}


@dataclass(frozen=True)
class CalibrationExample:
    id: str
    final_text: str
    human_score: int  # 1-10, hand-assigned against the same rubric anchors the judge uses
    human_rationale: str
    tool_context: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.tool_context is None:
            object.__setattr__(self, "tool_context", TOOL_CONTEXT_A_VS_C)

    @property
    def human_pass(self) -> bool:
        return self.human_score >= 7


CALIBRATION_SET: list[CalibrationExample] = [
    CalibrationExample(
        id="perfect_citation",
        final_text=(
            "option_a ranks first with a total score of 0.725. That's driven mainly by quality (8.5, normalized "
            "0.85, contributing 0.425 of the total) and a decent lead time (3 days, contributing 0.175); cost "
            "(120) contributes 0.125. option_c is close behind at 0.7162 — its quality is higher (9.2) and its "
            "lead time is shorter (1 day), but its cost (150) drags it down enough that option_a still wins."
        ),
        human_score=10,
        human_rationale="Correct winner, correct numbers for every criterion on both items, explains WHY option_a "
        "wins despite option_c's higher quality — exactly what the rubric's 10-anchor asks for.",
    ),
    CalibrationExample(
        id="fabricated_total_score",
        final_text="option_a wins with a total score of 0.91, comfortably ahead of option_c at 0.68.",
        human_score=1,
        human_rationale="Both numbers are fabricated — the real scores are 0.725 and 0.7162. Directly contradicts "
        "the tool context, which is anchor-1 territory verbatim.",
    ),
    CalibrationExample(
        id="vague_no_specifics",
        final_text="option_a is just the better choice overall, it edges out option_c pretty comfortably.",
        human_score=4,
        human_rationale="Correct winner, but zero specific criteria or values cited — textbook anchor-4 case.",
    ),
    CalibrationExample(
        id="two_criteria_cited_slightly_unclear",
        final_text=(
            "option_a comes out on top mainly because of cost (120 vs 150 for option_c) and it also does fine on "
            "quality (8.5). option_c is a bit better on the other stuff but not enough to catch up."
        ),
        human_score=7,
        human_rationale="Cites two real numbers correctly (cost 120/150, quality 8.5), but the reasoning is a "
        "little muddled (cost alone doesn't explain the win — quality's 2x weight and lead time both matter more) "
        "and lead_time is hand-waved as 'the other stuff.' Solid anchor-7: right but a bit unclear.",
    ),
    CalibrationExample(
        id="wrong_winner_stated",
        final_text="option_c wins this comparison with the higher total score, thanks to its strong quality rating of 9.2.",
        human_score=1,
        human_rationale="States the wrong winner outright (option_a actually won, 0.725 > 0.7162) — a real, "
        "consequential error a customer would act on incorrectly. Anchor-1: contradicts the data.",
    ),
    CalibrationExample(
        id="jargon_heavy_but_numerically_accurate",
        final_text=(
            "item_id=option_a total_score=0.725 [cost: raw=120.0 normalized_score=0.5 weight=0.25 "
            "contribution=0.125; quality: raw=8.5 normalized_score=0.85 weight=0.5 contribution=0.425; "
            "lead_time_days: raw=3 normalized_score=0.7 weight=0.25 contribution=0.175]. "
            "item_id=option_c total_score=0.7162 [cost: raw=150.0 normalized_score=0.125 weight=0.25 "
            "contribution=0.0312; quality: raw=9.2 normalized_score=0.92 weight=0.5 contribution=0.46; "
            "lead_time_days: raw=1 normalized_score=0.9 weight=0.25 contribution=0.225]."
        ),
        human_score=8,
        human_rationale="Every single number is correct and complete — this rubric grades ACCURACY of citation, "
        "not plain-language tone (that's a separate rubric, RUBRIC_TONE_FOR_NON_TECHNICAL_READER). Docked from 10 "
        "only because it never actually explains WHY option_a wins in words, just dumps the raw structure.",
    ),
    CalibrationExample(
        id="one_wrong_number_among_real_ones",
        final_text=(
            "option_a wins overall. Its cost is 120 and quality is 8.5, both better-weighted than option_c's. "
            "Its lead time contributes about 0.6 to the total, which is the deciding factor."
        ),
        human_score=4,
        human_rationale="Cost and quality raw values are correct, but the lead_time contribution (real value "
        "0.175) is misstated as 0.6, and 'better-weighted than option_c's' is vague/incorrect (option_c's cost "
        "and quality raw values are both worse for cost, better for quality — this glosses over that). A real "
        "citation attempt corrupted by a wrong number and an imprecise claim: anchor-4, not anchor-7.",
    ),
    CalibrationExample(
        id="off_topic_non_answer",
        final_text="I'm not sure what you're looking for — could you clarify what you'd like me to compare?",
        human_score=1,
        human_rationale="A real tool result was available and the question was unambiguous (compare option_a and "
        "option_c) — this is a non-answer that ignores the data entirely. Anchor-1: unrelated to the data.",
    ),
    CalibrationExample(
        id="clear_accurate_plain_narrative",
        final_text=(
            "option_a is the better pick here, mostly on quality — it scores 8.5 out of 10, which the scoring "
            "tool weights twice as heavily as cost or delivery time. option_c actually costs more (150 vs "
            "option_a's 120) and takes longer to arrive (1 day faster ships to option_c, so option_c is actually "
            "faster — correction, option_c ships in 1 day vs option_a's 3), but that's not enough to overcome "
            "option_a's cost and consistency advantage. Final scores: option_a 0.725, option_c 0.7162 — close, "
            "but option_a edges it out."
        ),
        human_score=9,
        human_rationale="Correct winner, correct final numbers, cites specific criteria values accurately "
        "(quality 8.5, cost 120 vs 150, lead time 3 vs 1 day — even self-corrects a slip mid-sentence rather than "
        "leaving a wrong claim standing), and it's readable narrative prose. Not a perfect 10 only because the "
        "self-correction reads a little clumsy and it slightly undersells why quality's weight matters.",
    ),
    CalibrationExample(
        id="criteria_names_right_values_swapped",
        final_text=(
            "option_a wins. Its quality score is 9.2, the highest of the two, and its lead time is 1 day, the "
            "fastest available. option_c trails on both fronts."
        ),
        human_score=2,
        human_rationale="Uses the right criterion NAMES (quality, lead_time) but attributes option_c's actual "
        "values (quality 9.2, lead_time 1) to option_a, and reverses the real comparison (option_a's real quality "
        "is 8.5 and lead time is 3 days — option_c is faster and higher-quality, just more expensive). This is "
        "the subtle-fabrication case: looks well-cited at a glance, is wrong on inspection. Anchor-1/2 territory.",
    ),
]
