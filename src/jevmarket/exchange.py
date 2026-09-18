"""Accounts layer: the book matches, the exchange settles.

Every accepted order is pre-checked against uncommitted cash (buys) or
uncommitted inventory (sells), so no trader can spend or deliver what it does
not have. Settlement is a pure transfer, which is what makes total cash and
total inventory conserved by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .book import Book, Side, SubmitResult, Trade


class OrderRejected(Exception):
    """Base class for orders the exchange refuses to accept."""


class InsufficientFunds(OrderRejected):
    """Buy order would commit more cash than the trader has uncommitted."""


class InsufficientInventory(OrderRejected):
    """Sell order would commit more of the good than the trader holds."""


@dataclass
class Account:
    cash: int
    inventory: int

    def mark_to_market(self, price: float) -> float:
        return self.cash + self.inventory * price


class Exchange:
    """A continuous double auction with hard budget and inventory constraints."""

    def __init__(
        self,
        accounts: dict[str, Account],
        *,
        max_short: int = 0,
        max_borrow: int = 0,
    ) -> None:
        self.accounts = accounts
        self.book = Book()
        self.trades: list[Trade] = []
        self.max_short = max_short
        self.max_borrow = max_borrow
        self._initial_cash = sum(a.cash for a in accounts.values())
        self._initial_inventory = sum(a.inventory for a in accounts.values())

    @classmethod
    def from_endowments(
        cls,
        trader_ids: Iterable[str],
        *,
        cash: int,
        inventory: int,
        **kwargs,
    ) -> "Exchange":
        return cls(
            {tid: Account(cash=cash, inventory=inventory) for tid in trader_ids},
            **kwargs,
        )

    # -- totals --------------------------------------------------------------

    @property
    def total_cash(self) -> int:
        return sum(a.cash for a in self.accounts.values())

    @property
    def total_inventory(self) -> int:
        return sum(a.inventory for a in self.accounts.values())

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def last_price(self) -> int | None:
        return self.trades[-1].price if self.trades else None

    # -- commitments ---------------------------------------------------------

    def committed_cash(self, trader_id: str) -> int:
        return sum(
            o.price * o.quantity
            for o in self.book.resting_orders(trader_id)
            if o.side is Side.BUY
        )

    def committed_inventory(self, trader_id: str) -> int:
        return sum(
            o.quantity
            for o in self.book.resting_orders(trader_id)
            if o.side is Side.SELL
        )

    def available_cash(self, trader_id: str) -> int:
        account = self.accounts[trader_id]
        return account.cash + self.max_borrow - self.committed_cash(trader_id)

    def available_inventory(self, trader_id: str) -> int:
        account = self.accounts[trader_id]
        return account.inventory + self.max_short - self.committed_inventory(trader_id)

    # -- trading -------------------------------------------------------------

    def submit(
        self, trader_id: str, side: Side, price: int, quantity: int
    ) -> SubmitResult:
        if trader_id not in self.accounts:
            raise KeyError(f"unknown trader {trader_id!r}")
        side = Side(side)
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")

        # Submitting on one side pulls this trader's resting orders on the
        # other side (self-trade prevention), which frees their commitments.
        freed_side = side.opposite
        if any(o.side is freed_side for o in self.book.resting_orders(trader_id)):
            self.book.cancel_all_on_side(trader_id, freed_side)

        if side is Side.BUY:
            cost = price * quantity
            if cost > self.available_cash(trader_id):
                raise InsufficientFunds(
                    f"{trader_id} needs {cost} but has "
                    f"{self.available_cash(trader_id)} uncommitted"
                )
        else:
            if quantity > self.available_inventory(trader_id):
                raise InsufficientInventory(
                    f"{trader_id} needs {quantity} units but has "
                    f"{self.available_inventory(trader_id)} uncommitted"
                )

        result = self.book.submit(trader_id, side, price, quantity)
        for trade in result.trades:
            self._settle(trade)
        self.trades.extend(result.trades)
        return result

    def cancel_all(self, trader_id: str) -> None:
        self.book.cancel_all(trader_id)

    def _settle(self, trade: Trade) -> None:
        value = trade.price * trade.quantity
        buyer = self.accounts[trade.buyer_id]
        seller = self.accounts[trade.seller_id]
        buyer.cash -= value
        seller.cash += value
        buyer.inventory += trade.quantity
        seller.inventory -= trade.quantity

    # -- invariants ----------------------------------------------------------

    def check_invariants(self) -> None:
        """Raise AssertionError if the exchange has created or destroyed anything."""
        assert self.total_cash == self._initial_cash, (
            f"cash not conserved: {self.total_cash} != {self._initial_cash}"
        )
        assert self.total_inventory == self._initial_inventory, (
            f"inventory not conserved: "
            f"{self.total_inventory} != {self._initial_inventory}"
        )
        for trader_id, account in self.accounts.items():
            assert account.cash >= -self.max_borrow, f"{trader_id} cash {account.cash}"
            assert account.inventory >= -self.max_short, (
                f"{trader_id} inventory {account.inventory}"
            )
            assert self.available_cash(trader_id) >= 0, (
                f"{trader_id} committed more cash than it holds"
            )
            assert self.available_inventory(trader_id) >= 0, (
                f"{trader_id} committed more inventory than it holds"
            )
        bid, ask = self.book.best_bid, self.book.best_ask
        assert bid is None or ask is None or bid < ask, f"crossed book {bid}/{ask}"
