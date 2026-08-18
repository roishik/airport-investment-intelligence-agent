# Decision log

One line per non-obvious choice, in build order, with why — written
**as** the choice was made, not reconstructed afterwards. Anyone reading
this should be able to reconstruct the reasoning without asking me.

The first section is architectural decisions that predate the specific
domain work; the second is the assignment itself, in the order the
choices actually happened.

## Architecture decisions

- **Hand-rolled agent loop, no framework** (`app/agent_loop.py`, ~70
  lines). At this size a framework's abstractions cost more to reason
  about than the loop they replace, and the loop is where termination,
  guardrail wrapping, and the reasoning trace all live — the three things
  worth being able to point at. See README "Why no framework."
- **`app/scoring.py` has zero I/O and zero LLM calls, on purpose.** It's
  the one file that has to be defensible as "not only LLM output" —
  keeping it pure means it's fully unit-testable with no mocking and no
  network.
- **Tools return per-component breakdowns (raw value, normalized score,
  weight, contribution), never a bare score**, so the LLM explains a
  number it never computed. Enforced at two levels: the tool's return
  shape (`app/tools.py`) and the system prompt's `NEVER_COMPUTE_RULE`
  (`app/system_prompt.py`).
- **`LLM_PROVIDER` defaults to `mock`, not `openai`.** Cloning this repo
  and running `pytest` or `python -m app.cli` works with zero setup — no
  key, no account, no auth debugging. A reviewer should be able to run it
  in under a minute.
- **LLM provider calls are non-streaming.** The agent loop needs the
  complete `tool_calls` list before it can decide what to do next, so
  streaming the model's tokens buys nothing on a tool-calling turn — see
  `openai_llm.py`'s docstring.
- **Chat UI is a single static HTML page + one FastAPI endpoint**, not a
  build-tooled frontend. UI polish is not what this brief asks for, and
  the tool-call log matters more than the styling.
- **Guardrails are a deterministic regex pre-filter, not a second LLM
  call.** An "is this an injection?" LLM call would be slower,
  non-deterministic, and itself attackable — see `app/guardrails.py` for
  what a production version would add instead.
- **Tool errors are caught and returned as `{"error": ...}` data**, never
  allowed to crash the loop or get silently swallowed. The model is told
  about the failure and is expected to say so, per system-prompt rule 5.
- **`max_turns` (default 6) hard-stops the loop and raises
  `MaxTurnsExceeded`** rather than looping forever if a provider keeps
  requesting tools. A hand-rolled loop has to enforce this itself.

## Data pipeline — consolidated summary

The itemized log below has the full reasoning behind each change, in the
order it happened; this section is the executive-summary version, kept
in one place because the story spans several entries and "what data do
you use and why" is a near-certain defence question.

### Required data categories

