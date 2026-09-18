"""The zero-intelligence baseline on the common action space."""

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


def test_zi_confidence_is_uninformative_by_construction():
    """The null model for the calibration outcome: it always says 0.5."""
    zi = ZeroIntelligence("t0", seed=3)
    assert all(zi.decide(observation(t)).confidence == 0.5 for t in range(200))


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
