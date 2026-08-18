"""Unit tests for app/entity_resolution.py — the pure, zero-I/O fuzzy
matcher. Like test_scoring.py these must pass with no network, no API
key, and no LLM."""
from __future__ import annotations

import pytest

from app.entity_resolution import (
    DECISIVE_MIN_CONFIDENCE,
    MIN_RELEVANCE,
    jaro_similarity,
    jaro_winkler_similarity,
    resolve,
    score_pair,
    soundex,
)

CATALOG = {
    "option_a": ["option_a", "Option A", "Alpha", "the alpha option"],
    "option_b": ["option_b", "Option B", "Bravo", "the bravo option"],
    "option_c": ["option_c", "Option C", "Charlie", "the charlie option"],
}

# For the short-code edit-distance fallback: upper-case 3-letter codes plus
# a lower-case short name, mirroring the real catalog's split between
# locid/iata_code aliases (always upper-case) and municipality-derived
# aliases that happen to be short (never upper-case).
CODE_CATALOG = {
    "item_lgb": ["LGB", "Long Beach Airport"],
    "item_abc": ["ABC", "Alphabet Field"],
    "item_abd": ["ABD", "Alphabet Downtown"],
    "item_reno": ["Reno", "Reno Municipal Airport"],
}


# ── Jaro / Jaro-Winkler ──────────────────────────────────────────────────
def test_jaro_identical_strings_is_one():
    assert jaro_similarity("martha", "martha") == 1.0


def test_jaro_no_shared_characters_is_zero():
    assert jaro_similarity("abc", "xyz") == 0.0


def test_jaro_known_reference_value():
    """MARTHA/MARHTA is the canonical worked example in the literature:
    one transposition, Jaro = 0.9444."""
    assert jaro_similarity("martha", "marhta") == pytest.approx(0.9444, abs=1e-4)


def test_jaro_winkler_boosts_shared_prefix_above_plain_jaro():
    plain = jaro_similarity("martha", "marhta")
    boosted = jaro_winkler_similarity("martha", "marhta")
    assert boosted > plain
    assert boosted == pytest.approx(0.9611, abs=1e-4)


def test_jaro_winkler_no_shared_prefix_equals_jaro():
    """With no common prefix the boost term is zero, so JW degrades
    exactly to Jaro — the prefix bonus is additive, not baked in."""
    assert jaro_winkler_similarity("abcdef", "zbcdef") == pytest.approx(jaro_similarity("abcdef", "zbcdef"))


def test_jaro_empty_string_is_zero_not_a_crash():
    assert jaro_similarity("", "abc") == 0.0
    assert jaro_similarity("abc", "") == 0.0


# ── Soundex ─────────────────────────────────────────────────────────────
def test_soundex_known_reference_values():
    assert soundex("Robert") == "R163"
    assert soundex("Rupert") == "R163"  # classic same-code pair
    assert soundex("Tymczak") == "T522"


def test_soundex_catches_phonetic_misspelling():
    """The case this signal exists for: a plausible misspelling that
    character metrics score lower but which sounds identical."""
    assert soundex("Anchorage") == soundex("Ankorage")


def test_soundex_is_padded_to_four_characters():
    assert len(soundex("Lee")) == 4
    assert soundex("Lee") == "L000"


def test_soundex_empty_input_returns_empty_not_a_crash():
    assert soundex("") == ""
    assert soundex("123") == ""


def test_soundex_known_limitation_different_first_letter():
    """Documented weakness vs. Double Metaphone, asserted so it's a known
    property rather than a surprise: Soundex keys off the first letter,
    so same-sounding words starting differently do NOT collide."""
    assert soundex("Kelly") != soundex("Celly")


# ── score_pair blending ─────────────────────────────────────────────────
def test_score_pair_exact_match_scores_near_one():
    confidence, _ = score_pair("Alpha", "Alpha")
    assert confidence == pytest.approx(1.0)


