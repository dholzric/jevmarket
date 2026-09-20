"""The three pre-declared primary outcomes.

Only three things decide the paper: how fast price finds the fundamental after
a jump (post-jump RMSE), whether stated confidence means anything (ECE), and
how often an arm is loud and wrong (confidently-wrong rate). Anything else this
module grows later is secondary and must be labelled as such in the write-up.
"""

from __future__ import annotations

import math

import numpy as np

DEFAULT_POST_JUMP_WINDOW = 20
CONFIDENT_THRESHOLD = 0.8


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _rmse(errors: list[float]) -> float:
    if not errors:
        return float("nan")
    return float(np.sqrt(np.mean(errors)))


def rmse_vs_fundamental(prices, fundamental) -> float:
    """Root mean squared pricing error over the periods that actually traded."""
    errors = [
        (price - f) ** 2
        for price, f in zip(prices, fundamental)
        if not _is_missing(price)
    ]
    return _rmse(errors)


def post_jump_rmse(
    prices, fundamental, jump_times, window: int = DEFAULT_POST_JUMP_WINDOW
) -> float:
    """PRIMARY OUTCOME 1. Pricing error in the periods just after a jump."""
    n = len(fundamental)
    errors = [
        (prices[t] - fundamental[t]) ** 2
        for jump in jump_times
        for t in range(jump, min(jump + window, n))
        if not _is_missing(prices[t])
    ]
    return _rmse(errors)


def _bins(confidences: np.ndarray, n_bins: int):
    """Yield (mask, count) for equal-width bins; bin 1 is closed at both ends."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (
            confidences <= hi if lo == 0.0 else (confidences > lo) & (confidences <= hi)
        )
        yield mask, int(mask.sum())


def expected_calibration_error(confidences, correct, n_bins: int = 10) -> float:
    """PRIMARY OUTCOME 2. Equal-width-bin ECE over stated confidence."""
    confidences = np.asarray(list(confidences), dtype=float)
    correct = np.asarray(list(correct), dtype=float)
    total = confidences.size
    if total == 0:
        return float("nan")

    ece = 0.0
    for mask, count in _bins(confidences, n_bins):
        if count:
            gap = abs(correct[mask].mean() - confidences[mask].mean())
            ece += (count / total) * gap
    return float(ece)


def confidently_wrong_rate(
    confidences, correct, threshold: float = CONFIDENT_THRESHOLD
) -> float:
    """PRIMARY OUTCOME 3. Share of high-confidence calls that turned out wrong."""
    confidences = np.asarray(list(confidences), dtype=float)
    correct = np.asarray(list(correct), dtype=bool)
    loud = confidences >= threshold
    if not loud.any():
        return float("nan")
    return float((~correct[loud]).mean())


def reliability_curve(confidences, correct, n_bins: int = 10):
    """(bin_midpoint, empirical_accuracy, count) per bin, for the diagram."""
    confidences = np.asarray(list(confidences), dtype=float)
    correct = np.asarray(list(correct), dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    midpoints = (edges[:-1] + edges[1:]) / 2
    return [
        (float(mid), float(correct[mask].mean()) if count else float("nan"), count)
        for mid, (mask, count) in zip(midpoints, _bins(confidences, n_bins))
    ]


def post_jump_rmse_by_sign(
    prices, fundamental, jump_times, window: int = DEFAULT_POST_JUMP_WINDOW
) -> dict:
    """Post-jump RMSE split by the direction of the jump.

    The asymmetric-conviction prediction lives here: if an arm is less willing
    to sell than to buy at equal mispricing, its market should be slower to
    find a fundamental that jumped DOWN than one that jumped UP.
    """
    n = len(fundamental)
    errors: dict[str, list[float]] = {"up": [], "down": []}

    for jump in jump_times:
        if jump == 0 or jump >= n:
            continue
        direction = fundamental[jump] - fundamental[jump - 1]
        if direction == 0:
            continue
        bucket = errors["up"] if direction > 0 else errors["down"]
        for t in range(jump, min(jump + window, n)):
            if not _is_missing(prices[t]):
                bucket.append((prices[t] - fundamental[t]) ** 2)

    return {key: _rmse(values) for key, values in errors.items()}
