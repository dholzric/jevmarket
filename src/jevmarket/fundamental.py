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


@dataclass
class MatchedJumpFundamental:
    """A designed fundamental for the up-vs-down comparison.

    The random-jump process is fine for measuring price discovery in general,
    but it is badly underpowered for comparing post-jump error after UP jumps
    against after DOWN jumps: a single run draws different numbers of each, at
    different magnitudes, from different price levels. The pilot showed this
    directly -- zero-intelligence, which is symmetric by construction, still
    returned a spurious -0.82 gap on one seed, larger than the effects we are
    trying to detect.

    This process removes that variance by design. Jumps are evenly spaced, of
    identical magnitude, and strictly alternating in direction, so every up
    window is matched by a down window of the same size from the same two price
    levels. The up-vs-down comparison becomes paired, and most of the noise
    cancels within the run rather than having to be averaged away across seeds.

    Only the starting direction is random, so that the two levels are not
    confounded with direction across seeds.
    """

    initial: float = 100.0
    jump_size: float = 10.0
    period_gap: int = 20
    seed: int = 0
    floor: float = 1.0

    jump_times: list[int] = field(default_factory=list, init=False, repr=False)
    _path: list[float] | None = field(default=None, init=False, repr=False)

    def path(self, periods: int) -> list[float]:
        if self._path is not None and len(self._path) >= periods:
            return self._path[:periods]

        rng = np.random.default_rng(self.seed)
        direction = 1 if rng.random() < 0.5 else -1

        # Only an even number of jumps, so every up is matched by a down. A
        # trailing unpaired jump would reintroduce exactly the imbalance this
        # process exists to remove.
        scheduled = [t for t in range(1, periods) if t % self.period_gap == 0]
        if len(scheduled) % 2:
            scheduled.pop()
        scheduled_set = set(scheduled)

        values = [float(self.initial)]
        self.jump_times = []
        for t in range(1, periods):
            if t in scheduled_set:
                values.append(max(self.floor, values[-1] + direction * self.jump_size))
                self.jump_times.append(t)
                direction = -direction
            else:
                values.append(values[-1])

        self._path = values
        return values
