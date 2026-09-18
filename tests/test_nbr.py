"""Noisy best-response: the informed, symmetric benchmark.

NBR matters most as a symmetry control. It best-responds to the book with
logit noise, and because its utility calculation treats the two sides
identically, a buy at edge +x and a sell at edge -x must get exactly the same
probability. That is the property Jev loses under the original wording, and it
is what makes NBR the right thing to measure Jev against.
"""

import pytest

from jevmarket.agents import Observation
from jevmarket.agents.nbr import NoisyBestResponse
from jevmarket.decision import Action


def observation(private_value, best_bid=99, best_ask=101, signal=None):
    return Observation(
        period=0,
        signal=private_value if signal is None else signal,
        private_value=private_value,
        best_bid=best_bid,
        best_ask=best_ask,
        last_price=100,
        cash=100_000,
        inventory=50,
        available_cash=100_000,
        available_inventory=50,
    )


def test_returns_a_valid_decision_with_a_real_distribution():
    decision = NoisyBestResponse("t0").decide(observation(104))
    assert decision.action in tuple(Action)
    assert set(decision.action_probabilities) == {"buy", "sell", "pass"}
    assert sum(decision.action_probabilities.values()) == pytest.approx(1.0)
    assert 0.0 <= decision.aggressiveness <= 1.0


def test_buys_when_the_good_is_clearly_cheap():
    decision = NoisyBestResponse("t0", temperature=0.2).decide(observation(115))
    assert decision.action is Action.BUY


def test_sells_when_the_good_is_clearly_dear():
    decision = NoisyBestResponse("t0", temperature=0.2).decide(observation(85))
    assert decision.action is Action.SELL


def test_passes_when_there_is_no_edge():
    decision = NoisyBestResponse("t0", temperature=0.2).decide(observation(100))
    assert decision.action is Action.PASS


def test_is_exactly_symmetric_between_the_two_sides():
    """The property that makes NBR the benchmark: equal |edge| -> equal conviction."""
    brain = NoisyBestResponse("t0", temperature=1.0)
    for edge in (2, 4, 8, 12):
        up = brain.decide(observation(100 + edge)).action_probabilities
        down = brain.decide(observation(100 - edge)).action_probabilities
        assert up["buy"] == pytest.approx(down["sell"], abs=1e-9)
        assert up["pass"] == pytest.approx(down["pass"], abs=1e-9)


def test_aggressiveness_rises_with_the_size_of_the_edge():
    brain = NoisyBestResponse("t0", temperature=0.5)
    levels = [brain.decide(observation(100 + e)).aggressiveness for e in (2, 6, 12)]
    assert levels == sorted(levels)


def test_low_temperature_is_nearly_deterministic():
    decision = NoisyBestResponse("t0", temperature=0.01).decide(observation(112))
    assert max(decision.action_probabilities.values()) > 0.95


def test_high_temperature_approaches_indifference():
    decision = NoisyBestResponse("t0", temperature=1_000.0).decide(observation(112))
    assert max(decision.action_probabilities.values()) < 0.45


def test_never_prefers_a_side_that_would_lose_money():
    """quote_price clamps the price, but NBR must not want the losing side either."""
    brain = NoisyBestResponse("t0", temperature=0.2)
    assert brain.decide(observation(90)).action_probabilities["buy"] < 0.1
    assert brain.decide(observation(110)).action_probabilities["sell"] < 0.1


def test_handles_an_empty_book_without_deadlocking():
    """The cold-start case that made the Jev arms pass forever."""
    decision = NoisyBestResponse("t0", temperature=0.5).decide(
        observation(104, best_bid=None, best_ask=None, signal=100)
    )
    assert decision.action is not Action.PASS


def test_already_priced_peaks_when_the_signal_matches_the_book():
    brain = NoisyBestResponse("t0")
    at_mid = brain.decide(observation(100, signal=100)).already_priced
    far = brain.decide(observation(100, signal=115)).already_priced
    assert at_mid > far
    assert 0.0 <= at_mid <= 1.0


def test_is_deterministic_given_the_same_observation():
    brain = NoisyBestResponse("t0", temperature=0.5)
    first = brain.decide(observation(107))
    assert all(brain.decide(observation(107)) == first for _ in range(5))
