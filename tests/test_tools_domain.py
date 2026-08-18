"""Domain-model tests — the "unmet demand" example that lives in
app/tools.py, NOT in app/analytics.py.

The split matters: app/analytics.py holds the generic contract every
modelled metric must satisfy (tested in tests/test_analytics.py), while
the formula, its constants, and its causal reasoning are this
assignment's domain code. Replacing the domain means rewriting these
tests and tools.py's model — and leaving analytics.py alone.
"""
from __future__ import annotations

import pytest

from app.tools import (
    CAPACITY_CONSTRAINED_UTILIZATION,
    WAITLIST_CONVERSION_RATE,
    estimate_unmet_demand,
)


def test_unmet_demand_applies_waitlist_discount():
    result = estimate_unmet_demand(served_units=120, capacity_units=130, turnaways=25, waitlist=18)
    assert result.value == pytest.approx(25 + 18 * WAITLIST_CONVERSION_RATE)


def test_unmet_demand_factor_magnitudes_sum_to_the_value():
    """The 'why' must reconstruct the 'what' exactly — if factors don't
    sum to the total, the explanation is decorative."""
    result = estimate_unmet_demand(served_units=120, capacity_units=130, turnaways=25, waitlist=18)
    assert sum(f.magnitude for f in result.factors) == pytest.approx(result.value)


def test_unmet_demand_factor_shares_sum_to_one():
    result = estimate_unmet_demand(served_units=120, capacity_units=130, turnaways=25, waitlist=18)
    assert sum(f.share_of_total for f in result.factors) == pytest.approx(1.0)


def test_unmet_demand_high_utilization_gets_higher_confidence():
    """Utilization is what makes the number credible rather than merely
    arithmetic — same inputs, different capacity, different claim."""
    constrained = estimate_unmet_demand(served_units=129, capacity_units=130, turnaways=25, waitlist=18)
    assert constrained.confidence == "medium"
    assert "lower bound" in constrained.caveat.lower()


def test_unmet_demand_low_utilization_drops_confidence_and_says_why():
    """The hostile question — 'is that unmet demand or just a capacity
    ceiling?' — answered structurally: with capacity to spare, the same
    arithmetic no longer supports the same claim."""
    slack = estimate_unmet_demand(served_units=100, capacity_units=180, turnaways=25, waitlist=18)
    assert slack.confidence == "low"
    assert "below" in slack.caveat.lower()


def test_unmet_demand_utilization_threshold_boundary():
    """Pin the threshold itself so a silent change is caught."""
    exactly_at = estimate_unmet_demand(
        served_units=CAPACITY_CONSTRAINED_UTILIZATION * 100, capacity_units=100, turnaways=5, waitlist=0
    )
    assert exactly_at.confidence == "medium"  # boundary is inclusive


def test_unmet_demand_value_is_identical_regardless_of_confidence():
    """Confidence changes the CLAIM, not the arithmetic. Same turnaways
    and waitlist produce the same number either way."""
    high = estimate_unmet_demand(served_units=129, capacity_units=130, turnaways=25, waitlist=18)
    low = estimate_unmet_demand(served_units=100, capacity_units=180, turnaways=25, waitlist=18)
    assert high.value == pytest.approx(low.value)


def test_unmet_demand_zero_signals_gives_zero_without_crashing():
    result = estimate_unmet_demand(served_units=50, capacity_units=100, turnaways=0, waitlist=0)
    assert result.value == 0.0
    assert all(f.share_of_total == 0.0 for f in result.factors)  # no divide-by-zero


def test_unmet_demand_negative_inputs_are_clamped_not_subtracted():
    """A negative turnaway count is bad data, not negative demand — it
    must not silently reduce the estimate."""
    result = estimate_unmet_demand(served_units=50, capacity_units=100, turnaways=-10, waitlist=10)
    assert result.value == pytest.approx(10 * WAITLIST_CONVERSION_RATE)


def test_unmet_demand_zero_capacity_does_not_crash():
    result = estimate_unmet_demand(served_units=10, capacity_units=0, turnaways=5, waitlist=0)
    assert result.value == pytest.approx(5.0)
    assert result.confidence == "low"  # NaN utilization must not read as "constrained"


def test_unmet_demand_always_carries_assumptions():
    """A modelled number without its assumptions is indistinguishable
    from a measured one — that's the failure this guards."""
    result = estimate_unmet_demand(served_units=120, capacity_units=130, turnaways=25, waitlist=18)
    assert len(result.assumptions) >= 3
    assert any("lower bound" in a.lower() for a in result.assumptions)
