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
  call, not laziness — same call rep-01 made.
- **[14:26] FAA CY2025 preliminary enplanements as primary source, not
  Wikipedia.** FAA's own site returned HTTP 403 on 2026-08-10 when rep-01
  was built; retried today and it's live (verified: page 200, both
  CY2024 and CY2025-preliminary xlsx 200 with real content). This is
  strictly better than rep-01's Wikipedia-sourced `enplanements.json`: no
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
