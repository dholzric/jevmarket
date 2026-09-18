"""Hard spend gates live in the runner, not in a person's memory."""

import pytest

from jevmarket.jev.budget import BudgetExceeded, Pricing, SpendGate


def test_calls_are_counted():
    gate = SpendGate(max_calls=10)
    gate.charge(input_tokens=100, output_tokens=20)
    assert gate.calls == 1


def test_exceeding_the_call_cap_raises():
    gate = SpendGate(max_calls=2)
    gate.charge(100, 20)
    gate.charge(100, 20)
    with pytest.raises(BudgetExceeded):
        gate.charge(100, 20)


def test_cost_is_computed_from_pricing():
    gate = SpendGate(max_calls=100, pricing=Pricing(input_per_mtok=3.0, output_per_mtok=15.0))
    gate.charge(input_tokens=1_000_000, output_tokens=1_000_000)
    assert gate.spent_usd == pytest.approx(18.0)


def test_exceeding_the_dollar_cap_raises():
    gate = SpendGate(max_usd=1.0, pricing=Pricing(input_per_mtok=3.0, output_per_mtok=15.0))
    with pytest.raises(BudgetExceeded):
        gate.charge(input_tokens=1_000_000, output_tokens=0)


def test_the_call_that_breaches_the_cap_is_still_recorded():
    """You spent it. The ledger must say so even though the run stops."""
    gate = SpendGate(max_usd=1.0, pricing=Pricing(3.0, 15.0))
    with pytest.raises(BudgetExceeded):
        gate.charge(1_000_000, 0)
    assert gate.spent_usd == pytest.approx(3.0)
    assert gate.calls == 1


def test_unknown_pricing_leaves_cost_unmeasured_but_still_gates_on_calls():
    gate = SpendGate(max_calls=1, pricing=None)
    gate.charge(100, 20)
    assert gate.spent_usd is None
    with pytest.raises(BudgetExceeded):
        gate.charge(100, 20)


def test_a_dollar_cap_without_pricing_is_rejected_at_construction():
    """Silently failing to enforce a spend cap is the worst outcome here."""
    with pytest.raises(ValueError):
        SpendGate(max_usd=5.0, pricing=None)


def test_cached_calls_are_free_and_do_not_consume_the_gate():
    gate = SpendGate(max_calls=1)
    gate.note_cache_hit()
    gate.note_cache_hit()
    gate.charge(100, 20)
    assert gate.calls == 1
    assert gate.cache_hits == 2


def test_remaining_reports_headroom():
    gate = SpendGate(max_calls=10, max_usd=5.0, pricing=Pricing(3.0, 15.0))
    gate.charge(1_000_000, 0)
    assert gate.remaining_calls == 9
    assert gate.remaining_usd == pytest.approx(2.0)


def test_summary_reports_the_whole_ledger():
    gate = SpendGate(max_calls=10, max_usd=5.0, pricing=Pricing(3.0, 15.0))
    gate.note_cache_hit()
    gate.charge(1_000_000, 0)
    summary = gate.summary()
    assert summary["live_calls"] == 1
    assert summary["cache_hits"] == 1
    assert summary["spent_usd"] == pytest.approx(3.0)
