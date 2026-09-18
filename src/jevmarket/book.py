"""Continuous double auction limit order book.

Integer tick prices, integer quantities, strict price-time priority.
The book owns matching; it never owns trader accounts.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


@dataclass
class Order:
    order_id: int
    trader_id: str
    side: Side
    price: int
    quantity: int
    seq: int


@dataclass(frozen=True)
class Trade:
    """One execution. Price is always the resting (passive) order's price."""

    price: int
    quantity: int
    buyer_id: str
    seller_id: str
    buy_order_id: int
    sell_order_id: int
    seq: int


@dataclass
class SubmitResult:
    order_id: int
    trades: list = field(default_factory=list)
    resting_quantity: int = 0


class Book:
    """Price-time priority limit order book for a single good."""

    def __init__(self) -> None:
        self._levels: dict[Side, dict[int, deque[Order]]] = {
            Side.BUY: {},
            Side.SELL: {},
        }
        self._next_order_id = 1
        self._next_seq = 1

    @property
    def best_bid(self) -> int | None:
        prices = self._levels[Side.BUY]
        return max(prices) if prices else None

    @property
    def best_ask(self) -> int | None:
        prices = self._levels[Side.SELL]
        return min(prices) if prices else None

    def submit(
        self, trader_id: str, side: Side, price: int, quantity: int
    ) -> SubmitResult:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        if price <= 0:
            raise ValueError(f"price must be positive, got {price}")

        order = Order(
            order_id=self._next_order_id,
            trader_id=trader_id,
            side=Side(side),
            price=int(price),
            quantity=int(quantity),
            seq=self._next_seq,
        )
        self._next_order_id += 1
        self._next_seq += 1

        self._cancel_trader_side(trader_id, order.side.opposite)
        trades = self._match(order)
        if order.quantity > 0:
            self._rest(order)
        return SubmitResult(
            order_id=order.order_id,
            trades=trades,
            resting_quantity=order.quantity,
        )

    def quantity_at(self, side: Side, price: int) -> int:
        """Total resting quantity at one price level."""
        return sum(o.quantity for o in self._levels[Side(side)].get(price, ()))

    def depth(self, side: Side) -> list[tuple[int, int]]:
        """Resting (price, quantity) levels, best price first."""
        levels = self._levels[Side(side)]
        prices = sorted(levels, reverse=(Side(side) is Side.BUY))
        return [(p, sum(o.quantity for o in levels[p])) for p in prices]

    def cancel_all(self, trader_id: str) -> None:
        """Remove every resting order belonging to one trader."""
        for side in (Side.BUY, Side.SELL):
            self._cancel_trader_side(trader_id, side)

    # -- internals -----------------------------------------------------------

    def _crosses(self, incoming: Side, incoming_price: int, resting_price: int) -> bool:
        if incoming is Side.BUY:
            return incoming_price >= resting_price
        return incoming_price <= resting_price

    def _best_opposite_price(self, incoming: Side) -> int | None:
        return self.best_ask if incoming is Side.BUY else self.best_bid

    def _match(self, order: Order) -> list[Trade]:
        """Consume opposite-side liquidity at prices that cross, best first."""
        trades: list[Trade] = []
        opposite = self._levels[order.side.opposite]

        while order.quantity > 0:
            best = self._best_opposite_price(order.side)
            if best is None or not self._crosses(order.side, order.price, best):
                break

            level = opposite[best]
            while order.quantity > 0 and level:
                resting = level[0]
                filled = min(order.quantity, resting.quantity)
                order.quantity -= filled
                resting.quantity -= filled

                buy, sell = (
                    (order, resting) if order.side is Side.BUY else (resting, order)
                )
                trades.append(
                    Trade(
                        price=best,
                        quantity=filled,
                        buyer_id=buy.trader_id,
                        seller_id=sell.trader_id,
                        buy_order_id=buy.order_id,
                        sell_order_id=sell.order_id,
                        seq=self._next_seq,
                    )
                )
                self._next_seq += 1

                if resting.quantity == 0:
                    level.popleft()

            if not level:
                del opposite[best]

        return trades

    def _rest(self, order: Order) -> None:
        level = self._levels[order.side].setdefault(order.price, deque())
        level.append(order)

    def _cancel_trader_side(self, trader_id: str, side: Side) -> None:
        """Self-trade prevention: a trader's resting orders on `side` are pulled."""
        levels = self._levels[side]
        for price in list(levels):
            level = deque(o for o in levels[price] if o.trader_id != trader_id)
            if level:
                levels[price] = level
            else:
                del levels[price]

    def resting_orders(self, trader_id: str) -> list[Order]:
        """Every order this trader currently has resting, both sides."""
        return [
            order
            for levels in self._levels.values()
            for level in levels.values()
            for order in level
            if order.trader_id == trader_id
        ]

    def cancel_all_on_side(self, trader_id: str, side: Side) -> None:
        self._cancel_trader_side(trader_id, Side(side))
