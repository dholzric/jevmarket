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