def test_score_pair_is_case_and_punctuation_insensitive():
    a, _ = score_pair("option_a", "OPTION A")
    b, _ = score_pair("option a", "option-a")
    assert a == pytest.approx(1.0)
    assert b == pytest.approx(1.0)


def test_score_pair_returns_per_signal_breakdown():
    """Same 'explain, never assert' habit as scoring.py's components —
    the blended number must always be decomposable."""
    _, signals = score_pair("Alpha", "Alpha")
    assert dict(signals).keys() == {"token_containment", "jaro_winkler", "token_set", "phonetic"}


def test_score_pair_token_set_ignores_word_order():
    """A pure character metric punishes reordering; the token-set signal
    is what rescues it."""
    _, signals = score_pair("los angeles international", "international los angeles")
    assert dict(signals)["token_set"] == pytest.approx(1.0)


def test_score_pair_unrelated_strings_score_low():
    confidence, _ = score_pair("zzzzz", "Alpha")
    assert confidence < MIN_RELEVANCE


# ── resolve() ───────────────────────────────────────────────────────────
def test_resolve_exact_id_is_decisive():
    result = resolve("option_a", CATALOG)
    assert result.decisive is True
    assert result.candidates[0].item_id == "option_a"
    assert result.candidates[0].confidence >= DECISIVE_MIN_CONFIDENCE


def test_resolve_alias_is_decisive():
    result = resolve("Charlie", CATALOG)
    assert result.decisive is True
    assert result.candidates[0].item_id == "option_c"


def test_resolve_no_match_returns_empty_and_not_decisive():
    """Zero matches is a normal fuzzy-search outcome, not an exception —
    deliberately unlike fetch_item_metrics's UnknownItemError, because
    being handed a nonexistent id IS a bug while finding nothing for a
    vague phrase is not."""
    result = resolve("quantum tunnelling diode", CATALOG)
    assert result.candidates == ()
    assert result.decisive is False


def test_resolve_ambiguous_query_is_not_decisive():
    """'Option' matches all three entries about equally — high-ish score,
    no gap. This is the 'LA' case: confident-looking but genuinely
    ambiguous, and the gap half of the bar is what catches it."""
    result = resolve("Option", CATALOG)
    assert len(result.candidates) > 1
    assert result.decisive is False


def test_resolve_ranks_candidates_by_confidence_descending():
    result = resolve("Option B", CATALOG)
    confidences = [c.confidence for c in result.candidates]
    assert confidences == sorted(confidences, reverse=True)
    assert result.candidates[0].item_id == "option_b"


def test_resolve_is_repeatable():
    """No hidden randomness or dict-ordering dependence — same property
    rank_items guarantees."""
    r1 = resolve("Option", CATALOG)
    r2 = resolve("Option", CATALOG)
    assert [(c.item_id, c.confidence) for c in r1.candidates] == [(c.item_id, c.confidence) for c in r2.candidates]
    assert r1.decisive == r2.decisive


def test_resolve_respects_top_k():
    result = resolve("Option", CATALOG, top_k=2)
    assert len(result.candidates) <= 2


def test_resolve_reports_which_alias_matched():
    """The matched_text field is what lets the model say 'I matched on
    the alias Bravo', rather than asserting an id with no provenance."""
    result = resolve("Bravo", CATALOG)
    assert result.candidates[0].matched_text == "Bravo"


def test_resolve_one_weak_lone_candidate_is_not_decisive():
    """The floor half of the bar, isolated: a single candidate with no
    competition still isn't decisive if it's a poor match. Gap alone
    would wrongly call this decisive (nothing to compare against)."""
    catalog = {"option_a": ["Alpha"]}
    result = resolve("Alphx zzz", catalog)
    if result.candidates:
        assert result.candidates[0].confidence < DECISIVE_MIN_CONFIDENCE
        assert result.decisive is False


