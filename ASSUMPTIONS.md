# Assumptions, uncertainty, and scope — [ASSIGNMENT NAME]

The brief explicitly scores this document: "clearly communicate
assumption, uncertainty and scoping." Listing what you didn't build, and
why, is rewarded, not penalized — see
Expect to be pushed on what you
*didn't* build and why."

## Assumptions

State each as a factual claim you're treating as true without verifying,
and what would break if it's wrong.

- **[Data assumption]** — e.g. "the public API's most recent data point
  is treated as current" — if wrong: [ranking could be stale by X].
- **[Domain assumption]** — e.g. "higher [metric] is always better for
  every user, regardless of their specific goal" — if wrong: [the
  weighting in `app/tools.py`'s `DEFAULT_CRITERIA` should be
  user-configurable instead of fixed].
- **[Scope assumption]** — e.g. "the user only ever compares items already
  present in the dataset" — if wrong: [unknown items surface as a tool
  error, not a fabricated guess — see `UnknownItemError` in
  `app/tools.py`].

## Uncertainty

Where the answer has a real error bar, not false precision.

- **[Data quality]** — e.g. "[public API]'s [field] has known reporting
  lag / self-reported bias" — how the agent should communicate this:
  [e.g. the system prompt's rule 4 requires stating this when it
  materially affects the answer].
- **[Model uncertainty]** — the deterministic score is exact given its
  inputs, but the CRITERIA and WEIGHTS themselves are a judgment call
  (see DESIGN_DOC.md §3) — the score is not "the true value," it's "the
  value under these stated assumptions."

## Explicit scope cuts

What you deliberately did NOT build, and why — this list is worth more
than it looks like it should be.

- **No voice interface.** The brief calls it a bonus; cut first per the
  runbook in README.md's "what to cut if time runs short."
- **No persistent multi-user history / auth.** In-memory single-session
  history only (`app/main.py`) — fine for a live demo, not production.
- **No retry/backoff on public-API calls in the example tool** (the
  `fetch_item_metrics` is a mocked in-memory dataset) —
  [replace this line once you wire a real API: state what retry/timeout
  policy you did or didn't add, and why].
- **[Your cut #1]** — why: [reason, e.g. "out of scope for a 24h build,
  would need X to do properly"].
- **[Your cut #2]** — why: [reason].
