# The brief's four example questions, answered end-to-end

Generated 2026-08-18T19:05:45 against `openai` / `gpt-4o-mini`.
Every number below came from a tool call; the model computed none of them.

Regenerate with:

```bash
LLM_PROVIDER=openai python scripts/run_example_questions.py
```

## Q1. Which airports in New England are strong candidates for terminal expansion?

*3 turns, 11.0s*

**Tool calls**

- `find_items({"filters": {"new_england": "yes"}})`
- `compare_items({"item_ids": ["BDL", "BOS", "PWM", "PVD", "MHT"]})`

**Answer**

The following airports in New England are strong candidates for terminal expansion based on their investment scores:

1. **Boston Logan International Airport (BOS)**
   - **Total Score:** 0.4386
   - **Key Contributions:**
     - **Traffic Growth:** Slight decline (-0.0033), but still contributes positively.
     - **Regional Demand Growth:** Moderate growth (0.00588).
     - **Catchment Monopoly:** Strong position (44.8).
     - **Capacity Pressure:** High (4,204,230.6).
     - **Absolute Scale:** Very large (21,021,153.0).

2. **Portland International Jetport (PWM)**
   - **Total Score:** 0.3465
   - **Key Contributions:**
     - **Traffic Growth:** Strong growth (0.0533).
     - **Regional Demand Growth:** Moderate growth (0.00821).
     - **Catchment Monopoly:** Good position (47.0).
     - **Capacity Pressure:** Lower compared to BOS (643,520.5).
     - **Absolute Scale:** Smaller (1,287,041.0).

3. **Manchester-Boston Regional Airport (MHT)**
   - **Total Score:** 0.3084
   - **Key Contributions:**
     - **Traffic Growth:** Strong growth (0.0826).
     - **Regional Demand Growth:** Moderate growth (0.005).
     - **Catchment Monopoly:** Moderate position (32.5).
     - **Capacity Pressure:** Low (342,797.0).
     - **Absolute Scale:** Smaller (685,594.0).

4. **Bradley International Airport (BDL)**
   - **Total Score:** 0.3002
   - **Key Contributions:**
     - **Traffic Growth:** Slight decline (-0.0005).
     - **Regional Demand Growth:** Moderate growth (0.00647).
     - **Catchment Monopoly:** Good position (47.4).
     - **Capacity Pressure:** Moderate (1,641,698.5).
     - **Absolute Scale:** Moderate (3,283,397.0).

5. **T.F. Green Airport (PVD)**
   - **Total Score:** 0.2859
   - **Key Contributions:**
     - **Traffic Growth:** Strong growth (0.0667).
     - **Regional Demand Growth:** Moderate growth (0.00409).
     - **Catchment Monopoly:** Lower position (24.4).
     - **Capacity Pressure:** Moderate (1,058,700.5).
     - **Absolute Scale:** Moderate (2,117,401.0).

### Summary
BOS stands out as the top candidate due to its significant capacity pressure and absolute scale, despite a slight decline in traffic growth. PWM and MHT also show strong potential for expansion, particularly due to their traffic growth rates. BDL and PVD, while lower in the ranking, still present opportunities for investment based on their regional demand growth and catchment monopolies. 

No airports were excluded from this analysis, ensuring a complete view of the eligible candidates.

---

## Q2. Compare LA and Santa Ana airport congestion levels.

*3 turns, 10.9s*

**Tool calls**

- `resolve_entity({"query": "LA"})`
- `resolve_entity({"query": "Santa Ana"})`
- `compare_items({"item_ids": ["LAX", "SNA"]})`

**Answer**

The comparison of congestion levels between Los Angeles International Airport (LAX) and Santa Ana Airport (SNA) reveals the following:

### Ranking and Scores
1. **LAX**
   - **Total Score:** 0.3584
   - **Components:**
     - **Traffic Growth:** 
       - Raw Value: -0.0335
       - Normalized Score: 0.2089
       - Contribution: 0.0522
     - **Regional Demand Growth:** 
       - Raw Value: -0.00184
       - Normalized Score: 0.0248
       - Contribution: 0.0062
     - **Catchment Monopoly:** 
       - Raw Value: 4.4
       - Normalized Score: 0.0
       - Contribution: 0.0
     - **Capacity Pressure:** 
       - Raw Value: 9,124,325.75
       - Normalized Score: 1.0
       - Contribution: 0.15
     - **Absolute Scale:** 
       - Raw Value: 36,497,303.0
       - Normalized Score: 1.0
       - Contribution: 0.15

