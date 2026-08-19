# The brief's four example questions, answered end-to-end

Generated 2026-08-19T10:44:54 against `openai` / `gpt-4o-mini`.
Every number below came from a tool call; the model computed none of them.

Regenerate with:

```bash
LLM_PROVIDER=openai python scripts/run_example_questions.py
```

## Q1. Which airports in New England are strong candidates for terminal expansion?

*3 turns, 13.4s*

**Tool calls**

- `find_items({"filters": {"region": "Northeast", "new_england": "yes"}})`
- `compare_items({"item_ids": ["BDL", "BOS", "BTV", "MHT", "PVD", "PWM"], "focus_criterion": ""})`

**Answer**

The following airports in New England are strong candidates for terminal expansion based on their investment potential:

1. **Boston Logan International Airport (BOS)**
   - **Total Score:** 0.4386
   - **Key Contributions:**
     - **Traffic Growth:** Slight decline, but still a significant contributor.
     - **Regional Demand Growth:** Positive growth, contributing to future demand.
     - **Catchment Monopoly:** Strong position with a high score indicating limited competition.
     - **Capacity Pressure:** High capacity pressure, suggesting a need for expansion.
     - **Absolute Scale:** Large airport size, enhancing its importance.

2. **Portland International Jetport (PWM)**
   - **Total Score:** 0.3465
   - **Key Contributions:**
     - **Traffic Growth:** Strong growth, indicating increasing passenger numbers.
     - **Regional Demand Growth:** Positive growth, supporting future expansion.
     - **Catchment Monopoly:** Good position with limited competition.
     - **Capacity Pressure:** Lower capacity pressure compared to BOS, but still relevant.
     - **Absolute Scale:** Smaller than BOS, but still significant.

3. **Manchester-Boston Regional Airport (MHT)**
   - **Total Score:** 0.3084
   - **Key Contributions:**
     - **Traffic Growth:** Strong growth, indicating potential for increased capacity.
     - **Regional Demand Growth:** Positive, but lower than BOS and PWM.
     - **Catchment Monopoly:** Moderate competition.
     - **Capacity Pressure:** Low capacity pressure, suggesting less immediate need for expansion.
     - **Absolute Scale:** Smaller airport size.

4. **Bradley International Airport (BDL)**
   - **Total Score:** 0.3002
   - **Key Contributions:**
     - **Traffic Growth:** Slight decline, but still a contributor.
     - **Regional Demand Growth:** Positive growth.
     - **Catchment Monopoly:** Good position with limited competition.
     - **Capacity Pressure:** Moderate pressure.
     - **Absolute Scale:** Medium-sized airport.

5. **T.F. Green Airport (PVD)**
   - **Total Score:** 0.2859
   - **Key Contributions:**
     - **Traffic Growth:** Strong growth.
     - **Regional Demand Growth:** Positive, but lower than others.
     - **Catchment Monopoly:** Moderate competition.
     - **Capacity Pressure:** Moderate pressure.
     - **Absolute Scale:** Medium-sized airport.

6. **Burlington International Airport (BTV)**
   - **Total Score:** 0.2015
   - **Key Contributions:**
     - **Traffic Growth:** Strong growth.
     - **Regional Demand Growth:** Slight decline.
     - **Catchment Monopoly:** Moderate competition.
     - **Capacity Pressure:** Low pressure.
     - **Absolute Scale:** Smaller airport.

These rankings reflect a combination of factors including traffic growth, regional demand growth, competition, capacity pressure, and the current size of the airports. All airports listed have sufficient data to support their ranking.

---

## Q2. Compare LA and Santa Ana airport congestion levels.

*3 turns, 6.5s*

**Tool calls**

- `resolve_entity({"query": "LA"})`
- `resolve_entity({"query": "Santa Ana"})`
- `compare_items({"item_ids": ["LAX", "SNA"], "focus_criterion": "capacity_pressure"})`

**Answer**

I interpreted "LA" as referring to Los Angeles International Airport (LAX), which is the primary airport in the LA metro area. I will compare LAX with Santa Ana Airport (SNA) regarding congestion levels, specifically focusing on capacity pressure.

### Capacity Pressure Comparison:
- **LAX**:
  - **Raw Value**: 9,124,325.75 passengers per air-carrier runway
  - **Normalized Score**: 1.0
  - **Rank**: 1

- **SNA**:
  - **Raw Value**: 5,521,729.0 passengers per air-carrier runway
  - **Normalized Score**: 0.698
  - **Rank**: 2

### Summary:
LAX has a higher capacity pressure score compared to SNA, indicating that it experiences more congestion relative to its runway capacity. This means that LAX is more congested than SNA, which could suggest a greater need for expansion or renovation to alleviate congestion issues.

If you have any further questions or need additional comparisons, feel free to ask!

*This run resolves "LA" the same way as before, but now visibly uses the `focus_criterion` mechanism — the tool call carries `"focus_criterion":"capacity_pressure"` and the reply reports the single-criterion ordering, explicitly distinct from the blended investment score.*

---

## Q3. What is the percentage of long haul flights out of Anchorage?

*3 turns, 4.4s*

**Tool calls**

- `aggregate_records({"item_id": "ANC", "operation": "share", "category": "long_haul"})`
- `aggregate_records({"item_id": "ANC", "operation": "share", "category": "international"})`

**Answer**

The percentage of long-haul flights out of Anchorage (ANC) is represented by the share of international flights, which is approximately **15.99%**.

It's important to note that this figure serves as a proxy for long-haul flights. The average distance for outbound international flights from Anchorage is about 4,322 miles, while domestic flights average around 1,458 miles. This means that the international share may understate the actual number of long flights, as many domestic routes are also relatively long, such as Anchorage to Seattle, which is approximately 1,448 miles.

---

## Q4. What is the unmet flight demand in SFO and why?

*2 turns, 5.1s*

**Tool calls**

- `estimate_derived_metric({"item_id": "SFO"})`

**Answer**

The unmet flight demand at San Francisco International Airport (SFO) is estimated to be approximately **1,278,222 annual enplanements**. This figure represents the demand that cannot be accommodated due to specific constraints at the airport.

### Reasons for Unmet Demand:

1. **Weather-Suppressed Throughput**:
   - The primary factor contributing to unmet demand is the **weather-suppressed throughput**. SFO experiences a significant reduction in arrival capacity during low visibility conditions, which occurs approximately **12% of the year**. During these periods, the airport's parallel runways cannot operate independently due to their proximity, leading to a **50% drop in arrival capacity**. This means that any demand exceeding the reduced capacity during these times cannot be fulfilled.

2. **Structural Capacity Deficit**:
   - The model did not identify any structural capacity deficit at SFO, indicating that the airport's facilities are generally adequate for its projected demand under normal conditions. However, this does not account for the demand that is not scheduled due to known constraints, which is not reflected in the unmet demand figure.

### Additional Notes:
- The estimate is considered a **lower bound** because it does not include demand that was never scheduled due to the known constraints, nor does it account for passengers who may choose to drive to competing airports instead.
- The confidence level of this estimate is **medium**, and it is based on various assumptions about traffic growth and weather conditions.

In summary, the unmet demand at SFO is primarily driven by weather-related capacity limitations, particularly during periods of low visibility, rather than a lack of structural capacity in the airport's facilities.

---
