"""Limit order book behaviour: resting, matching, and price-time priority."""

import pytest

from jevmarket.book import Book, Side


def test_empty_book_has_no_best_bid_or_ask():
    book = Book()
    assert book.best_bid is None
    assert book.best_ask is None


def test_non_crossing_buy_rests_and_sets_best_bid():
    book = Book()
    result = book.submit(trader_id="t1", side=Side.BUY, price=100, quantity=5)
    assert result.trades == []
    assert result.resting_quantity == 5
    assert book.best_bid == 100
    assert book.best_ask is None


def test_non_crossing_sell_rests_and_sets_best_ask():
    book = Book()
    book.submit(trader_id="t1", side=Side.SELL, price=110, quantity=3)
    assert book.best_ask == 110
    assert book.best_bid is None


def test_higher_bid_replaces_best_bid():
    book = Book()
    book.submit(trader_id="t1", side=Side.BUY, price=100, quantity=5)
    book.submit(trader_id="t2", side=Side.BUY, price=101, quantity=5)
    assert book.best_bid == 101


def test_lower_ask_replaces_best_ask():
    book = Book()
    book.submit(trader_id="t1", side=Side.SELL, price=110, quantity=5)
    book.submit(trader_id="t2", side=Side.SELL, price=109, quantity=5)
    assert book.best_ask == 109


def test_rejects_non_positive_quantity():
    book = Book()
    with pytest.raises(ValueError):
        book.submit(trader_id="t1", side=Side.BUY, price=100, quantity=0)


# --- matching ---------------------------------------------------------------


def test_crossing_buy_trades_at_resting_ask_price():
    book = Book()
    book.submit(trader_id="seller", side=Side.SELL, price=110, quantity=5)
    result = book.submit(trader_id="buyer", side=Side.BUY, price=120, quantity=5)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.price == 110
    assert trade.quantity == 5
    assert trade.buyer_id == "buyer"
    assert trade.seller_id == "seller"
    assert result.resting_quantity == 0
    assert book.best_ask is None


def test_crossing_sell_trades_at_resting_bid_price():
    book = Book()
    book.submit(trader_id="buyer", side=Side.BUY, price=100, quantity=4)
    result = book.submit(trader_id="seller", side=Side.SELL, price=90, quantity=4)

    assert len(result.trades) == 1
    assert result.trades[0].price == 100
    assert book.best_bid is None


def test_incoming_larger_than_resting_leaves_remainder_on_book():
    book = Book()
    book.submit(trader_id="seller", side=Side.SELL, price=110, quantity=3)
    result = book.submit(trader_id="buyer", side=Side.BUY, price=110, quantity=8)

    assert sum(t.quantity for t in result.trades) == 3
    assert result.resting_quantity == 5
    assert book.best_bid == 110
    assert book.best_ask is None


def test_resting_larger_than_incoming_keeps_remainder_resting():
    book = Book()
    book.submit(trader_id="seller", side=Side.SELL, price=110, quantity=9)
    result = book.submit(trader_id="buyer", side=Side.BUY, price=110, quantity=2)

    assert sum(t.quantity for t in result.trades) == 2
    assert result.resting_quantity == 0
    assert book.best_ask == 110
    assert book.quantity_at(Side.SELL, 110) == 7


def test_marketable_order_sweeps_cheapest_levels_first():
    book = Book()
    book.submit(trader_id="s_expensive", side=Side.SELL, price=112, quantity=5)
    book.submit(trader_id="s_cheap", side=Side.SELL, price=110, quantity=5)
    result = book.submit(trader_id="buyer", side=Side.BUY, price=115, quantity=7)

    prices = [t.price for t in result.trades]
    assert prices == [110, 112]
    assert [t.quantity for t in result.trades] == [5, 2]


def test_book_is_never_crossed_after_matching():
    book = Book()
    book.submit(trader_id="s1", side=Side.SELL, price=110, quantity=5)
    book.submit(trader_id="b1", side=Side.BUY, price=115, quantity=9)

    assert book.best_bid is None or book.best_ask is None or book.best_bid < book.best_ask


def test_time_priority_within_a_price_level():
    book = Book()
    book.submit(trader_id="early", side=Side.SELL, price=110, quantity=2)
    book.submit(trader_id="late", side=Side.SELL, price=110, quantity=2)
    result = book.submit(trader_id="buyer", side=Side.BUY, price=110, quantity=3)

    assert [t.seller_id for t in result.trades] == ["early", "late"]
    assert [t.quantity for t in result.trades] == [2, 1]


def test_self_trade_is_prevented_by_cancelling_own_resting_orders():
    book = Book()
    book.submit(trader_id="t1", side=Side.SELL, price=110, quantity=5)
    result = book.submit(trader_id="t1", side=Side.BUY, price=115, quantity=5)

    assert result.trades == []
    assert book.best_ask is None
    assert book.best_bid == 115
