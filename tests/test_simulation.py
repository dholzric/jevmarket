"""End-to-end: a full ZI economy must conserve, reproduce, and trade."""

from jevmarket.fundamental import Fundamental, Signal
from jevmarket.simulation import RunConfig, run


def config(**kwargs):
    base = dict(
        n_traders=20,
        periods=200,
        seed=42,
        arm="zi",
        initial_cash=100_000,
        initial_inventory=50,
        private_value_sd=5.0,
        fundamental=Fundamental(initial=100.0, jump_prob=0.02, jump_sd=8.0, seed=42),
        signal=Signal(delay=0, noise_sd=0.0, seed=42),
    )
    base.update(kwargs)
    return RunConfig(**base)


def test_a_zi_run_produces_trades():
    result = run(config())
    assert result.exchange.trade_count > 50


def test_conservation_holds_at_the_end_of_a_full_run():
    result = run(config())
    result.exchange.check_invariants()
    assert result.exchange.total_cash == 20 * 100_000
    assert result.exchange.total_inventory == 20 * 50


def test_one_fundamental_and_one_price_observation_per_period():
    result = run(config(periods=200))
    assert len(result.fundamental_path) == 200
    assert len(result.trade_prices) == 200


def test_the_run_is_reproducible_under_a_seed():
    a, b = run(config()), run(config())
    assert a.trade_prices == b.trade_prices
    assert a.fundamental_path == b.fundamental_path


def test_a_different_seed_gives_a_different_price_path():
    a, b = run(config(seed=1)), run(config(seed=2))
    assert a.trade_prices != b.trade_prices


def test_every_decision_is_logged_with_its_arm_and_period():
    result = run(config(periods=50, n_traders=10))
    assert len(result.decisions) == 50 * 10
    assert {d.arm for d in result.decisions} == {"zi"}
    assert {d.period for d in result.decisions} == set(range(50))


def test_rejected_orders_are_counted_not_raised():
    result = run(config(initial_cash=300, initial_inventory=2))
    assert result.rejections > 0
    result.exchange.check_invariants()


def test_zi_prices_track_the_fundamental_better_than_a_shuffled_control():
    """Weak sanity check: ZI-C is not informative, but its value clamp still
    ties trade prices to F_t. Pure noise would not."""
    from jevmarket.metrics import rmse_vs_fundamental

    result = run(config(periods=400, n_traders=30))
    observed = rmse_vs_fundamental(result.trade_prices, result.fundamental_path)
    shuffled = rmse_vs_fundamental(
        result.trade_prices, list(reversed(result.fundamental_path))
    )
    assert observed < shuffled


# --- the Jev arms on the same engine ----------------------------------------


def _jev_client(tmp_path=None):
    from jevmarket.jev.cache import DecisionCache
    from jevmarket.jev.client import JevClient
    from jevmarket.jev.mock import MockTransport

    cache = DecisionCache(tmp_path) if tmp_path is not None else None
    return JevClient(MockTransport(seed=1), cache=cache)


def test_a_jev_arm_runs_on_the_same_engine_and_conserves():
    result = run(config(arm="jev_argmax", jev_client=_jev_client(), periods=60, n_traders=10))
    result.exchange.check_invariants()
    assert result.exchange.trade_count > 0
    assert {d.arm for d in result.decisions} == {"jev_argmax"}


def test_the_sampling_arm_also_runs():
    result = run(config(arm="jev_sample", jev_client=_jev_client(), periods=60, n_traders=10))
    result.exchange.check_invariants()
    assert {d.arm for d in result.decisions} == {"jev_sample"}


def test_a_jev_arm_without_a_client_fails_loudly_before_spending_anything():
    import pytest

    with pytest.raises(ValueError, match="jev_client"):
        run(config(arm="jev_argmax"))


def test_every_decision_carries_a_distribution_whatever_the_arm():
    for arm in ("zi", "jev_argmax", "jev_sample"):
        result = run(config(arm=arm, jev_client=_jev_client(), periods=30, n_traders=8))
        for record in result.decisions:
            probabilities = record.decision.action_probabilities
            assert set(probabilities) == {"buy", "sell", "pass"}
            assert abs(sum(probabilities.values()) - 1.0) < 1e-3


def test_sharing_a_cache_across_arms_never_costs_more_than_separate_caches(tmp_path):
    """The honest version of the cost claim.

    One call serves both arms for a given observation, but NOT across a run:
    the arms take different actions, so they walk into different books within a
    few periods. Measured saving from sharing is around 3%, not a halving. What
    must always hold is that sharing is never worse.
    """
    from jevmarket.jev.cache import DecisionCache
    from jevmarket.jev.client import JevClient
    from jevmarket.jev.mock import MockTransport

    cache = DecisionCache(tmp_path)

    class Counting:
        def __init__(self):
            self.inner = MockTransport(seed=1)
            self.calls = 0

        def send(self, request):
            self.calls += 1
            return self.inner.send(request)

    transport = Counting()

    client = JevClient(transport, cache=cache)

    run(config(arm="jev_argmax", jev_client=client, periods=40, n_traders=10))
    after_first = transport.calls
    run(config(arm="jev_sample", jev_client=client, periods=40, n_traders=10))
    shared_total = transport.calls

    separate = Counting()
    separate_client = JevClient(separate, cache=DecisionCache(tmp_path / "other"))
    run(config(arm="jev_sample", jev_client=separate_client, periods=40, n_traders=10))

    assert after_first > 0
    assert shared_total <= after_first + separate.calls


def test_dropping_account_fields_from_the_state_is_what_makes_the_cache_work(tmp_path):
    """Regression guard on a measured 30x improvement.

    Putting cash/inventory back in the state would silently take the hit rate
    from ~31% to ~1% and quietly multiply the cost of every sweep.
    """
    from jevmarket.jev.cache import DecisionCache
    from jevmarket.jev.client import JevClient
    from jevmarket.jev.mock import MockTransport

    cache = DecisionCache(tmp_path)
    client = JevClient(MockTransport(seed=1), cache=cache)
    run(config(arm="jev_argmax", jev_client=client, periods=40, n_traders=10))

    assert cache.hit_rate > 0.15, f"cache hit rate collapsed to {cache.hit_rate:.1%}"


def test_burn_in_lets_an_informative_arm_inherit_a_book():
    """Cold start: with an empty book an informative arm may see no reason to
    quote at all. Burn-in periods of ZI flow open the market first."""
    result = run(
        config(arm="jev_argmax", jev_client=_jev_client(), periods=40,
               n_traders=10, burn_in_periods=5)
    )
    assert {d.arm for d in result.decisions} == {"burn_in", "jev_argmax"}
    assert all(d.arm == "burn_in" for d in result.decisions if d.period < 5)
    result.exchange.check_invariants()
