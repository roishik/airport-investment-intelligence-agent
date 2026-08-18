"""
entity_resolution.py — deterministic fuzzy matching that turns a free-text
query ("LA", "the Anchorage one", "Ankorage") into item ids, so the LLM
never has to know, remember, or guess an id itself.

RULES FOR THIS FILE (same discipline as scoring.py):
  1. ZERO I/O, ZERO LLM calls, ZERO network. Pure string comparison.
  2. Every function is PURE: same inputs -> same outputs.
  3. No third-party dependencies — Jaro-Winkler and Soundex are
     implemented here, in full, deliberately. See "Why not embeddings"
     and "Why hand-rolled" below.

WHY NOT EMBEDDINGS / word2vec (asked in review 2026-08-17, and the
answer is not "we ran out of time"):
Embeddings measure MEANING similarity. Entity resolution needs IDENTITY
similarity, and for proper nouns and codes the two actively conflict.
`LAX` and `LGB` are both rare tokens that embed as "airport-ish," so an
embedding model scores them SIMILAR — which is precisely backwards, since
telling them apart is the whole job. Production record-linkage systems
(Fellegi-Sunter, Splink, Dedupe) use string metrics + phonetic keys +
blocking for exactly this reason. Where semantics genuinely helps is the
paraphrase hop ("the windy city" -> "Chicago"), and the LLM already does
that for free upstream of this module: the model proposes a NAME, this
module resolves that name to an ID with a confidence. Model does world
knowledge; deterministic code does identity. That split is also what
keeps "the LLM can never invent an id" true.

WHY HAND-ROLLED rather than rapidfuzz/jellyfish:
Two fewer dependencies, and every line here is short enough to explain
and to unit-test in isolation. A library whose internals are opaque is a
liability when the resolver returns a surprising match and you need to
say why. Double Metaphone would beat Soundex on hard phonetics; that's a
known, accepted limitation, not an oversight.

This module's job is not merely "here are some candidates" — it's "is
this match good enough to ACT on" (`decisive` on ResolutionResult).
app/tools.py wires `decisive` straight to system-prompt behavior: when
it's False the model must state the ambiguity and ask rather than
silently pick the top candidate. That is the runtime demonstration of
"communicate assumptions and uncertainty," not just a doc asserting it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

# A candidate must clear this blended score to be surfaced at all —
# below it, it isn't a plausible candidate, it's noise. NOT picked by
# feel: it's the midpoint of the measured gap between labelled
# should-match and should-not-match pairs. Re-derive it with
# `PYTHONPATH=. python scripts/calibrate_resolver.py` after touching any
# weight or metric here, and re-derive it again against REAL names once a
# rep swaps in a real dataset — a threshold calibrated on placeholder
# data is only as good as that data.
MIN_RELEVANCE = 0.63

# The two-part bar for "decisive". Both must hold — each targets a
# different failure mode; see resolve()'s docstring.
#
# The confidence floor sits deliberately ABOVE MIN_RELEVANCE. If they
# were equal (or inverted) every surfaced candidate would clear the floor
# automatically and only the gap check would do any work — a dead
# condition that still looks like a safeguard, which is worse than not
# having it. Surfacing and acting are two different bars: 0.63 says
# "worth showing the user", 0.75 says "safe to act on unasked".
DECISIVE_MIN_CONFIDENCE = 0.75
DECISIVE_MIN_GAP = 0.15  # ...and clearly ahead of the runner-up

# Blend weights for the final confidence, CALIBRATED against labelled
# should-match / should-not-match pairs rather than picked by feel — see
# scripts/calibrate_resolver.py, which prints the separation between the
# two classes and fails loudly if they overlap.
#
# The first attempt weighted whole-string Jaro-Winkler at 0.6 and had
# NEGATIVE separation: 'the weather in paris' scored 0.54 against 'the
# alpha option' while the genuine match 'alpha' scored only 0.48. Two
# compounding causes, both worth knowing:
#   1. A short query is punished by length mismatch against a longer
#      alias, even when it appears in that alias verbatim.
#   2. A shared leading stopword ("the ") collects an undeserved Winkler
#      prefix bonus AND a free Jaccard hit.
# token_containment fixes both: it matches each query token against its
# best candidate token, weighted by token LENGTH, so long distinctive
# words dominate and stopwords can no longer carry a match on their own.
# That's why it now carries the largest share.
_W_TOKEN_CONTAINMENT = 0.5
_W_JARO_WINKLER = 0.3
_W_TOKEN_SET = 0.1
_W_PHONETIC = 0.1


@dataclass(frozen=True)
class EntityCandidate:
    item_id: str
    matched_text: str  # whichever id/name/alias produced this score
    confidence: float  # 0..1 blended score
    signals: tuple[tuple[str, float], ...]  # per-metric breakdown, same "explain, don't assert" habit as scoring.py


@dataclass(frozen=True)
class ResolutionResult:
    query: str
    candidates: tuple[EntityCandidate, ...]  # descending confidence, ties by item_id
    decisive: bool


def _normalize(text: str) -> str:
    """Casefold, collapse whitespace, drop punctuation. Deliberately does
    NOT strip generic domain words ("airport", "international") — that's
    a per-domain decision the caller makes when building its catalog, not
    something a generic matcher should assume."""
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text.casefold())
    return " ".join(cleaned.split())


def jaro_similarity(s1: str, s2: str) -> float:
    """Jaro similarity: proportion of matching characters (within a
    sliding window) adjusted for transpositions. The base metric that
    Jaro-Winkler refines."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    # Characters farther apart than this can't count as a match.
    match_window = max(len1, len2) // 2 - 1
    if match_window < 0:
        match_window = 0

    s1_matched = [False] * len1
    s2_matched = [False] * len2
    matches = 0
    for i, ch in enumerate(s1):
        start = max(0, i - match_window)
        end = min(i + match_window + 1, len2)
        for j in range(start, end):
            if not s2_matched[j] and s2[j] == ch:
                s1_matched[i] = True
                s2_matched[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    # Count transpositions: matched chars that appear in a different order.
    transpositions = 0
    k = 0
    for i in range(len1):
        if not s1_matched[i]:
            continue
        while not s2_matched[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    transpositions //= 2

    return (matches / len1 + matches / len2 + (matches - transpositions) / matches) / 3


def jaro_winkler_similarity(s1: str, s2: str, prefix_scale: float = 0.1, max_prefix: int = 4) -> float:
    """Jaro, boosted when strings share a leading prefix. The prefix bonus
    is why this beats plain edit distance on names and codes: people get
    the START of a name right far more often than the end, so agreement
    there is stronger evidence of identity."""
    jaro = jaro_similarity(s1, s2)
    prefix_len = 0
    for a, b in zip(s1[:max_prefix], s2[:max_prefix]):
        if a != b:
            break
        prefix_len += 1
    return jaro + prefix_len * prefix_scale * (1 - jaro)


_SOUNDEX_CODES = {
    **dict.fromkeys("bfpv", "1"),
    **dict.fromkeys("cgjkqsxz", "2"),
    **dict.fromkeys("dt", "3"),
    **dict.fromkeys("l", "4"),
    **dict.fromkeys("mn", "5"),
    **dict.fromkeys("r", "6"),
}


def soundex(word: str) -> str:
    """Classic Soundex: first letter + 3 consonant-class digits, so
    same-sounding spellings collide ('Anchorage'/'Ankorage' -> A526).
    Known limitation vs. Double Metaphone: Soundex is anglocentric and
    only keys off the first letter, so it misses same-sounding words that
    start differently ('Kelly'/'Celly'). Accepted, not overlooked."""
    letters = [ch for ch in word.casefold() if ch.isalpha()]
    if not letters:
        return ""

    first = letters[0]
    encoded = [_SOUNDEX_CODES.get(ch, "") for ch in letters]

    # Collapse runs of the same code, including one that starts at the
    # first letter (its digit is dropped, but it still suppresses a
    # duplicate immediately after it).
    result = ""
    previous = encoded[0]
    for code in encoded[1:]:
        if code and code != previous:
            result += code
        # Vowels (empty code) reset the run; h/w do not, but Soundex's
        # h/w rule is a refinement this deliberately-simple version skips.
        previous = code
        if len(result) == 3:
            break

    return (first.upper() + result).ljust(4, "0")


def _token_set_similarity(a: str, b: str) -> float:
    """Jaccard overlap of word sets — order-independent, so 'Los Angeles
    International' and 'International Los Angeles' score 1.0 where a
    character metric would punish the reordering."""
    tokens_a, tokens_b = set(a.split()), set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _token_containment(query: str, candidate: str) -> float:
    """For each QUERY token, its best Jaro-Winkler match among the
    candidate's tokens, averaged with each token weighted by its own
    length.

    Length-weighting is the load-bearing part. A short query token that
    matches perfectly ('alpha' inside 'the alpha option') should score
    high; a shared stopword ('the') should contribute almost nothing,
    because three characters of agreement is weak evidence of identity
    while seven characters is strong. This deliberately avoids a
    hard-coded stopword list — those are per-language and per-domain, and
    would be one more thing to get wrong on an unfamiliar dataset.

    Asymmetric on purpose: it asks "is the query accounted for by the
    candidate", not the reverse, so a short query still matches a long
    official name without being penalised for the extra words.
    """
    query_tokens = query.split()
    candidate_tokens = candidate.split()
    if not query_tokens or not candidate_tokens:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    for qt in query_tokens:
        best = max(jaro_winkler_similarity(qt, ct) for ct in candidate_tokens)
        weight = float(len(qt))
        weighted_sum += best * weight
        total_weight += weight

    return weighted_sum / total_weight if total_weight else 0.0


def score_pair(query: str, candidate_text: str) -> tuple[float, tuple[tuple[str, float], ...]]:
    """Blend the four signals into one confidence, and return the
    per-signal breakdown alongside it — same discipline as scoring.py's
    ComponentBreakdown: never hand back a bare number nobody can explain.
    A candidate that scores 0.71 should be answerable with WHICH signal
    got it there."""
    q, c = _normalize(query), _normalize(candidate_text)
    if not q or not c:
        return 0.0, (
            ("token_containment", 0.0),
            ("jaro_winkler", 0.0),
            ("token_set", 0.0),
            ("phonetic", 0.0),
        )

    containment = _token_containment(q, c)
    jw = jaro_winkler_similarity(q, c)
    token_set = _token_set_similarity(q, c)
    phonetic = 1.0 if soundex(q.replace(" ", "")) == soundex(c.replace(" ", "")) else 0.0

    blended = (
        _W_TOKEN_CONTAINMENT * containment
        + _W_JARO_WINKLER * jw
        + _W_TOKEN_SET * token_set
        + _W_PHONETIC * phonetic
    )
    signals = (
        ("token_containment", round(containment, 4)),
        ("jaro_winkler", round(jw, 4)),
        ("token_set", round(token_set, 4)),
        ("phonetic", phonetic),
    )
    return blended, signals


def resolve(query: str, catalog: Mapping[str, Sequence[str]], top_k: int = 5) -> ResolutionResult:
    """`catalog` maps item_id -> every text that should count as a name
    for it (its id, display name, aliases — the caller decides scope).
    Returns candidates clearing MIN_RELEVANCE, sorted descending, plus a
    `decisive` verdict.

    `decisive` requires BOTH halves of the bar:
      - the top candidate is a solid match on its own
        (confidence >= DECISIVE_MIN_CONFIDENCE), and
      - it is clearly ahead of the runner-up
        (top - runner_up >= DECISIVE_MIN_GAP).

    Either half failing means "do not act on this without stating the
    assumption or asking." A high score with a close runner-up is the
    'LA' case — LAX vs. the basin, several readings all plausible. A lone
    low score with no competition is 'nothing here really matches', which
    is not confident just because it is unopposed. Zero candidates is
    never decisive by construction: an empty top-1 has no confidence to
    check.
    """
    scored: list[EntityCandidate] = []
    for item_id, texts in catalog.items():
        best: EntityCandidate | None = None
        for text in texts:
            confidence, signals = score_pair(query, text)
            if best is None or confidence > best.confidence:
                best = EntityCandidate(
                    item_id=item_id, matched_text=text, confidence=round(confidence, 4), signals=signals
                )
        if best is not None and best.confidence >= MIN_RELEVANCE:
            scored.append(best)

    scored.sort(key=lambda c: (-c.confidence, c.item_id))
    top: tuple[EntityCandidate, ...] = tuple(scored[:top_k])

    if len(top) == 0:
        decisive = False
    else:
        runner_up = top[1].confidence if len(top) > 1 else 0.0
        decisive = top[0].confidence >= DECISIVE_MIN_CONFIDENCE and (top[0].confidence - runner_up) >= DECISIVE_MIN_GAP

    return ResolutionResult(query=query, candidates=top, decisive=decisive)