What the four brief questions plus general ranking (Q1's "candidates")
actually need, and where each comes from:

| Category | Used for | Source | Status |
|---|---|---|---|
| Airport identity/geo (name, municipality, region, lat/lon, type) | entity resolution, New England/LA-basin/SF-Bay filtering, nearest-competitor distance | OurAirports bulk CSV | Live-fetched, static file |
| Runway count | capacity/feasibility proxy | OurAirports `runways.csv` | Live-fetched, static file |
| Enplanements (multi-year), hub class, YoY change | passenger-volume and growth-trajectory criteria | FAA Commercial Service Enplanements (CY2025 preliminary + CY2024 final) | Live-fetched, static file |
| Nearest-competitor distance | catchment-monopoly signal | Derived (haversine) from OurAirports geo, computed across the full 515-airport set | Computed at build time |
| County population + migration (2020–2025, two growth windows) | regional demand-growth trend — the only demand-side signal in the set | US Census PEP Vintage 2025 county flat file, joined via Census Geocoder (lat/lon → FIPS) | Live-fetched, static file; 501/515 airports |
| ANC domestic/international departure mix + avg distance/flight | Q3 long-haul proxy | BTS T100 Segment Summary By Origin Airport (`data.bts.gov`, dataset `r495-tyji`) | Fetched once via `curl`, static file |
| Live operational status (closures/ground delays) | unscored operational color, satisfies brief's "use public APIs" live-call requirement | FAA NAS Status (`nasstatus.faa.gov`) | Planned (P3), not yet built |
| **Not covered**: BTS On-Time Performance (delay minutes), FAA ASPM/OPSNET (measured congestion) | would strengthen a real delay-based congestion criterion for Q2 | Both blocked — BTS the same bot-wall as T-100 segment data, ASPM needs an FAA login | Explicit scope cut, see `ASSUMPTIONS.md` |
| **Not covered**: true T-100 segment-level data (Origin+Dest+Distance+Departures per route, for ALL airports, not just ANC) | would let every airport (not just ANC) answer a "long-haul %" style question | TranStats portal, bot-blocked; confirmed absent from `data.bts.gov`'s entire catalog (see [15:38] below) | Explicit scope cut |

### Evolution (started with → changed to → why)

1. **Started**: 27 curated airports (16 "core" tied to the brief's four
   regions + 8 "context" hubs), OpenFlights `routes.dat` (community
   data, last touched ~2014) for ANC's route list. Built during scaffold
   prep, before the real assignment's data was live. See [14:25]–[14:30].
2. **Changed** (this session, [14:53]): expanded to the full 515-airport
   FAA commercial-service universe. Roi's call — the brief's four
   questions are illustrative examples, not the full intended scope; a
   27-airport set answers a demo, not a general-purpose tool. Surfaced
   and fixed a real parsing bug (FAA sheet footer rows) invisible at 27
   airports.
3. **Changed** ([15:38]): replaced OpenFlights with real BTS T-100
   monthly data for ANC, after confirming (via `data.bts.gov`'s own API,
   not just the visible catalog page) that no BTS open-data table has
   per-route granularity anywhere. Reframed Q3 as domestic/international
   departure share — real and current — instead of a route-existence
   percentage from a stale 2014 snapshot.
4. **Changed** ([15:47]): refresh-cadence design logged as a deferred
   feature, not built this session.
5. **Changed** ([17:46]): added county population + migration growth —
   the first demand-side signal in the set (everything before it
   described the airport, nothing described its region). Same step fixed
   14 airports that had been silently joined to foreign airports.
6. **Current**: every source in use is keyless; rebuilding `data/` from
   scratch needs no credentials at all.

### Current sources at a glance

| Source | What | Update frequency at origin | Key/auth |
|---|---|---|---|
| OurAirports | airports.csv, runways.csv | Rolling, no fixed schedule; changes rarely (airport metadata is close to static) | None |
| FAA Commercial Service Enplanements | enplanements xlsx (CY2025 prelim + CY2024 final) | Annual, ~6-month lag; preliminary→final revision mid-cycle | None |
| BTS T100 Segment Summary By Origin Airport | `data.bts.gov` Socrata API, filtered to ANC | Source metadata says "Annual," but the table itself carries monthly-grain history and appears current through 2026-04 | None |
| Census PEP Vintage 2025 county totals | `www2.census.gov` flat file — population + birth/death/migration, 2020–2025 | Annual (new vintage each spring, revising all prior years) | None |
| Census Geocoder | coordinates → county FIPS | Continuous (boundary vintages) | None |
| FAA NAS Status | `nasstatus.faa.gov` | Real-time | None (planned, not built) |

## Assignment decisions (in build order)

<!-- Format: **[HH:MM] decision** — why. Rejected: alternative, and why not. -->

- **[14:25] Target set: 27 airports, two tiers.** 19 "core" airports —
  the ones the brief's four questions name or imply (10 New England
  fields, LAX + 4 LA-basin alternatives, ANC, SFO + OAK + SJC) — plus 8
  "context" national hubs (ATL/ORD/DFW/DEN/JFK/SEA/PHX/MIA) added purely
  for ranking breadth, so Q1's "candidates" ranking isn't a boutique
  table of pre-selected winners with nothing real to compare against.
  Rejected: all ~500 US scheduled-service airports —
  correct in principle, but FAA-lookup and nearest-competitor cost scale
  with it for no defence value at this size; the exclusion list itself
  (small EAS-subsidized New England fields) is a documented, judgment
  call, not laziness.
- **[14:26] FAA CY2025 preliminary enplanements as primary source, not
  Wikipedia.** FAA's own site returned HTTP 403 on an earlier attempt
  (2026-08-10); retried today and it's live (verified: page 200, both
  CY2024 and CY2025-preliminary xlsx 200 with real content). This is
  strictly better than a Wikipedia-sourced enplanements table: no
  `/2` total-passengers-to-enplanements fudge, an official `Hub` class
  column (L/M/S/N), and a built-in `% Change` column that hands us a
  growth-trajectory criterion for free. Verified: file paths under
  `faa.gov/sites/faa.gov/files/...` (my first guess, from a cached
  earlier check) now 404 — the live paths are under
  `faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/`.
  `data/refresh_data.py` documents where to look if this moves again.
- **[14:28] Q3 (long-haul % from ANC) sourced from OpenFlights
  `routes.dat`, not BTS T-100.** BTS T-100 Segment (the authoritative
  source — real scheduled departures/seats/passengers per route) is
  blocked behind TranStats' bot-protected download portal: the file
  listing loads (200) but the actual ZIP GET 404s behind an F5
  session-cookie challenge. `data.transportation.gov`'s Socrata catalog
  doesn't carry T-100 either (checked — only unrelated Bay Area/corridor
  sets). OpenFlights is free, no key, and has 34 distinct ANC-origin
  routes with full geo coverage, but it's a stated fallback, not
  presented as current: it hasn't been refreshed since ~2014 (ANC-SEA, a
  route that obviously exists today, isn't in it), and it only has route
  EXISTENCE, not flight FREQUENCY — one flight a week and one a day count
  identically. The honest name for what this measures is "share of
  long-haul ROUTES," not "share of long-haul flights," and the true
  flight-weighted number is very likely lower (short Bush-Alaska hops
  plausibly fly more often than trunk routes). Roi has the option to
  hand-download the real T-100 extract from TranStats if he wants to
  attempt it; `refresh_data.py`'s `build_anc_routes()` docstring says
  exactly what to swap in if he does.
