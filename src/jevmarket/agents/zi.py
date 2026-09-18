"""Zero-intelligence baseline.

Random direction, random aggressiveness, no view of the book. Its distribution
over {buy, sell, pass} is a fixed randomisation that never moves with the
state, which is exactly what makes it the null model for the calibration
outcome. It is not stupid in the way it trades: `quote_price` clamps every
quote at its private value, so like Gode & Sunder's ZI-C it never knowingly
trades at a loss. Everything above that constraint is noise.
"""

from __future__ import annotations

import numpy as np

from ..decision import Decision
from .base import Observation

PASS_PROBABILITY = 0.10
SIDE_PROBABILITY = (1.0 - PASS_PROBABILITY) / 2
POLICY = {"buy": SIDE_PROBABILITY, "sell": SIDE_PROBABILITY, "pass": PASS_PROBABILITY}


class ZeroIntelligence:
    arm = "zi"

    def __init__(self, trader_id: str, seed: int = 0) -> None:
        self.trader_id = trader_id
        self.seed = seed

    def decide(self, observation: Observation) -> Decision:
        # Seeded on (seed, period) so a rerun reproduces the path exactly,
        # independent of the order traders happen to be called in.
        rng = np.random.default_rng([self.seed, observation.period])
        action = rng.choice(list(POLICY), p=list(POLICY.values()))
        return Decision.create(
            action=str(action),
            aggressiveness=float(rng.random()),
            already_priced=0.5,  # no view: the uninformative midpoint
            action_probabilities=dict(POLICY),
        )
