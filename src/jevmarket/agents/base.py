"""What every brain sees, and what every brain must return.

All four arms -- zero-intelligence, noisy best-response, Jev argmax, Jev
sample -- consume the same `Observation` and emit the same `Decision`. That is
the whole point of the design: the only thing that varies across arms is the
function in between.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..decision import Decision


@dataclass(frozen=True)
class Observation:
    """One trader's view of the world at the top of its turn."""

    period: int
    signal: float
    private_value: float
    best_bid: int | None
    best_ask: int | None
    last_price: int | None
    cash: int
    inventory: int
    available_cash: int
    available_inventory: int

    @property
    def spread(self) -> int | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @property
    def midpoint(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2


class Trader(Protocol):
    trader_id: str
    arm: str

    def decide(self, observation: Observation) -> Decision: ...