def test_stopword_query_does_not_outrank_a_genuine_match():
    """Regression for the calibration failure that forced the blend to be
    redesigned. The original weighting scored 'the weather in paris'
    against 'the alpha option' at 0.5420, ABOVE the genuine match
    'alpha'/'the alpha option' at 0.4825 — a shared leading stopword
    collecting both a Winkler prefix bonus and a free Jaccard hit, while
    the real match was punished for being shorter than its alias. No
    threshold can fix an ordering that wrong; the fix was adding the
    length-weighted token_containment signal."""
    genuine, _ = score_pair("alpha", "the alpha option")
    stopword_noise, _ = score_pair("the weather in paris", "the alpha option")
    assert genuine > stopword_noise


def test_surfacing_bar_sits_below_the_acting_bar():
    """MIN_RELEVANCE must stay strictly below DECISIVE_MIN_CONFIDENCE. If
    they invert, every surfaced candidate clears the confidence half of
    the decisive bar automatically and only the gap check does any work —
    a dead condition that still reads like a safeguard."""
    assert MIN_RELEVANCE < DECISIVE_MIN_CONFIDENCE


def test_resolve_empty_catalog_returns_nothing():
    result = resolve("anything", {})
    assert result.candidates == ()
    assert result.decisive is False


def test_resolve_skips_entries_with_no_names():
    """An item with an empty alias list must be skipped, not crash the
    whole resolution — ragged catalogs are as real as ragged metrics."""
    catalog = {"option_a": ["Alpha"], "option_broken": []}
    result = resolve("Alpha", catalog)
    assert [c.item_id for c in result.candidates] == ["option_a"]


# ── short-code edit-distance fallback ────────────────────────────────────
# Real bug found using the live agent (2026-08-18): 'LBG', a one-letter
# transposition of the real code 'LGB' (Long Beach), returned zero
# candidates. Below MIN_FUZZY_QUERY_LENGTH, short queries were exact-match
# only, so the Jaro-Winkler/Soundex machinery never even ran. These lock in
# the narrow fix: codes (not names) within one edit of a short query are
# still worth surfacing.
def test_resolve_transposed_code_matches_when_unambiguous():
    """The bug report itself: a single adjacent-letter swap of a real code,
    with nothing else in the catalog one edit away, resolves decisively —
    a typo'd code should behave like a correct one."""
    result = resolve("LBG", CODE_CATALOG)
    assert result.decisive is True
    assert result.candidates[0].item_id == "item_lgb"
    assert result.candidates[0].matched_text == "LGB"


def test_resolve_code_typo_is_case_insensitive():
    result = resolve("lbg", CODE_CATALOG)
    assert result.decisive is True
    assert result.candidates[0].item_id == "item_lgb"


def test_resolve_code_typo_with_two_equally_close_codes_is_not_decisive():
    """'ABX' is one edit from both ABC and ABD — genuinely ambiguous, same
    as the 'LA' case elsewhere in this file. Surfaced, not acted on."""
    result = resolve("ABX", CODE_CATALOG)
    assert result.decisive is False
    assert {c.item_id for c in result.candidates} == {"item_abc", "item_abd"}


def test_resolve_code_two_edits_away_is_not_surfaced():
    result = resolve("ZZZ", CODE_CATALOG)
    assert result.candidates == ()
    assert result.decisive is False


def test_resolve_short_name_is_not_treated_as_a_code():
    """'Reno' is a short alias but a municipality name, not a code (it
    isn't upper-case in the catalog). 'ren' — one edit away by simple
    string distance — must NOT match it; only genuine codes participate in
    the short-query fallback, or short city names would start colliding
    with unrelated codes the way 'LA' once did with Lawton/La Crosse."""
    result = resolve("ren", CODE_CATALOG)
    assert result.candidates == ()
    assert result.decisive is False


def test_resolve_short_non_code_shaped_query_still_returns_nothing():
    """A short query that isn't code-shaped (has a space) skips the
    fallback entirely rather than fuzzy-matching against codes."""
    result = resolve("a b", CODE_CATALOG)
    assert result.candidates == ()
    assert result.decisive is False
