"""A Jev-shaped transport that never touches the network.

Its job is not to imitate Jev's judgement -- it cannot -- but to exercise every
line of the pipeline for free: request building, cache keys, budget charging,
answer parsing, and both decode arms. It leans the direction the private value
implies, with enough probability mass elsewhere that the sampling arm actually
samples.
"""

from __future__ import annotations

import numpy as np

from .transport import JevRequest, JevResponse

SCORE_LEVELS = 5


def _softmax(values: np.ndarray) -> np.ndarray:
    exponentiated = np.exp(values - values.max())
    return exponentiated / exponentiated.sum()


class MockTransport:
    """Deterministic given (seed, request). No I/O, no cost."""

    def __init__(self, seed: int = 0, sharpness: float = 0.08) -> None:
        self.seed = seed
        self.sharpness = sharpness

    def send(self, request: JevRequest) -> JevResponse:
        state = request.state
        rng = np.random.default_rng([self.seed, int(request.cache_key[:8], 16)])

        value = state["your_private_value"]
        bid, ask = state["best_bid"], state["best_ask"]
        if bid is not None and ask is not None:
            reference = (bid + ask) / 2
        elif state["last_trade_price"] is not None:
            reference = state["last_trade_price"]
        else:
            # Empty book, no trades yet. Price off the signal, not off your own
            # value -- otherwise edge is 0 by construction, everyone passes, and
            # the market never opens.
            reference = state["your_signal"]
        edge = value - reference

        options = ["buy", "sell", "pass"]
        logits = np.array(
            [
                self.sharpness * edge,
                -self.sharpness * edge,
                -abs(self.sharpness * edge) + 0.4,
            ]
        )
        probabilities = _softmax(logits + rng.normal(0.0, 0.15, size=3))
        chosen = options[int(np.argmax(probabilities))]

        level_logits = np.array(
            [abs(edge) * self.sharpness * (level - 2) for level in range(SCORE_LEVELS)]
        )
        level_probabilities = _softmax(level_logits + rng.normal(0.0, 0.2, SCORE_LEVELS))
        score = float(np.dot(np.arange(SCORE_LEVELS), level_probabilities))

        return JevResponse(
            answers={
                "action": {
                    "type": "choice",
                    "choice": chosen,
                    "probabilities": {
                        option: float(p) for option, p in zip(options, probabilities)
                    },
                    "confidence": float(probabilities.max()),
                },
                "aggressiveness": {
                    "type": "score",
                    "score": score,
                    "legend": {str(i): f"level {i}" for i in range(SCORE_LEVELS)},
                    "probabilities": {
                        str(i): float(p) for i, p in enumerate(level_probabilities)
                    },
                    "confidence": float(level_probabilities.max()),
                },
                "already_priced": {
                    "type": "noul",
                    "noul": float(np.exp(-abs(edge) * self.sharpness)),
                },
            },
            model="jev-mock-1.0.0",
            input_tokens=len(str(sorted(state.items()))) // 4 + 120,
            output_tokens=24,
            latency_s=0.0,
        )
