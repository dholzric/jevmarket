"""Conservation invariants: the exchange creates and destroys nothing.

These are the tests that make the instrument trustworthy. Every trade moves
cash from buyer to seller and inventory from seller to buyer, one-for-one.
"""

import random

import pytest

from jevmarket.book import Side
from jevmarket.exchange import Exchange, InsufficientFunds, InsufficientInventory


def make_exchange(n=4, cash=100_000, inventory=50, **kwargs):
    return Exchange.from_endowments(
        [f"t{i}" for i in range(n)], cash=cash, inventory=inventory, **kwargs
    )


def test_endowments_set_starting_totals():
    ex = make_exchange(n=4, cash=1_000, inventory=10)
    assert ex.total_cash == 4_000
    assert ex.total_inventory == 40


def test_a_trade_moves_cash_and_inventory_one_for_one():
    ex = make_exchange(n=2, cash=1_000, inventory=10)
    ex.submit("t0", Side.SELL, price=100, quantity=3)
    ex.submit("t1", Side.BUY, price=100, quantity=3)

    assert ex.accounts["t0"].cash == 1_300
    assert ex.accounts["t0"].inventory == 7
    assert ex.accounts["t1"].cash == 700
    assert ex.accounts["t1"].inventory == 13


def test_totals_are_conserved_across_a_trade():
    ex = make_exchange(n=2, cash=1_000, inventory=10)
    ex.submit("t0", Side.SELL, price=100, quantity=3)
    ex.submit("t1", Side.BUY, price=100, quantity=3)

    assert ex.total_cash == 2_000
    assert ex.total_inventory == 20


def test_buy_beyond_available_cash_is_rejected():
    ex = make_exchange(n=2, cash=500, inventory=10)
    with pytest.raises(InsufficientFunds):
        ex.submit("t0", Side.BUY, price=100, quantity=6)


def test_sell_beyond_available_inventory_is_rejected():
    ex = make_exchange(n=2, cash=500, inventory=10)
    with pytest.raises(InsufficientInventory):
        ex.submit("t0", Side.SELL, price=100, quantity=11)


def test_resting_buy_order_commits_cash_against_a_second_order():
    ex = make_exchange(n=2, cash=1_000, inventory=10)
    ex.submit("t0", Side.BUY, price=100, quantity=10)  # commits the whole 1,000
    with pytest.raises(InsufficientFunds):
        ex.submit("t0", Side.BUY, price=100, quantity=1)


def test_resting_sell_order_commits_inventory():
    ex = make_exchange(n=2, cash=1_000, inventory=10)
    ex.submit("t0", Side.SELL, price=100, quantity=10)
    with pytest.raises(InsufficientInventory):
        ex.submit("t0", Side.SELL, price=100, quantity=1)


def test_cash_and_inventory_never_go_negative():
    ex = make_exchange(n=2, cash=1_000, inventory=10)
    ex.submit("t0", Side.SELL, price=50, quantity=10)
    ex.submit("t1", Side.BUY, price=50, quantity=10)

    for account in ex.accounts.values():
        assert account.cash >= 0
        assert account.inventory >= 0


def test_invariants_hold_under_random_order_flow():
    """The property test: 20k random submissions, nothing created or destroyed."""
    rng = random.Random(20260918)
    ex = make_exchange(n=12, cash=50_000, inventory=40)
    start_cash, start_inventory = ex.total_cash, ex.total_inventory

    accepted = 0
    for _ in range(20_000):
        trader = f"t{rng.randrange(12)}"
        side = rng.choice([Side.BUY, Side.SELL])
        price = rng.randint(80, 120)
        quantity = rng.randint(1, 5)
        try:
            ex.submit(trader, side, price=price, quantity=quantity)
            accepted += 1
        except (InsufficientFunds, InsufficientInventory):
            pass
        ex.check_invariants()

    assert accepted > 1_000, "flow was rejected too often to exercise the book"
    assert ex.trade_count > 100, "no trades happened; the test proves nothing"
    assert ex.total_cash == start_cash
    assert ex.total_inventory == start_inventory


def test_book_is_never_crossed_under_random_order_flow():
    rng = random.Random(4242)
    ex = make_exchange(n=8, cash=50_000, inventory=40)

    for _ in range(5_000):
        trader = f"t{rng.randrange(8)}"
        side = rng.choice([Side.BUY, Side.SELL])
        try:
            ex.submit(trader, side, price=rng.randint(90, 110), quantity=rng.randint(1, 4))
        except (InsufficientFunds, InsufficientInventory):
            pass
        bid, ask = ex.book.best_bid, ex.book.best_ask
        if bid is not None and ask is not None:
            assert bid < ask
