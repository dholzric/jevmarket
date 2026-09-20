"""Independent calling: no cache, every response archived in call order.

Prereg 10h replays the confirmatory market with a fresh live call per trader
decision. The content-addressed cache is deliberately not used -- reading it
would memoise, writing it would overwrite the entries the memoised runs replay
from. Reproducibility comes instead from an ordered per-run archive that a
replay transport serves back, refusing any request that does not match.
"""

import threading

import pytest

from jevmarket.agents import Observation
from jevmarket.fundamental import MatchedJumpFundamental, Signal
from jevmarket.jev.archive import CallLog, ReplayExhausted, ReplayMismatch, ReplayTransport
from jevmarket.jev.budget import SpendGate
from jevmarket.jev.client import JevClient
from jevmarket.jev.mock import MockTransport
from jevmarket.jev.questions import build_request
from jevmarket.simulation import RunConfig, run


def observation(period=0, private_value=104.3, signal=104.0, best_bid=99, best_ask=101):
    return Observation(
        period=period, signal=signal, private_value=private_value,
        best_bid=best_bid, best_ask=best_ask, last_price=100,
        cash=10_000, inventory=50, available_cash=10_000, available_inventory=50,
    )


class CountingTransport:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def send(self, request):
        self.calls += 1
        return self.inner.send(request)


def market(client, seed=3):
    return RunConfig(
        n_traders=4, periods=30, seed=seed, arm="jev_argmax", burn_in_periods=3,
        fundamental=MatchedJumpFundamental(initial=100.0, jump_size=10.0,
                                           period_gap=10, seed=1000 + seed),
        signal=Signal(seed=seed), jev_client=client,
    )


# --- archiving --------------------------------------------------------------


def test_an_archiving_client_records_every_live_call_in_order():
    log = CallLog()
    transport = CountingTransport(MockTransport(seed=1))
    client = JevClient(transport, archive=log)

    observations = [observation(period=0), observation(period=0), observation(private_value=120)]
    for obs in observations:
        client.decide(obs)

    assert transport.calls == 3, "no cache: an identical state is a fresh call"
    assert [e["cache_key"] for e in log.entries] == [
        build_request(o).cache_key for o in observations
    ]


def test_an_archive_round_trips_through_gzipped_json(tmp_path):
    log = CallLog()
    client = JevClient(MockTransport(seed=1), archive=log)
    client.decide(observation())
    client.decide(observation(private_value=90))

    path = tmp_path / "run.json.gz"
    log.save(path)
    loaded = CallLog.load(path)

    assert loaded.entries == log.entries


# --- replay -----------------------------------------------------------------


def test_replaying_an_archive_reproduces_a_run_without_the_wire():
    log = CallLog()
    live = run(market(JevClient(MockTransport(seed=1), archive=log)))

    wire = CountingTransport(MockTransport(seed=1))
    replayed = run(market(JevClient(ReplayTransport(log), archive=None)))

    assert wire.calls == 0
    assert replayed.trade_prices == live.trade_prices
    assert [d.decision.action for d in replayed.decisions] == [
        d.decision.action for d in live.decisions
    ]


def test_replay_refuses_a_request_that_does_not_match_the_archive():
    log = CallLog()
    JevClient(MockTransport(seed=1), archive=log).decide(observation())

    with pytest.raises(ReplayMismatch):
        JevClient(ReplayTransport(log)).decide(observation(private_value=150))


def test_replay_refuses_to_invent_a_response_past_the_end_of_the_archive():
    log = CallLog()
    JevClient(MockTransport(seed=1), archive=log).decide(observation())

    client = JevClient(ReplayTransport(log))
    client.decide(observation())
    with pytest.raises(ReplayExhausted):
        client.decide(observation())


# --- the gate under concurrency ---------------------------------------------


def test_the_spend_gate_counts_correctly_when_runs_charge_it_from_many_threads():
    """Prereg 10h runs seeds in parallel against one shared gate."""
    gate = SpendGate(max_calls=10_000_000)
    per_thread = 200_000

    def hammer():
        for _ in range(per_thread):
            gate.charge(3, 1)

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert gate.calls == 4 * per_thread
    assert gate.input_tokens == 3 * 4 * per_thread