2. **SNA**
   - **Total Score:** 0.2917
   - **Components:**
     - **Traffic Growth:** 
       - Raw Value: 0.0282
       - Normalized Score: 0.4932
       - Contribution: 0.1233
     - **Regional Demand Growth:** 
       - Raw Value: -0.00071
       - Normalized Score: 0.0673
       - Contribution: 0.0168
     - **Catchment Monopoly:** 
       - Raw Value: 18.9
       - Normalized Score: 0.0912
       - Contribution: 0.0182
     - **Capacity Pressure:** 
       - Raw Value: 5,521,729.0
       - Normalized Score: 0.698
       - Contribution: 0.1047
     - **Absolute Scale:** 
       - Raw Value: 5,521,729.0
       - Normalized Score: 0.191
       - Contribution: 0.0286

### Analysis
- **LAX** has a higher total score (0.3584) compared to **SNA** (0.2917), indicating that LAX experiences more congestion pressure overall.
- **Capacity Pressure** is a significant factor for both airports, with LAX having a much higher raw value, indicating it handles a larger volume of traffic.
- **Traffic Growth** is negative for LAX, suggesting a decline, while SNA shows positive growth, indicating a potential increase in demand.
- **Catchment Monopoly** is notably higher for SNA, which may suggest it serves a more localized market effectively.

In summary, while LAX is currently more congested overall, SNA shows signs of growth and a strong local market presence.

---

## Q3. What is the percentage of long haul flights out of Anchorage?

*3 turns, 3.9s*

**Tool calls**

- `aggregate_records({"item_id": "ANC", "operation": "share", "category": "long haul"})`
- `aggregate_records({"item_id": "ANC", "operation": "share", "category": "international"})`

**Answer**

The percentage of long-haul flights out of Anchorage (ANC) can be approximated by looking at the share of international flights, which serves as a proxy for long-haul travel. Currently, about **15.99%** of flights from Anchorage are international.

It's important to note that this figure is a proxy for long-haul flights, as "long haul" is not a defined category in the dataset. The average distance for outbound international flights from Anchorage is significantly longer (around 4,322 miles) compared to domestic flights (averaging 1,458 miles). Therefore, while the international share gives a sense of long-haul traffic, it may understate the total number of long flights, especially since many domestic routes are also relatively long.

---

## Q4. What is the unmet flight demand in SFO and why?

*2 turns, 7.4s*

**Tool calls**

- `estimate_derived_metric({"item_id": "SFO"})`

**Answer**

The unmet flight demand at San Francisco International Airport (SFO) is estimated to be approximately **1,278,222 annual enplanements**. This figure represents the demand that cannot be accommodated due to specific constraints at the airport.

### Reasons for Unmet Demand:

1. **Weather-Suppressed Throughput**: 
   - The primary factor contributing to unmet demand is the **weather-suppressed throughput**. The airport's parallel runways are too close together, which significantly reduces arrival capacity during low visibility conditions. Specifically, arrival capacity drops by **50%** during these times. This situation occurs about **12% of the year**, leading to a substantial number of flights that cannot be scheduled when visibility is poor.

2. **Structural Capacity Deficit**: 
   - There is no structural capacity deficit identified in the current model. This means that under normal conditions, the airport's infrastructure can handle the projected demand based on its traffic growth and regional population growth. However, the unmet demand figure primarily arises from the weather-related constraints rather than a lack of overall capacity.

### Model Assumptions:
- The estimate is based on a projected demand growth of **4.7%** for the airport and **0.51%** for the county's population.
- The model assumes that the airport can sustain **7,800,000 annual enplanements** under ideal conditions, which is the 95th percentile achieved across eligible airports.
- The estimate is considered a **lower bound** because it does not account for demand that airlines may choose not to schedule due to known constraints, nor does it include passengers who might opt for competing airports.

### Confidence Level:
- The confidence in this estimate is categorized as **medium**, indicating that while the model provides a reasonable approximation, there are variables that could affect the accuracy of the unmet demand figure.

---
