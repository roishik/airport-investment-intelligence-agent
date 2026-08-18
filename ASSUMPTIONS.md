# Assumptions, uncertainty, and scope

The brief explicitly scores this document: "clearly communicate
assumption, uncertainty and scoping." Listing what wasn't built, and why,
is rewarded, not penalized — expect to be pushed on it directly.

## Data assumptions

- **The FAA CY2025 enplanements file is "preliminary," not final.** It
  is FAA's own published figure, cross-checked against the CY2024 final
  file (which agrees with CY2025's own prior-year column to the digit),
  but CY2025 itself could still be revised when FAA finalizes it. If
  wrong: any criterion built on CY2025 enplanements shifts by whatever
  the revision is — small in practice, since FAA's preliminary/final
  deltas are typically well under 1%.
- **"% Change" in the FAA file is single-year (2024→2025), not a
  multi-year trend.** Used as a growth-trajectory signal, it reflects one
  year of noise (a single bad or good year), not a structural trend. If
  wrong: an airport having one unusually good/bad year could be
  over/under-weighted relative to one on a real multi-year trajectory. A
  3-5 year CAGR would be the fix; not pursued here for time.
- **Nearest-competitor distance is computed only within the 27-airport
  target set** (see `data/candidates.json`'s `_meta`), not the full US
  airport universe. Correct by construction for every "core" tier
  airport; an artifact of the set's composition for "context" tier ones.
  If wrong (i.e. if a closer real competitor exists outside the set):
  the catchment-monopoly signal, if used as a criterion, overstates how
  uncontested that airport's market actually is.
- **Runway count from OurAirports is treated as a capacity/feasibility
  proxy, not validated against real usage.** SNA in particular reports 2
  runways, but one (6/24) is a short crosswind strip used mainly by
  general aviation, not scheduled commercial traffic — raw runway count
  would overstate SNA's effective capacity relative to, say, LAX's 4
  full-length runways. Flagged here so it isn't silently treated as
  equivalent capacity if a criterion uses it directly.

## Uncertainty

- **Q3 (long-haul % out of Anchorage) measures route existence, not
  flight frequency.** The source (OpenFlights `routes.dat`) has one row
  per distinct route, so a route flown daily and one flown weekly count
  identically. Short Bush-Alaska hops plausibly fly more often than long
  trunk routes, so the true flight-frequency-weighted long-haul share is
  likely LOWER than what this dataset reports. The agent states the
  answer at multiple long-haul thresholds (see `DESIGN_DOC.md` §"Q3
  threshold") specifically because the threshold choice swings the
  answer far more than a single point estimate would let on.
- **Q3's underlying route data is stale (OpenFlights, last updated
  ~2014).** Confirmed: ANC–SEA, a route that obviously exists today, is
  missing from it entirely. The authoritative source (BTS T-100 Segment)
  is blocked behind a bot-protected download portal — see `DECISIONS.md`
  for the verification and the fallback reasoning. If a real T-100
  extract becomes available, `data/refresh_data.py`'s
  `build_anc_routes()` names exactly what to swap in.
- **The deterministic score is exact given its inputs, but the criteria
  and weights are a judgment call**, not a measured constant (see
  `DESIGN_DOC.md` §2). The ranking is "the answer under these stated
  assumptions," not "the true value" — `weight_robustness_report`
  quantifies how sensitive it is to that call, rather than asserting it
  isn't sensitive at all.

## Explicit scope cuts

- **No voice interface.** The brief calls it a bonus; cut first if time
  runs short, per `README.md`.
- **No persistent multi-user history or auth.** In-memory single-session
  history only (`app/main.py`) — fine for a live demo, not production.
- **27 airports, not the ~500 US scheduled-service fields.** See
  `DECISIONS.md`'s target-set entry — the exclusion is a stated scoping
  decision (small EAS-subsidized fields, and airports far outside any of
  the brief's four regions), not an oversight.
- **No FAA ASPM/OPSNET or BTS On-Time Performance data.** Both would
  strengthen a "constraint severity" / delay-based congestion criterion;
  ASPM access appears to need an FAA login, and BTS is blocked the same
  way T-100 is (see `DECISIONS.md`). The congestion/delay story this
  submission tells therefore leans on capacity/utilization proxies
  (runway count, enplanements relative to hub class) rather than
  measured delay minutes — stated here so it isn't presented as more
  than it is.
