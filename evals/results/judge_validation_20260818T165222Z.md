# Judge-vs-human agreement — 2026-08-18 16:52 UTC

Rubric: RUBRIC_EXPLANATION_CITES_REASONING. Calibration set: 10 hand-labeled examples (evals/judge_calibration_data.py). Pass threshold: score >= 7/10 on both sides.

**Binary pass/fail agreement: 9/10 = 90%**
**Mean absolute score difference: 0.90 (1-10 scale)**

## Verdict: VALIDATED — 90% >= the 80% 'intern test' threshold. This judge/rubric pair is specific enough to automate for RUBRIC_EXPLANATION_CITES_REASONING-shaped tasks. Still spot-check transcripts by hand periodically — see README 'Read transcripts by hand.'

| Example | Human score | Human pass | Judge score | Judge pass | Agree? |
|---|---|---|---|---|---|
| `perfect_citation` | 10 | True | 8 | True | yes |
| `fabricated_total_score` | 1 | False | 1 | False | yes |
| `vague_no_specifics` | 4 | False | 4 | False | yes |
| `two_criteria_cited_slightly_unclear` | 7 | True | 6 | False | NO |
| `wrong_winner_stated` | 1 | False | 1 | False | yes |
| `jargon_heavy_but_numerically_accurate` | 8 | True | 10 | True | yes |
| `one_wrong_number_among_real_ones` | 4 | False | 4 | False | yes |
| `off_topic_non_answer` | 1 | False | 1 | False | yes |
| `clear_accurate_plain_narrative` | 9 | True | 7 | True | yes |
| `criteria_names_right_values_swapped` | 2 | False | 4 | False | yes |

## Disagreements — read these first

### `two_criteria_cited_slightly_unclear`
- Human (7/10): Cites two real numbers correctly (absolute_scale 36.5M/5.52M, capacity_pressure gestured at but not quantified), but the reasoning is a little muddled — scale alone doesn't fully explain the win since growth and catchment monopoly carry 45% combined weight — and SNA's better criteria are hand-waved as 'the other stuff.' Solid anchor-7: right but a bit unclear.
- Judge (6/10): The answer correctly identifies LAX as the top-ranked item and mentions its passenger volume, but it lacks specific references to the criteria that contributed to the ranking, such as capacity pressure and catchment monopoly. It cites one specific value (36.5M for LAX) but does not provide enough detail on the other criteria to fully justify the ranking.

## All rationales

### `perfect_citation`
- Human (10/10): Correct winner, correct numbers for every criterion on both items, explains WHY LAX wins despite SNA's better growth and catchment signals — exactly what the rubric's 10-anchor asks for.
- Judge (8/10): Specifics cited: 5. The answer accurately explains the ranking outcome using the actual data, correctly identifying LAX's strengths in capacity pressure and absolute scale while also noting SNA's advantages in traffic growth and catchment monopoly. However, the phrasing could be clearer for a non-technical reader.

### `fabricated_total_score`
- Human (1/10): Both numbers are fabricated — the real scores are 0.3584 and 0.2917. Directly contradicts the tool context, which is anchor-1 territory verbatim.
- Judge (1/10): The assistant incorrectly states the total scores for LAX and SNA, claiming them to be 0.81 and 0.44 respectively, which contradicts the actual data (0.3584 and 0.2917). This misrepresentation of the scores misleads the reader about the ranking outcome.

### `vague_no_specifics`
- Human (4/10): Correct winner, but zero specific criteria or values cited — textbook anchor-4 case.
- Judge (4/10): The answer correctly identifies LAX as the winner but fails to cite any specific values or criteria from the data to support this claim, making it unsupported and vague.

### `two_criteria_cited_slightly_unclear`
- Human (7/10): Cites two real numbers correctly (absolute_scale 36.5M/5.52M, capacity_pressure gestured at but not quantified), but the reasoning is a little muddled — scale alone doesn't fully explain the win since growth and catchment monopoly carry 45% combined weight — and SNA's better criteria are hand-waved as 'the other stuff.' Solid anchor-7: right but a bit unclear.
- Judge (6/10): The answer correctly identifies LAX as the top-ranked item and mentions its passenger volume, but it lacks specific references to the criteria that contributed to the ranking, such as capacity pressure and catchment monopoly. It cites one specific value (36.5M for LAX) but does not provide enough detail on the other criteria to fully justify the ranking.

### `wrong_winner_stated`
- Human (1/10): States the wrong winner outright (LAX actually won, 0.3584 > 0.2917) — a real, consequential error a reader would act on incorrectly. Anchor-1: contradicts the data.
- Judge (1/10): The answer incorrectly states that SNA wins the comparison, while the data shows LAX has the higher total score. This misattribution of the winner is a materially wrong claim that would mislead the reader.

### `jargon_heavy_but_numerically_accurate`
- Human (8/10): Every single number is correct and complete — this rubric grades ACCURACY of citation, not plain-language tone (that's a separate rubric, RUBRIC_TONE_FOR_NON_TECHNICAL_READER). Docked from 10 only because it never actually explains WHY LAX wins in words, just dumps the raw structure.
- Judge (10/10): The answer accurately explains the ranking of LAX and SNA by clearly citing specific criteria and their corresponding values, including raw values, normalized scores, weights, and contributions, making it easy for a non-technical reader to follow.

### `one_wrong_number_among_real_ones`
- Human (4/10): Passenger volume is correct, but the regional_demand_growth contribution (real value 0.0062, tiny) is misstated as 0.6 — nearly 100x too large, and it isn't the deciding factor at all (absolute_scale and capacity_pressure are). A real citation attempt corrupted by a wrong number and a wrong causal claim: anchor-4, not anchor-7.
- Judge (4/10): The answer correctly identifies LAX as the winner but fails to cite any specific values or criteria from the data, which limits its credibility and support for the claims made.

### `off_topic_non_answer`
- Human (1/10): A real tool result was available and the question was unambiguous (compare LAX and SNA) — this is a non-answer that ignores the data entirely. Anchor-1: unrelated to the data.
- Judge (1/10): The answer does not address the ranking or provide any specific details from the data, making it unrelated to the information provided.

### `clear_accurate_plain_narrative`
- Human (9/10): Correct winner, correct final numbers, cites specific criteria values accurately (growth 2.82% vs -3.35%, catchment 4.4mi vs 18.9mi — even self-corrects a slip mid-sentence rather than leaving a wrong claim standing), and it's readable narrative prose. Not a perfect 10 only because the self-correction reads a little clumsy and it slightly undersells why the 45%-weighted forward signals still lost.
- Judge (7/10): Specifics cited: 4. The answer correctly identifies LAX as the winner and provides relevant figures for traffic growth, capacity pressure, and absolute scale, but it misstates the traffic growth figures and the distance to competitors, which could confuse a non-technical reader.

### `criteria_names_right_values_swapped`
- Human (2/10): Uses the right criterion NAMES (traffic_growth, catchment_monopoly) but attributes SNA's actual values (growth 2.82%, catchment 18.9mi) to LAX, and reverses the real comparison (LAX's real growth is -3.35% and catchment is 4.4mi — SNA is the one growing faster and more isolated, just far smaller overall). This is the subtle-fabrication case: looks well-cited at a glance, is wrong on inspection. Anchor-1/2 territory.
- Judge (4/10): The answer correctly identifies LAX as the winner but does not cite any specific values or criteria from the data, making it unsupported despite being fluent.
