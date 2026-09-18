"""The jumping fundamental F_t and the information treatments layered on it.

F_t is piecewise constant: with probability `jump_prob` each period it moves by
a Normal(0, jump_sd) shock, otherwise it holds. Piecewise-constant (rather than
a random walk) is deliberate -- it makes "how fast does price find the new
fundamental after a jump" a well-posed question, which is what the primary
outcome (post-jump RMSE) measures.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Fundamental:
    initial: float = 100.0
    jump_prob: float = 0.02
    jump_sd: float = 8.0
    seed: int = 0
    floor: float = 1.0

    jump_times: list[int] = field(default_factory=list, init=False, repr=False)
    _path: list[float] | None = field(default=None, init=False, repr=False)

    def path(self, periods: int) -> list[float]:
        """F_0 .. F_{periods-1}. Cached: one Fundamental means one path."""
        if self._path is not None and len(self._path) >= periods:
            return self._path[:periods]

        rng = np.random.default_rng(self.seed)
        values = [float(self.initial)]
        self.jump_times = []
        for t in range(1, periods):
            if rng.random() < self.jump_prob:
                shock = float(rng.normal(0.0, self.jump_sd))
                values.append(max(self.floor, values[-1] + shock))
                if values[-1] != values[-2]:
                    self.jump_times.append(t)
            else:
                values.append(values[-1])

        self._path = values
        return values


@dataclass
class Signal:
    """What a trader sees instead of F_t.

    `delay=0, noise_sd=0` is the full-information arm. Anything else is the
    delayed/noisy arm. Noise is a pure function of (seed, t), so two traders
    with the same seed see the same world and a rerun reproduces it exactly.
    """

    delay: int = 0
    noise_sd: float = 0.0
    seed: int = 0

    def __post_init__(self) -> None:
        if self.delay < 0:
            raise ValueError(f"delay must be non-negative, got {self.delay}")
        if self.noise_sd < 0:
            raise ValueError(f"noise_sd must be non-negative, got {self.noise_sd}")

    @property
    def is_full_information(self) -> bool:
        return self.delay == 0 and self.noise_sd == 0.0

    def observe(self, path: list[float], t: int) -> float:
        base = path[max(0, t - self.delay)]
        if self.noise_sd == 0.0:
            return base
        rng = np.random.default_rng([self.seed, t])
        return float(base + rng.normal(0.0, self.noise_sd))
