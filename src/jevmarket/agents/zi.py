"""Zero-intelligence baseline.

Random direction, random aggressiveness, no view of the book, and a flat 0.5
confidence -- the null model for the calibration outcome. It is not stupid in
the way it trades: `quote_price` clamps every quote at its private value, so
like Gode & Sunder's ZI-C it never knowingly trades at a loss. Everything above
that constraint is noise.
"""

from __future__ import annotations

import numpy as np

from ..decision import Decision
from .base import Observation

PASS_PROBABILITY = 0.10


class ZeroIntelligence:
    arm = "zi"

    def __init__(self, trader_id: str, seed: int = 0) -> None:
        self.trader_id = trader_id
        self.seed = seed

    def decide(self, observation: Observation) -> Decision:
        # Seeded on (seed, period) so a rerun reproduces the path exactly,
        # independent of the order traders happen to be called in.
        rng = np.random.default_rng([self.seed, observation.period])
        side_p = (1.0 - PASS_PROBABILITY) / 2
        action = rng.choice(
            ["buy", "sell", "pass"], p=[side_p, side_p, PASS_PROBABILITY]
        )
        return Decision.from_payload(
            {
                "action": str(action),
                "aggressiveness": float(rng.random()),
                "already_priced": False,
                "confidence": 0.5,
                "rationale": "",
            }
        )
