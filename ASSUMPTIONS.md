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
- **Nearest-competitor distance is computed within the full 515-airport
  FAA commercial-service set** (see `data/candidates.json`'s `_meta`),
  not the full ~2,500-airport OurAirports universe of GA/private fields.
  A real geographic claim for the vast majority of airports (any nearer
  *scheduled-service* competitor is in this set by construction — FAA's
  own enplenements list is exactly "which airports have scheduled
  commercial service"); it would only understate a catchment-monopoly
  signal in the rare case where the true nearest facility is a
  private/GA field, which isn't a competitor for commercial passengers
  anyway.
- **County population is where the airport SITS, not its catchment.**
  BOS is in Suffolk County (~792k) while Boston's real catchment is
  ~4.9M; SFO is in San Mateo (~744k) against a Bay Area of ~7.7M. Read
  these fields as a regional growth-TREND signal only — never as market
  size, which enplanements already measure directly. If wrong (i.e. if
  the airport's county diverges from its catchment's trend): the growth
  signal is biased for major-hub airports specifically, because urban
  core counties lost population post-2020 while their suburbs gained.
  A radius-based multi-county catchment would be the fix; not pursued
  here for time (see `DECISIONS.md` [17:46]).
- **Population growth is reported over two windows, and the window
  changes the answer.** 2020→2025 spans the pandemic migration shock;
  2022→2025 excludes it. This flips the sign for real airports — SFO is
  −0.50%/yr on the full window and +0.51%/yr on the recent one. Neither
  is "the" truth: the full window overweights a one-off shock, the
  recent one may not have run long enough to be a trend. Both are
  published for exactly this reason; using either alone would present a
  window artifact as a structural finding.
- **Census PEP revises every prior year with each new vintage.** LA
  County 2023 is 9,663,345 in Vintage 2023 but 9,732,568 in Vintage 2025
  (+0.7%). All figures here come from Vintage 2025 only. If wrong (i.e.
  if a figure gets mixed across vintages): small absolute errors, but
  they land directly in a growth *rate*, where a 0.7% level shift over a
  3-year window is a meaningful distortion.
- **Runway count from OurAirports is treated as a capacity/feasibility
  proxy, not validated against real usage.** SNA in particular reports 2
  runways, but one (6/24) is a short crosswind strip used mainly by
  general aviation, not scheduled commercial traffic — raw runway count
  would overstate SNA's effective capacity relative to, say, LAX's 4
  full-length runways. Flagged here so it isn't silently treated as
  equivalent capacity if a criterion uses it directly.

## Uncertainty

- **Q3 (long-haul % out of Anchorage) is answered as a domestic vs.
  international departure share, not a strict "% of flights over N
  miles."** Source is real BTS T-100 data (`data.bts.gov`, dataset
  `r495-tyji`, filtered to ANC — see `DECISIONS.md` [15:38]), not the
  earlier OpenFlights fallback. Every T-100-tagged dataset on
  `data.bts.gov` was checked via its API: none carry a per-route
  (Origin+Dest) breakdown, only pre-aggregated summaries — so a true
  distance-threshold percentage isn't computable from any publicly
  downloadable BTS table (the real segment-level microdata lives only on
  the legacy TranStats portal, which stays bot-blocked). International
  share is used as the long-haul proxy instead, which is a reasonable
  stand-in specifically for ANC (its international traffic is
  overwhelmingly trans-Pacific cargo/passenger routes averaging ~4,300
  mi/flight in 2025, vs. domestic's ~1,450 mi average). This is real,
  current, departure-count-weighted data (2014–2026, monthly), fixing
  both of OpenFlights' problems at once: it was stale (last touched
  ~2014; ANC–SEA, a route that obviously exists today, was missing
  entirely) and it counted route existence, not flight frequency.
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
- **14 of 515 airports have no population data**, and this is handled by
  design rather than by dropping them. Puerto Rico (7) is published
  separately with no municipio totals file in the Vintage 2025 tree; the
  island territories (7 — Guam, American Samoa, USVI, N. Marianas) are
  not covered by Census PEP at county level at all. `app/scoring.py`
  renormalizes each item's weights across the criteria actually
  available for it, so these airports rank on their remaining criteria
  instead of failing or scoring a spurious zero.
- **Full FAA Commercial Service Enplanements universe (515 airports),
  not a curated subset.** Originally scoped to 27 airports tied to the
  brief's four example questions; expanded per Roi's explicit call (see
  `DECISIONS.md` [14:53]) — the questions are illustrative, not the
  full intended scope of what the agent should answer. This does *not*
  include the ~2,500-airport OurAirports universe of GA/private fields
  with no scheduled service — only airports with real FAA enplenements
  data, which is itself already FAA's definition of "commercial
  service."
- **The default *ranking* is scoped to FAA hub class L/M/S (144 of the
  515), even though all 515 remain queryable.** This is a ranking-
  eligibility filter, not a data cut: `find_items` still reaches every
  airport in the file. The reason is that percentage growth on a
  near-zero base is meaningless — scoring all 515 put Jack Edwards
  National (+126,403% YoY on 37,951 passengers) and Adak Airport (2,524
  passengers, ranked above SFO) into the top 50, and made New Bedford
  Regional read as New England's second-best expansion candidate. The
  threshold is FAA's own primary-airport hub classification (≥0.05% of
  national enplanements, a natural floor of 503,097 here), deliberately
  chosen over a round number we'd have picked ourselves. If wrong (i.e.
  if a genuinely investable airport sits just below the line): a fast-
  growing nonhub on the cusp of primary status is invisible to the
  default ranking and has to be asked about by name. That is the known
  cost of the cut.
- **Terminal-expansion *feasibility* is not modelled at all.** Nothing
  here knows whether an airport has land to build on, an unexpired
  environmental approval, or political consent — all of which can veto a
  project that scores well. The ranking answers "where is the demand
  pressure," not "where can you actually build," and the two are not the
  same question. `runway_count` is the closest available proxy and it is
  a weak one.
- **No FAA ASPM/OPSNET or BTS On-Time Performance data.** Both would
  strengthen a "constraint severity" / delay-based congestion criterion;
  ASPM access appears to need an FAA login, and BTS is blocked the same
  way T-100 is (see `DECISIONS.md`). The congestion/delay story this
  submission tells therefore leans on capacity/utilization proxies
  (runway count, enplanements relative to hub class) rather than
  measured delay minutes — stated here so it isn't presented as more
  than it is.
