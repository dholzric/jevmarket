"""Aggressiveness -> price. The one place a number becomes an order.

A brain (ZI, NBR, or Jev) supplies a direction and a scalar in [0,1]. This
module turns that into an integer tick, anchored on the book, and hard-clamps
it at the trader's own private value. That clamp is what stops an LLM from
buying above value because it phrased something confidently: the model cannot
express a losing price, because it never expresses a price at all.
"""

from __future__ import annotations

import math

from .book import Side

DEFAULT_PASSIVE_OFFSET = 5


def quote_price(
    side: Side,
    value: float,
    aggressiveness: float,
    best_bid: int | None,
    best_ask: int | None,
    passive_offset: int = DEFAULT_PASSIVE_OFFSET,
) -> int | None:
    """Integer tick price, or None if no admissible quote exists.

    aggressiveness 0 -> improve the near touch by one tick (passive)
    aggressiveness 1 -> cross to the far touch (marketable), value permitting
    """
    side = Side(side)
    aggressiveness = min(1.0, max(0.0, float(aggressiveness)))

    if side is Side.BUY:
        limit = math.floor(value)
        if limit < 1:
            return None
        passive = min(best_bid + 1, limit) if best_bid is not None else limit - passive_offset
        passive = max(1, min(passive, limit))
        marketable = min(best_ask, limit) if best_ask is not None else limit
        lo, hi = passive, max(passive, marketable)
    else:
        limit = math.ceil(value)
        if limit < 1:
            return None
        passive = max(best_ask - 1, limit) if best_ask is not None else limit + passive_offset
        marketable = max(best_bid, limit) if best_bid is not None else limit
        hi, lo = passive, min(passive, marketable)
        aggressiveness = 1.0 - aggressiveness  # for sells, aggressive means lower

    price = int(round(lo + aggressiveness * (hi - lo)))
    price = max(1, price)
    if side is Side.BUY:
        return min(price, limit)
    return max(price, limit)
