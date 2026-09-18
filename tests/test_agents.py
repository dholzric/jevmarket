"""The zero-intelligence baseline on the common action space."""

import pytest

from jevmarket.agents import Observation, ZeroIntelligence
from jevmarket.decision import Action, Decision


def observation(period=0, signal=100.0, private_value=100.0):
    return Observation(
        period=period,
        signal=signal,
        private_value=private_value,
        best_bid=None,
        best_ask=None,
        last_price=None,
        cash=10_000,
        inventory=50,
        available_cash=10_000,
        available_inventory=50,
    )


def test_zi_returns_a_valid_decision():
    zi = ZeroIntelligence(trader_id="t0", seed=1)
    decision = zi.decide(observation())
    assert isinstance(decision, Decision)
    assert decision.action in tuple(Action)


def test_zi_is_reproducible_under_a_seed():
    a = [ZeroIntelligence("t0", seed=5).decide(observation(t)) for t in range(50)]
    b = [ZeroIntelligence("t0", seed=5).decide(observation(t)) for t in range(50)]
    assert a == b


def test_different_seeds_give_different_decision_streams():
    a = [ZeroIntelligence("t0", seed=5).decide(observation(t)) for t in range(50)]
    b = [ZeroIntelligence("t0", seed=6).decide(observation(t)) for t in range(50)]
    assert a != b


def test_zi_uses_the_whole_action_space():
    zi = ZeroIntelligence("t0", seed=2)
    actions = {zi.decide(observation(t)).action for t in range(300)}
    assert actions == set(Action)


def test_zi_reports_its_own_policy_as_its_distribution():
    """Every arm carries a real distribution over {buy, sell, pass}. ZI's is its
    fixed randomisation, which is what makes it the calibration null."""
    zi = ZeroIntelligence("t0", seed=3)
    distributions = {
        tuple(sorted(zi.decide(observation(t)).action_probabilities.items()))
        for t in range(200)
    }
    assert len(distributions) == 1, "ZI's policy must not vary with the state"
    assert sum(dict(next(iter(distributions))).values()) == pytest.approx(1.0)


def test_zi_has_no_view_on_whether_the_signal_is_already_priced():
    zi = ZeroIntelligence("t0", seed=3)
    assert all(zi.decide(observation(t)).already_priced == 0.5 for t in range(200))


def test_zi_confidence_is_the_mass_on_the_action_it_took():
    zi = ZeroIntelligence("t0", seed=3)
    for t in range(50):
        decision = zi.decide(observation(t))
        assert decision.confidence == pytest.approx(
            decision.action_probabilities[decision.action.value]
        )


def test_zi_ignores_the_book_entirely():
    """Same seed and period, different book -> same decision."""
    rich_book = Observation(
        period=4, signal=100.0, private_value=100.0,
        best_bid=99, best_ask=101, last_price=100,
        cash=10_000, inventory=50, available_cash=10_000, available_inventory=50,
    )
    assert (
        ZeroIntelligence("t0", seed=8).decide(rich_book)
        == ZeroIntelligence("t0", seed=8).decide(observation(period=4))
    )
