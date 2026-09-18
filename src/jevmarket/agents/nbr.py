"""Noisy best-response: the informed, symmetric benchmark.

For every (side, aggressiveness level) pair it prices the quote through the
same `quote_price` the other arms use, scores it by expected surplus times a
simple fill probability, and softmaxes over the result. The temperature is the
noise: low is near-optimal play, high is near-indifference.

Its defining property for this project is **symmetry**. The utility
calculation treats acquiring and disposing identically, so a buy at edge +x and
a sell at edge -x receive exactly the same probability. Jev under the original
wording does not, and NBR is the yardstick that makes that visible.
"""

from __future__ import annotations

import numpy as np

from ..book import Side
from ..decision import Decision
from ..quoting import quote_price
from .base import Observation

SCORE_LEVELS = 5
DEFAULT_TEMPERATURE = 0.5

# Crude but symmetric fill model. The point is that it never favours one side.
FILL_MARKETABLE = 1.0
FILL_IMPROVING = 0.35
FILL_BEHIND = 0.15

# Added only for choosing among exactly-equal utilities; never affects the
# reported distribution.
TIE_BREAK_TOWARD_PASS = np.array([0.0, 0.0, 1e-12])


class NoisyBestResponse:
    arm = "nbr"

    def __init__(
        self,
        trader_id: str,
        seed: int = 0,
        temperature: float = DEFAULT_TEMPERATURE,
        already_priced_scale: float = 5.0,
    ) -> None:
        self.trader_id = trader_id
        self.seed = seed
        self.temperature = max(1e-6, float(temperature))
        self.already_priced_scale = already_priced_scale

    # -- utilities -----------------------------------------------------------

    def _fill_probability(self, side: Side, price: int, observation: Observation) -> float:
        best_bid, best_ask = observation.best_bid, observation.best_ask
        if side is Side.BUY:
            if best_ask is not None and price >= best_ask:
                return FILL_MARKETABLE
            if best_bid is None or price > best_bid:
                return FILL_IMPROVING
            return FILL_BEHIND
        if best_bid is not None and price <= best_bid:
            return FILL_MARKETABLE
        if best_ask is None or price < best_ask:
            return FILL_IMPROVING
        return FILL_BEHIND

    def _side_utilities(self, side: Side, observation: Observation):
        """Expected surplus at each aggressiveness level on one side."""
        value = observation.private_value
        utilities = []
        for level in range(SCORE_LEVELS):
            aggressiveness = level / (SCORE_LEVELS - 1)
            price = quote_price(
                side, value, aggressiveness, observation.best_bid, observation.best_ask
            )
            if price is None:
                utilities.append(0.0)
                continue
            surplus = (value - price) if side is Side.BUY else (price - value)
            utilities.append(
                max(0.0, surplus) * self._fill_probability(side, price, observation)
            )
        return np.array(utilities)

    def decide(self, observation: Observation) -> Decision:
        buy = self._side_utilities(Side.BUY, observation)
        sell = self._side_utilities(Side.SELL, observation)

        # One utility per action: the best that side can do. Passing is worth 0.
        action_utilities = np.array([buy.max(), sell.max(), 0.0])
        probabilities = _softmax(action_utilities / self.temperature)
        options = ["buy", "sell", "pass"]
        # Exact ties must break toward passing. With zero expected surplus there
        # is no reason to trade, and a bare argmax would break the tie toward
        # whichever side is listed first -- silently making NBR asymmetric at
        # precisely the zero-edge point where its symmetry is the whole claim.
        action = options[int(np.argmax(action_utilities + TIE_BREAK_TOWARD_PASS))]

        # Aggressiveness is the softmax-weighted level on the chosen side, so it
        # is continuous in the edge rather than jumping between grid points.
        levels = buy if action == "buy" else sell if action == "sell" else None
        if levels is None or levels.max() <= 0.0:
            aggressiveness = 0.0
        else:
            weights = _softmax(levels / self.temperature)
            aggressiveness = float(
                np.dot(weights, np.arange(SCORE_LEVELS)) / (SCORE_LEVELS - 1)
            )

        reference = observation.midpoint
        if reference is None:
            reference = observation.last_price
        if reference is None:
            already_priced = 0.5
        else:
            already_priced = float(
                np.exp(-abs(observation.signal - reference) / self.already_priced_scale)
            )

        return Decision.create(
            action=action,
            aggressiveness=min(1.0, max(0.0, aggressiveness)),
            already_priced=min(1.0, max(0.0, already_priced)),
            action_probabilities=dict(zip(options, (float(p) for p in probabilities))),
        )


def _softmax(values: np.ndarray) -> np.ndarray:
    exponentiated = np.exp(values - values.max())
    return exponentiated / exponentiated.sum()
