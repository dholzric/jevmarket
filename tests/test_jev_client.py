"""The Jev client: state rendering, caching, budget, and the two decode arms.

The arms that matter here: `jev_argmax` takes the choice Jev returned,
`jev_sample` draws from the same `probabilities` map. Both read ONE response,
so for a given observation the pair costs one API call and H5 is a within-call
comparison with no between-call noise. Across a whole run the saving is small
(~3%), because the arms take different actions and diverge into different
books -- see test_simulation.py.
"""

import pytest

from jevmarket.agents import Observation
from jevmarket.agents.jev import JevArgmax, JevSample
from jevmarket.decision import Action
from jevmarket.jev.budget import BudgetExceeded, SpendGate
from jevmarket.jev.cache import DecisionCache
from jevmarket.jev.client import JevClient
from jevmarket.jev.mock import MockTransport
from jevmarket.jev.questions import render_state, build_request


def observation(period=0, private_value=104.3, signal=104.0, best_bid=99, best_ask=101):
    return Observation(
        period=period,
        signal=signal,
        private_value=private_value,
        best_bid=best_bid,
        best_ask=best_ask,
        last_price=100,
        cash=10_000,
        inventory=50,
        available_cash=10_000,
        available_inventory=50,
    )


class CountingTransport:
    """Wraps a transport and counts how many times the wire was actually used."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def send(self, request):
        self.calls += 1
        return self.inner.send(request)


# --- what Jev is shown ------------------------------------------------------


def test_state_carries_the_book_the_private_value_and_the_signal():
    state = render_state(observation())
    assert state["best_bid"] == 99
    assert state["best_ask"] == 101
    assert state["spread"] == 2
    assert state["your_private_value"] == 104
    assert state["your_signal"] == 104


def test_state_matches_the_field_list_frozen_in_the_schema():
    from jevmarket.decision import load_schema

    assert set(render_state(observation())) == set(load_schema()["state_fields"])


def test_cash_and_inventory_are_deliberately_absent_from_the_state():
    """They change after every fill; including them made every key unique and
    collapsed the cache hit rate from 31% to 1%. Code owns the budget."""
    state = render_state(observation())
    for banned in ("your_cash", "your_units", "cash_you_can_spend", "units_you_can_sell"):
        assert banned not in state


def test_state_rounds_to_whole_ticks_so_identical_situations_share_a_cache_entry():
    a = render_state(observation(private_value=104.3, signal=104.0))
    b = render_state(observation(private_value=104.4, signal=104.1))
    assert a == b


def test_state_excludes_the_period_number():
    """The period is not decision-relevant, and leaving it out multiplies reuse."""
    assert render_state(observation(period=3)) == render_state(observation(period=900))


def test_an_empty_book_is_rendered_explicitly_not_dropped():
    state = render_state(observation(best_bid=None, best_ask=None))
    assert state["best_bid"] is None
    assert state["best_ask"] is None
    assert state["spread"] is None


def test_the_request_carries_the_frozen_questions_verbatim():
    from jevmarket.decision import load_schema

    request = build_request(observation())
    assert request.questions == load_schema()["questions"]
    assert request.model == "jev-latest"
    assert request.schema_version == "v1"


def test_the_request_body_is_what_typesafe_expects():
    body = build_request(observation()).body()
    assert set(body) == {"model", "state", "questions"}
    assert set(body["questions"]) == {"action", "aggressiveness", "already_priced"}


# --- the client -------------------------------------------------------------


def test_the_client_turns_a_response_into_a_decision():
    client = JevClient(MockTransport(seed=1))
    decision, response = client.decide(observation())
    assert decision.action in tuple(Action)
    assert 0.0 <= decision.aggressiveness <= 1.0
    assert response.from_cache is False


def test_a_repeated_situation_is_served_from_cache(tmp_path):
    transport = CountingTransport(MockTransport(seed=1))
    client = JevClient(transport, cache=DecisionCache(tmp_path))

    first, _ = client.decide(observation(period=0))
    second, response = client.decide(observation(period=7))

    assert transport.calls == 1, "identical state should not hit the wire twice"
    assert response.from_cache is True
    assert first.action is second.action


def test_cache_hits_do_not_consume_the_spend_gate(tmp_path):
    transport = CountingTransport(MockTransport(seed=1))
    gate = SpendGate(max_calls=1)
    client = JevClient(transport, cache=DecisionCache(tmp_path), budget=gate)

    for period in range(10):
        client.decide(observation(period=period))

    assert transport.calls == 1
    assert gate.calls == 1
    assert gate.cache_hits == 9


def test_the_spend_gate_stops_a_runaway_sweep(tmp_path):
    client = JevClient(MockTransport(seed=1), budget=SpendGate(max_calls=2))
    client.decide(observation(private_value=104))
    client.decide(observation(private_value=120))
    with pytest.raises(BudgetExceeded):
        client.decide(observation(private_value=130))


def test_usage_is_charged_to_the_gate():
    gate = SpendGate(max_calls=10)
    JevClient(MockTransport(seed=1), budget=gate).decide(observation())
    assert gate.input_tokens > 0


# --- the two arms -----------------------------------------------------------


def test_argmax_takes_the_action_jev_chose():
    client = JevClient(MockTransport(seed=1))
    brain = JevArgmax(trader_id="t0", client=client)
    decision = brain.decide(observation())
    best = max(decision.action_probabilities, key=decision.action_probabilities.get)
    assert decision.action.value == best


def test_argmax_is_deterministic():
    client = JevClient(MockTransport(seed=1))
    brain = JevArgmax(trader_id="t0", client=client)
    assert {brain.decide(observation()).action for _ in range(20)} == {
        brain.decide(observation()).action
    }


def test_sample_draws_from_the_same_distribution_jev_returned():
    client = JevClient(MockTransport(seed=1))
    brain = JevSample(trader_id="t0", client=client, seed=3)
    actions = {brain.decide(observation(period=t)).action for t in range(400)}
    assert len(actions) > 1, "sampling arm never varied; it is just argmax"


def test_sample_keeps_the_distribution_it_sampled_from():
    client = JevClient(MockTransport(seed=1))
    brain = JevSample(trader_id="t0", client=client, seed=3)
    decision = brain.decide(observation())
    assert decision.confidence == pytest.approx(
        decision.action_probabilities[decision.action.value]
    )


def test_sample_is_reproducible_under_a_seed():
    def stream(seed):
        client = JevClient(MockTransport(seed=1))
        brain = JevSample(trader_id="t0", client=client, seed=seed)
        return [brain.decide(observation(period=t)).action for t in range(60)]

    assert stream(3) == stream(3)
    assert stream(3) != stream(4)


def test_both_arms_can_share_one_call(tmp_path):
    """Per observation, the pair is one call. This is what makes H5 a
    within-call comparison; it is NOT a halving of run cost."""
    transport = CountingTransport(MockTransport(seed=1))
    cache = DecisionCache(tmp_path)
    shared = JevClient(transport, cache=cache)

    JevArgmax(trader_id="t0", client=shared).decide(observation())
    JevSample(trader_id="t0", client=shared, seed=3).decide(observation())

    assert transport.calls == 1


def test_the_mock_never_returns_something_the_contract_rejects():
    client = JevClient(MockTransport(seed=9))
    for value in range(80, 130):
        decision, _ = client.decide(observation(private_value=value, signal=value))
        assert sum(decision.action_probabilities.values()) == pytest.approx(1.0)
        assert 0.0 <= decision.already_priced <= 1.0
