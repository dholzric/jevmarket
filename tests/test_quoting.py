"""Code owns the price. `aggressiveness` in [0,1] maps to an integer tick.

The invariant that matters for the whole design: a trader never quotes on the
wrong side of its own private value, no matter what the model returns.
"""

import random

from jevmarket.book import Side
from jevmarket.quoting import quote_price


def test_buy_at_zero_aggressiveness_improves_the_best_bid_by_one_tick():
    assert quote_price(Side.BUY, value=110.0, aggressiveness=0.0, best_bid=100, best_ask=105) == 101


def test_buy_at_full_aggressiveness_lifts_the_best_ask():
    assert quote_price(Side.BUY, value=110.0, aggressiveness=1.0, best_bid=100, best_ask=105) == 105


def test_buy_never_quotes_above_its_private_value():
    assert quote_price(Side.BUY, value=103.0, aggressiveness=1.0, best_bid=100, best_ask=120) == 103


def test_sell_at_zero_aggressiveness_improves_the_best_ask_by_one_tick():
    assert quote_price(Side.SELL, value=90.0, aggressiveness=0.0, best_bid=100, best_ask=105) == 104


def test_sell_at_full_aggressiveness_hits_the_best_bid():
    assert quote_price(Side.SELL, value=90.0, aggressiveness=1.0, best_bid=100, best_ask=105) == 100


def test_sell_never_quotes_below_its_private_value():
    assert quote_price(Side.SELL, value=103.0, aggressiveness=1.0, best_bid=90, best_ask=120) == 103


def test_empty_book_buy_quotes_below_value_by_the_passive_offset():
    price = quote_price(Side.BUY, value=100.0, aggressiveness=0.0, best_bid=None, best_ask=None, passive_offset=5)
    assert price == 95


def test_empty_book_at_full_aggressiveness_quotes_at_value():
    assert quote_price(Side.BUY, value=100.0, aggressiveness=1.0, best_bid=None, best_ask=None) == 100


def test_returns_none_when_the_value_is_below_one_tick():
    assert quote_price(Side.BUY, value=0.4, aggressiveness=1.0, best_bid=None, best_ask=None) is None


def test_aggressiveness_is_monotone_in_price():
    prices = [
        quote_price(Side.BUY, value=130.0, aggressiveness=a / 10, best_bid=100, best_ask=120)
        for a in range(11)
    ]
    assert prices == sorted(prices)
    assert prices[0] < prices[-1]


def test_no_quote_is_ever_on_the_wrong_side_of_its_value():
    """Property test over the whole input space the model can reach."""
    rng = random.Random(31337)
    for _ in range(20_000):
        value = rng.uniform(1.0, 200.0)
        aggressiveness = rng.random()
        best_bid = rng.choice([None, rng.randint(1, 200)])
        best_ask = rng.choice([None, rng.randint(1, 200)])
        side = rng.choice([Side.BUY, Side.SELL])

        price = quote_price(side, value, aggressiveness, best_bid, best_ask)
        if price is None:
            continue
        assert price >= 1
        if side is Side.BUY:
            assert price <= value, f"bought above value: {price} > {value}"
        else:
            assert price >= value, f"sold below value: {price} < {value}"