- **[14:30] Nearest-competitor distance computed only within the
  27-airport target set, not the full US airport universe.** For every
  "core" airport this is still correct by construction (the set was
  built so each core airport's real nearest major competitor is in it —
  e.g. SNA's is LGB, ANC's is SEA at 1,445 mi, matching the
  independently-known ANC–SEA distance of ~1,448 mi). For "context" tier
  airports the number is an artifact of the set's composition and is
  flagged as such in `candidates.json`'s `_meta`, not presented as a real
  geographic claim.
- **[14:53] Reversed [14:25]: target set expanded from the curated
  27 to the full FAA Commercial Service Enplanements list (515 airports
  after the join, ~520 in the raw sheet).** Roi's call: the brief's four
  questions are illustrative examples, not the full scope of what the
  agent should be able to answer — a scoping cut that only covers the
  four named questions is a demo, not a general-purpose tool, and
  narrowing to "top N by size" is a defensible follow-on layer, not the
  starting point. Rejected: keep 27 (cheap, already defended, matches
  the plan's own cut-list direction) — overruled by Roi directly; keep
  top-N by enplanements as a middle ground — also rejected, same
  reasoning, decide breadth vs. depth trade-offs later once there's a
  real reason to, not preemptively.
  Fixed a real bug surfaced by the expansion: `_load_faa()` was
  filtering rows on `Locid` alone, which let 6 unlabeled FAA sheet
  footer rows ("Large Count", "Total Primary Airports", ...) through as
  if they were airports, because their position under the Locid column
  happened to hold a count number. None of the curated 27 collided with
  this, so it was invisible until the join went national. Fix: also
  require a numeric `Rank` (`r[0]`), which footer rows never have.
  Also handled: ~30 of the ~520 real FAA Locids have no OurAirports
  `iata_code` (small/non-hub fields OurAirports doesn't consider
  IATA-worthy) — falls back to `local_code` (FAA LID), which recovers
  all but a genuine zero. 3 of those `local_code`s collide with an
  unrelated GA airstrip sharing the same 3-letter code in OurAirports;
  tie-broken by airport type (large > medium > small) since a code with
  real FAA enplanements data is never the GA strip. Verified all three
  (AFE, AWI, ORS) resolve to the airport that actually has enplenements,
  not the strip. `nearest_competitor` is now a real geographic claim for
  every airport in the set, not an artifact of a curated 27 — see
  `candidates.json`'s `_meta.nearest_competitor_note`.
  BTS T-100 (see [14:28]) is unaffected by this — Roi is hand-downloading
  it for the Anchorage long-haul question specifically (domestic +
  international, passenger + all-cargo, per his own call, since ANC's
  real long-haul traffic is largely cargo) — that swap is still pending,
  tracked separately, not resolved by this entry.
- **[15:38] Resolved [14:28]/[76-94]: Q3 now sourced from real BTS data
  (data.bts.gov, not TranStats), reframed as domestic vs. international
  departure share, not OpenFlights route-existence.** Searched every
  T-100-tagged dataset on data.bts.gov's open catalog (`AFF - T100
  Segment Summary`, `...By Carrier`, `...By Country`, `...By Origin
  Airport`, `...Monthly`, `T100 - Preliminary Estimates`) via its
  Socrata API, not just the visible category list — confirmed none of
  them carry a per-route (Origin+Dest) breakdown; only pre-aggregated
  "Aviation Facts & Figures" rollups. The true segment-level microdata
  with Origin+Dest+Distance+Departures per route lives only on the
  legacy TranStats portal, still bot-blocked (Roi didn't attempt a
  manual TranStats session this round — chose the faster real-data path
  instead, see the question this resolves).
  Used `AFF - T100 Segment Summary By Origin Airport` (data.bts.gov,
  dataset `r495-tyji`) filtered to ANC instead — real monthly data,
  2014-01 through 2026-04, public Socrata API, no key/auth/bot-block.
  Pulled via `curl` (no browser download needed) into
  `data/bts_anc_origin_summary.json`, then `data/refresh_data.py`'s
  `build_anc_routes()` was replaced with `build_anc_traffic_mix()`,
  producing `data/anc_traffic_mix.json`. `data/anc_routes.json` and
  `data/openflights_routes.dat` deleted — no longer used.
  Verified against the raw data (every row, not assumed): `total_departures
  == domestic_departures + outbound_international` exactly.
  `inbound_international` (flights arriving at ANC from abroad) is a
  separate BTS figure and is excluded — it answers "ANC's international
  exposure," not "flights out of Anchorage."
  Real 2025 numbers: 87,988 total departures from ANC, 16.0%
  international, average domestic distance/flight 1,457.5 mi (itself
  already long-haul-heavy — ANC-SEA alone is ~1,448 mi), average
  outbound-international distance/flight 4,322.3 mi (trans-Pacific
  cargo/passenger routes to Asia). This can't produce a strict
  "% of flights over N miles" (no per-route rows to threshold), but the
  domestic/international split is a defensible long-haul proxy for ANC
  specifically, and it's real current data instead of a stale 2014
  snapshot with a route-count-not-frequency limitation.
- **[15:47] Refresh cadence + one-click refresh: designed, deferred.**
  Roi's call: the intended defence answer is "yes, data refreshes on a
  cron (daily or monthly) or with one click from the UI" — every current
  source supports this (all three are free, no-key, no-auth; `refresh_data.py`
  already fetches-and-rebuilds idempotently, each run fully overwriting
  its output file rather than incrementally patching it, so a cron job
  calling it needs no special retry/merge logic). Not built this
  session — building it doesn't help answer any of the four scored
  example questions, and P2 (criteria/weights) and P3 (wiring real data
  into `app/tools.py`, still on `_MOCK_DATASET`) are ahead of it in the
  schedule. Logged now so the design is on record as a real one rather
  than reconstructed after the fact, and picked up later only if time
  allows.
  Design, if built: (1) **cadence** — no single interval fits every
  source (OurAirports barely changes; FAA revises ~annually with a
  preliminary→final swing mid-cycle; BTS's own metadata says "Annual"
  despite carrying monthly-grain history) so a **daily cron is simplest
  and correct by construction** — each source's fetch-and-rebuild step
  is a no-op in substance on days nothing changed upstream, just wasted
  (cheap) requests, versus under-fetching and missing a revision.
  (2) **One-click** — a `POST /admin/refresh` route in `app/main.py`
  calling the same `fetch_sources()` → `build_candidates()` →
  `build_anc_traffic_mix()` pipeline synchronously, with progress/output
  surfaced through the live tool-call log UI already built for tool
  calls (`app/agent_loop.py`) so a refresh is visibly happening, not a
  silent background swap. (3) **Safety** — `refresh_data.py` writes to
  new files then the caller swaps them in (or, simplest: the current
  behavior of overwriting in place is fine since every build is a full
  rebuild from source, not a diff/patch — there's no partial-write state
  to corrupt into). Rejected: incremental/delta refresh — no source here
  is large enough (515 airports, 148 ANC months) to justify the
  complexity; a full rebuild every time is simpler and self-healing.
- **[16:07] True per-flight long-haul % for Q3 (via OpenSky Network):
  evaluated, deferred, not built.** Roi surfaced a candidate set of
  flight-data APIs (via a conversation with Gemini) that might get past
  the "no per-route data anywhere on data.bts.gov" wall from [15:38] and
  produce a real distance-threshold percentage instead of the
  domestic/international proxy. Checked each against what's actually
  needed — a per-flight departure log for ANC with a real destination,
  so individual flights (not an average) can be bucketed by distance:

  | Option | Data shape | Free-tier reality | Cargo coverage |
  |---|---|---|---|
  | **OpenSky `/flights/departure`** | Real ADS-B-tracked departures, `estArrivalAirport` per flight | Free registration (OAuth2 client-credentials, no indication of a card requirement); 4,000 credits/day standard tier, a ≤2-day query costs 30 credits (rate confirmed from `openskynetwork.github.io/opensky-api/rest.html`, not from Roi's Gemini conversation) — ~130 requests/day free, enough for a full month in one sitting | Tracks all transponder-equipped aircraft — the only option that reliably sees FedEx/UPS trans-Pacific flights, which is most of what makes ANC's long-haul story real |
  | FlightAware AeroAPI | Also real ADS-B-based | $5/month free credit, metered per-record — probably a few hundred flights before it's gone | Likely good (also ADS-B), but budget is tight |
  | AeroDataBox | Airport departure boards, right shape | 30–200 requests/month (RapidAPI free tier) — maybe 1–2 weeks of days, not a real sample | Uncertain |
  | Aviationstack | Flight schedule/status | Free plan blocks date filters entirely; historical/future needs a paid Basic plan or a CC-gated trial | Uncertain — GDS-adjacent sources often miss all-cargo carriers |
  | Amadeus Self-Service | Bookable fares / published passenger schedules | Generous free quota, but wrong data shape (booking GDS, not operations) | Likely misses cargo entirely |

  **OpenSky is the clear best fit** if this gets picked up later: free
  at a genuinely usable volume, and the only option that reliably
  captures cargo operations. Real cost is registration (Roi, not
  Claude — account creation is off-limits) plus implementation: OAuth2
  token flow, pagination in ≤2-day chunks (the endpoint's own limit)
  across a representative period, joining `estArrivalAirport` to
  `candidates.json`'s coordinates for distance, and handling that
  `estArrivalAirport` is an *inferred* estimate that can be null (needs
  explicit reporting, not silent dropping — same principle as the
  `unmatched_faa_locids` handling in [14:53]).
  Rejected for now, not rejected outright: Roi's call — P2 (criteria)
  and P3 (wiring real data into `app/tools.py`) are ahead of this on the
  clock, and the current BTS domestic/international answer from [15:38]
  is already a real, defensible upgrade over the original OpenFlights
  fallback. Pick this up only if time allows; if it lands, it *replaces*
  the domestic/international proxy with a true "% of flights over N
  miles," not something layered alongside it.
- **[17:46] Added regional population growth (US Census), county-level,
  two windows, keyless.** Roi's call: the dataset had no demand-side
  signal at all — every existing field describes the airport (size,
  runways, traffic) and none describes the *region it serves*, which is
  what actually makes an airport an investment opportunity. Chose Census
  Population Estimates over the alternatives he surfaced (building
  permits / IPUMS / Boundary-Annexation / Zillow / ATTOM): permits are a
  second-order leading indicator, IPUMS needs registration and is built
  for microdata research, BAS tracks rare boundary events rather than a
  rankable metric, and the commercial ones cost money for a signal the
  official source already gives free.
  **Geography: county, chosen by Roi over place and CBSA.** Place (city)
  maps straight onto the existing `municipality` field but misses
  suburban growth; CBSA is the truest catchment but needs a metro-boundary
  mapping per airport. County is the middle: wider than the city, exact
  FIPS join, no boundary definitions to invent.
  **Joined by geocoding, not name matching.** Airport lat/lon → county
  FIPS via the Census Geocoder (keyless), because county names repeat
  across states (30-odd Washington Counties) and municipality strings are
  ambiguous — the same class of silent-wrong-answer bug as the FAA LocID
  join. 515/515 airports geocoded, no failures.
  **Source: the published Vintage 2025 flat file, NOT the Census Data
  API — and this is the interesting part.** The API's newest
  county-capable dataset is Vintage 2023 (`2024/pep.json` and
  `2025/pep.json` both 404), which would have pinned the growth window to
  2020→2023 — i.e. *entirely inside the pandemic migration shock*, where
  52% of airports showed negative county growth and LA/SF read as
  structurally declining markets. Roi pushed back on treating the 404 as
  final rather than accepting the degraded window; checking Census's
  published-files tree found Vintage 2025 sitting there. The flat file
  wins on every axis: 6 years instead of 4, ends 2025 instead of 2023,
  carries birth/death/migration components the API's county endpoint
  doesn't expose, and **needs no API key at all**. Roi had already
  obtained a Census API key for the API path; it is now unused and was
  removed from `app/config.py` and `.env.example` rather than left as
  dead config. Rejected: keeping the API — strictly worse data behind an
  extra credential.
  **Two windows, both reported.** 2020→2025 (full published series) and
  2022→2025 (post-shock). This is not hedging: the window flips the sign
  for real airports — SFO reads −0.50%/yr on the full window and
  +0.51%/yr on the recent one, BOS goes flat (+0.01%) to growing
  (+0.59%). Reporting one number would present a window artifact as a
  structural finding. Same principle as D3's multi-threshold Q3 answer.
  Also carried: net and domestic migration for the recent window, raw and
  per-1,000 — an in-migrant generates air travel demand this year, a
  birth doesn't for ~18, so migration is the better forward signal and is
  kept as its own field rather than folded into the population rate.
  **Known limitation, stated in `candidates.json`'s `_meta` and
  `ASSUMPTIONS.md`:** this is the county the airport SITS IN, not its
  catchment. BOS → Suffolk County (~792k) against a real Boston catchment
  of ~4.9M; SFO → San Mateo (~744k) against a Bay Area ~7.7M. So these
  fields are a regional growth-TREND signal and must never be used as
  market size — enplanements already measure size directly. Rejected
  (for now): summing counties within a ~50mi radius, which would be a
  genuine catchment proxy but needs a county-centroid fetch and ~30-40
  min that P2/P3 need more.
  **Coverage: 501/515 airports.** The 14 without population are Puerto
  Rico (7 — published separately, and the Vintage 2025 tree has no
  municipio totals file) and the island territories (7 — Guam, American
  Samoa, USVI, N. Marianas, which PEP does not cover at county level).
  They are NOT dropped: `app/scoring.py` renormalizes weights across the
  criteria actually available per item, so they still rank on their
  remaining criteria. This is the A1 missing-data fix earning its keep on
  real ragged data rather than a synthetic test.
  **Vintage revision caveat:** each PEP vintage revises all prior years —
  LA County 2023 is 9,663,345 in Vintage 2023 but 9,732,568 in Vintage
  2025 (+0.7%). Compare only within a vintage; never mix. Noted in
  `census_county_population.json`'s `_meta`.
- **[17:46] Fixed a silent data-corruption bug the population work
  surfaced: 14 airports were joined to FOREIGN airports.** Adding county
  geocoding meant looking at `iso_region` per airport, which exposed
  entries in Iran, Russia, China, Turkey, Brazil, Australia and 8 more
  inside a US-only dataset. Cause: [14:53]'s join matched FAA LocIDs
  against OurAirports' **global** `iata_code` index, and a US FAA LID
  collides with foreign IATA codes — FAA `SAW` (Marquette/Sawyer,
  Michigan) resolved to Istanbul Sabiha Gökçen, `IWA` (Mesa Gateway,
  Arizona) to Ivanovo, Russia, `HXD` (Hilton Head) to Haixi, China. Each
  one put a real US airport's enplanements onto a foreign airport's name
  AND coordinates, which also silently corrupted those airports'
  `nearest_competitor` distances. Fix: restrict the OurAirports universe
  to US + territories *before* any matching, so the collision is
  impossible rather than something a tie-break has to notice. All 14 then
  resolve correctly via `local_code`. Also added an explicit `iata_code`
  field, since for ~30 airports the FAA LocID key is NOT the IATA code
  (`SAW`→MQT, `IWA`→AZA) and entity resolution needs to accept both.
  Worth noting how it was caught: not by a test, but by looking at a
  distribution (`iso_region` value counts) rather than spot-checking
  familiar airports — BOS/LAX/ANC/SFO all looked perfect throughout.
- **[18:10] Fixed three factual errors in `candidates.json`'s shipped
  `_meta` block** (`data/refresh_data.py:522,544`). It credited the
  population data to **"US Census PEP Vintage 2023"** — the exact vintage
  [17:46] rejected as strictly worse, so the shipped artifact contradicted
  its own decision log. Also BOS's illustrative county population read
  "~768k" against an actual 791,891, and the missing-population note
  blamed only the island territories, omitting Puerto Rico's 7 of the 14.
  Caught by cross-reading the three places the same fact is stated
  (`census_county_population.json`'s `_meta`, `DECISIONS.md`, and
  `candidates.json`) rather than trusting any one of them — the same
  distribution-over-spot-check habit that caught the foreign-airport join.
  Worth stating as a general lesson: a hand-written `_meta` string is
  documentation that ships as data, and nothing tests it.

## P2 — criteria and weights (the defended artifact)

- **[18:20] Eligible set narrowed to FAA hub class L/M/S — 144 of the 515
  airports — and this is a *ranking* filter, not a data cut.** All 515
  stay in `candidates.json` and stay addressable by `find_items`; what
  changes is which airports are candidates for the default ranking.
  Why it was needed: scoring all 515 put **8 airports under 500k
  enplanements into the top 50**, purely as percentage-growth artifacts
  on a near-zero base — Jack Edwards National at **+126,403% YoY** on
  37,951 passengers, Show Low Regional at +183% on 10,345, Adak Airport
  (2,524 passengers) ranked #23 nationally, *above SFO at #34*. They
  clamp to max score on `traffic_growth` and usually on
  `catchment_monopoly` too (remote ⇒ far from any competitor), which is
  45% of total weight won by being tiny and volatile. It also directly
  broke Q1: New Bedford Regional (3,145 enplanements) read as New
  England's **second-best** expansion candidate, ahead of Bradley,
  Portland and Providence.
  **Chose FAA's own hub classification over an invented enplanements
  floor.** L/M/S is the FAA's definition of a primary airport at ≥0.05%
  of national enplanements; it lands at 144 airports with a natural floor
  of 503,097. The defence is "I didn't pick a threshold, I used the
  regulator's own — the same classification FAA uses for capacity
  planning and AIP funding," which is strictly better than defending a
  round number I chose. Rejected: a 500k enplanements floor (identical
  144-airport result, but an arbitrary number I'd have to justify);
  keeping all 515 and disclosing the artifact in `ASSUMPTIONS.md`
  (honest, but ships a ranking whose top-50 is visibly wrong on
  inspection — and "documented" is not the same as "defensible" when the
  output is plainly wrong).
  Verified after the cut: top 20 contains no absurdities, and Q1's New
  England answer becomes BOS → HVN → PWM → MHT → BDL → PVD → BTV. HVN
  (Tweed New Haven) ranking 2nd is a real-world check passing — it is
  genuinely mid-terminal-expansion right now.
- **[18:20] Five criteria, weights 25/25/20/15/15.** In order:
  `traffic_growth` 25, `regional_demand_growth` 25, `catchment_monopoly`
  20, `capacity_pressure` 15, `absolute_scale` 15.
  The brief's framing sentence asks where renovation is *most profitable
  based on increased capacity* — a headroom question, not a size
  question. So forward-looking signals carry **50%**, size-flavored ones
  **30%**, with `absolute_scale` alone at 15% (the plan capped it at
  25%). Sanity check that this worked: **LAX ranks #67 of 144**, not #1.
  **Bounds are the 5th/95th percentile of the eligible 144**, hard-coded
  as constants rather than recomputed per query, so a ranking is
  reproducible and inspectable rather than shifting silently when the
  candidate set changes. Symmetric percentile clipping is used for all
  five rather than log-transforming the skewed ones — one consistent
  normalization rule across every criterion is far easier to defend than
  five bespoke ones, and `Criterion.normalize` already clamps out-of-range
  values at both ends.
- **[18:20] `capacity_pressure` (enplanements ÷ runways) kept despite
  correlating r=0.89 with `absolute_scale` — disclosed, weighted low, not
  hidden.** Measured across all 515 airports it is 0.89 with raw
  enplanements and 0.986 in log space: it is largely absolute size in
  different units, not the independent "how close to the ceiling" signal
  it looks like. Roi's call to keep it: it is the most direct available
  proxy for congestion, and it is what Q2 (LAX vs. SNA congestion) reads
  from, so removing it would leave that question with nothing to answer
  from. Mitigation: it and `absolute_scale` together are held to 30%, and
  the correlation is stated up front here and in `DESIGN_DOC.md` rather
  than waiting to be found. Rejected: raw `runway_count` instead
  (r≈0.53–0.59 with size, so less redundant, but a much weaker and
  murkier signal); dropping to 4 criteria (cleanest, but costs Q2 its
  only congestion input).
- **[18:20] Population scored on `county_population_cagr_recent`
  (2022→2025) only — the other two population fields are reporting, not
  scoring.** The three are internally near-collinear (full vs recent CAGR
  r=**0.90**; migration-per-1,000 vs CAGR r=**0.82–0.83**), so scoring
  more than one would double-count the same regional-demand fact — the
  same trap as `capacity_pressure`, caught before it shipped this time.
  Chose the recent window because the full 2020→2025 series bakes in the
  pandemic migration shock as if it were a trend (it is what makes SFO
  read −0.50%/yr and LA/SF look structurally declining). Rejected:
  migration-per-1,000, despite [17:46]'s own argument that migration is
  the better forward signal — it is a *component* of the CAGR rather than
  an independent axis, and its range (−92 to +113 per 1,000) is far
  noisier. That argument isn't discarded, it's demoted to the sensitivity
  report below.
  Confirmed the population family is a genuinely **new** axis, not more
  of the same: r=0.10–0.18 vs enplanements, 0.11 vs traffic growth, 0.01
  vs monopoly distance. This is the criterion that actually fixes the
  "ranks by current size" failure the brief's framing punishes.
- **[18:20] Ran `weight_robustness_report` on the final configuration
  immediately, and the headline result is that the #1 slot is NOT
  decisive — reporting that is the point.** Nashville (BNA, 0.6343) and
  Denver (DEN, 0.6317) are **0.42% apart**, and the winner flips at a
  0.9× multiplier on `traffic_growth` — i.e. a 10% weight change. Ties
  and near-ties recur below it: PVU and LAS are exactly equal at 0.5700,
  MCO and CLT differ by 0.0004.
  The overall ordering is much more stable than the top slot: Kendall tau
  stays **0.76–0.91** across halving or doubling *any* single criterion,
  and 0.85 against flat 20/20/20/20/20 weights — so the weighting
  judgment is load-bearing but not wild.
  What makes this worth defending rather than hiding: BNA and DEN tie
  **for opposite reasons**. BNA wins on growth (0.1377), regional demand
  (0.1696) and a maxed-out monopoly component (0.2000); DEN wins on scale
  (0.1500) and capacity pressure (0.1272). "Nashville is the growth case,
  Denver is the scale case, and at these weights they are indistinguishable"
  is a real finding about the domain — presenting either as *the* answer
  would be the actual error.
  **Consequence for P3:** the ranking tool must surface near-ties
  explicitly instead of implying a decisive winner, reusing the
  `decisive` pattern already in `app/entity_resolution.py` (a confidence
  floor plus a required gap) rather than inventing a second convention.
  Also measured, so the D2b window choice is stated as a number rather
  than a preference: swapping the population criterion to the full window
  gives tau=0.89 (top becomes GPI), to migration-per-1,000 tau=0.88 (top
  becomes DEN).

## P3 — wiring real data into the agent

- **[18:50] Runway geometry is COMPUTED, not looked up — and this is the
  most defensible thing in the submission.** Q4 asks for unmet demand at
  SFO "and why," and the "why" is the hard half: a correlation does not
  survive being asked twice, a mechanism does. SFO's real constraint is
  physical and published — its parallel arrival runways are ~750 ft apart,
  far below the 2,500 ft FAA requires for even dependent simultaneous
  approaches, so in low visibility the two arrival streams collapse into
  one and the arrival rate halves while the schedule doesn't.
  Rather than hardcode that fact, `app/runway_geometry.py` derives it:
  OurAirports publishes runway-end coordinates and true headings, so the
  perpendicular centerline separation is computable. It returns **746.8 ft
  for SFO against a published 750** — 0.4% off, from public data.
  Subtlety that matters: it must be measured PERPENDICULAR to the runway
  heading, not threshold-to-threshold. SFO's thresholds are staggered, so
  the naive straight-line distance is 893 ft, which lands the airport in
  the wrong FAA band. There's a test pinning both numbers.
  The same computation runs on all 515 airports, which is what makes it a
  model rather than one fact with arithmetic around it. It independently
  recovers things nobody told it: **Denver shows ZERO degradation** (built
  with runways 2,510+ ft apart, deliberately, for exactly this reason),
  **Seattle 0.67** (16C/16L are 738 ft apart), **SNA 0.00** (single
  runway). Rejected: hardcoding SFO's 750 ft — it would have been faster
  and it would have collapsed the moment anyone asked about a second
  airport.
- **[18:55] The unmet-demand model replaced outright, not force-fitted.**
  The skeleton's model was turnaways + discounted waitlist, which has no
  airport analogue — no one records the passenger who was never
  scheduled. Rewrote it as two additive terms with separate mechanisms:
  weather-suppressed throughput (the runway-geometry story above) and
  structural capacity deficit (demand projected one year forward at the
  airport's own traffic and county-population growth, minus good-weather
  runway capacity). The generic contract in `app/analytics.py` —
  factors that provably sum to the value, mandatory assumptions and
  caveat — survived untouched, which is the architecture working as
  designed.
  **The property worth defending is that it self-gates.** Anchorage loses
  a third of its arrival capacity in low visibility and still returns
  ZERO unmet demand, correctly, because at 12% utilization the remaining
  capacity covers everything that wanted to fly. Weather degradation is
  only a problem where demand is already near the ceiling. SFO returns
  1.28M annual enplanements, **100% of it weather-driven and 0%
  structural** — i.e. SFO does not need more terminal, it needs runway
  separation it physically cannot have. That is the actual finding.
  Capacity per arrival stream (7.8M enplanements/yr) is the 95th
  percentile actually achieved across the eligible 144, not an invented
  throughput figure. Noted honestly: San Diego does 12.7M on one runway,
  so p95 is deliberately conservative and the estimate is a lower bound.
  **Stated weakest input, first, in the assumptions:** IMC frequency is a
  single national 12% applied uniformly, when the real rate is intensely
  local (SFO's summer marine layer vs. Phoenix). Per-airport METAR
  history from aviationweather.gov would fix it and is the highest-value
  upgrade to the model.
- **[19:30] Three bugs found by RUNNING the four questions, not by
  reading the code. All three produced confident, plausible, wrong
  answers — which is the category that matters.**
  1. **Q3 reported "0% of flights out of Anchorage are long haul."** The
     model asked `aggregate_records` for category `"long haul"`; the real
     categories are `domestic`/`international`; zero rows matched and the
     tool reported a zero. Every number in that sentence was correct and
     the sentence was false. Fix: distinguish "no such category" from "a
     real category with zero rows" — `unknown_category` plus
     `known_categories` plus a `category_semantics` string saying which
     available category is the right proxy and what its limitation is.
     This is the same guard `find_items` already had via
     `unknown_filter_keys`, applied to a category VALUE rather than a
     filter KEY; the gap was that the idea had only been implemented in
     one of the two places it applies.
  2. **The eligibility gate leaked.** Asked for New England candidates,
     the model called `find_items` without the eligibility filter and New
     Bedford Regional (3,145 passengers, +53% "growth") came back ranked
     4th — the exact failure the P2 gate exists to prevent, reappearing
     because the gate lived in a filter the LLM had to remember to pass.
     Fix: enforcement moved into `compare_items` itself, where it cannot
     be bypassed by any prompt. Ineligible airports are RETURNED in an
     `ineligible` list with a reason rather than silently dropped — the
     user asked about them. `include_ineligible=True` is the deliberate
     override. General lesson worth stating: a correctness rule the model
     has to remember is not a rule, it's a suggestion.
  3. **`resolve_entity("LA")` returned Lawton, Oklahoma** at 0.83
     confidence, plus La Crosse and Lafayette — a two-character query is
     a prefix of all three and Jaro-Winkler pays a large prefix bonus.
     Two fixes: a `MIN_FUZZY_QUERY_LENGTH` guard (under 4 characters,
     exact match only — a short query carries too little signal to rank
     on), and a metro layer, because "LA" genuinely is not an airport.
     `METRO_AIRPORTS` is the one hand-written structure in `dataset.py`
     and it earns the exception: no public column says which airports
     share a metro market. It returns all five LA-basin airports as
     explicitly non-decisive, so the agent must state which reading it
     used rather than silently picking the busiest.
- **[19:40] `MaxTurnsExceeded` now carries its partial work.** It
  previously raised bare and `/chat` had no handler, so a live demo that
  tripped the turn ceiling showed a blank UI and an HTTP 500. Hitting the
  ceiling means the agent ran out of turns, not that it learned nothing —
  it may have made five good tool calls and never written them up. The
  exception now carries the transcript and tool log, and `/chat` returns
  a 200 with an honest partial answer plus the full tool log. History is
  deliberately NOT updated on that path: the turn never reached a final
  assistant message, and persisting a truncated transcript would corrupt
  every subsequent turn. Converts a demo-day disaster into a
  "here's my termination guarantee working" talking point.
- **[19:45] FAA NAS Status is the one live call, and it is deliberately
  outside the scored path.** Free, no key, real-time, and it returns XML
  rather than JSON. A ground stop at SNA this afternoon says nothing
  about whether SNA is worth a terminal investment over a decade — it is
  weather or an equipment outage. Feeding transient operational status
  into a capital-planning score would not survive ten seconds of
  questioning, so it is presented as live operational colour with a
  `scope_note` in the payload itself and a system-prompt rule forbidding
  the model from treating it as evidence. Every failure mode returns
  `available: false` with a reason rather than raising: this is decoration
  on an answer that must still work without it, and a timeout on an
  optional feed should degrade the response, not fail the question.
