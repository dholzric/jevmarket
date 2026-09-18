"""Paired analysis of the matched-jump runs.

Every cell in a seed runs on the same fundamental path and the same private
value draws, so the wording contrast is paired within seed. Comparing marginal
cell means throws that away: the pilot's per-seed noise on a raw gap is ~0.8,
while the paired difference removes everything the two cells share.

Reports, per decode mode:

    gap(cell)          = RMSE(down) - RMSE(up)
    paired contrast    = gap(original) - gap(mirror), per seed
    bootstrap CI over seeds on the paired contrast

    python scripts/analyse_matched.py data/matched.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

import numpy as np


def bootstrap_ci(values, iterations=20_000, alpha=0.05, seed=0):
    values = np.asarray(values, dtype=float)
    if len(values) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(iterations, len(values)), replace=True)
    means = draws.mean(axis=1)
    return (
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="data/matched.json", type=pathlib.Path)
    args = parser.parse_args(argv)

    if not args.path.is_file():
        print(f"no results at {args.path}")
        return 1
    rows = json.loads(args.path.read_text(encoding="utf-8"))["results"]

    by_cell_seed = {(r["cell"], r["seed"]): r for r in rows}
    seeds = sorted({r["seed"] for r in rows})
    cells = sorted({r["cell"] for r in rows})

    print(f"seeds {seeds}\ncells {cells}\n")

    print("=== raw gaps, RMSE(down) - RMSE(up), per cell per seed ===")
    header = f"{'cell':>22} " + " ".join(f"{'s' + str(s):>7}" for s in seeds) + f"{'mean':>9}{'SE':>8}"
    print(header)
    print("-" * len(header))
    gaps = {}
    for cell in cells:
        series = []
        for seed in seeds:
            row = by_cell_seed.get((cell, seed))
            series.append(
                row["post_jump_down"] - row["post_jump_up"] if row else float("nan")
            )
        gaps[cell] = series
        clean = [v for v in series if v == v]
        mean = statistics.fmean(clean) if clean else float("nan")
        se = (statistics.stdev(clean) / len(clean) ** 0.5) if len(clean) > 1 else float("nan")
        print(f"{cell:>22} " + " ".join(f"{v:>7.2f}" for v in series) + f"{mean:>9.2f}{se:>8.2f}")

    print("\n=== PAIRED contrast: gap(original) - gap(mirror), within seed ===")
    print("(removes the fundamental path and the private-value draws, which both")
    print(" cells share; this is the primary test)\n")
    print(f"{'decode':>12} " + " ".join(f"{'s' + str(s):>7}" for s in seeds)
          + f"{'mean':>9}{'95% CI':>18}")
    print("-" * 80)

    any_reported = False
    for decode in ("jev_argmax", "jev_sample"):
        original = gaps.get(f"{decode}/original")
        mirror = gaps.get(f"{decode}/mirror")
        if original is None or mirror is None:
            print(f"{decode:>12}   (missing a cell — run incomplete)")
            continue
        paired = [o - m for o, m in zip(original, mirror) if o == o and m == m]
        if not paired:
            continue
        any_reported = True
        mean = statistics.fmean(paired)
        lo, hi = bootstrap_ci(paired)
        series = " ".join(f"{v:>7.2f}" for v in paired)
        print(f"{decode:>12} {series}{mean:>9.2f}   [{lo:>6.2f}, {hi:>6.2f}]")

    if any_reported:
        print("\n  A positive, CI-excludes-zero contrast is the prediction:")
        print("  the original wording slows down-jump repricing relative to mirror,")
        print("  on the same paths, with the same traders.")

    zi = gaps.get("zi/-")
    if zi:
        clean = [v for v in zi if v == v]
        lo, hi = bootstrap_ci(clean)
        print(f"\n=== control ===")
        print(f"  zi gap  mean {statistics.fmean(clean):+.2f}  95% CI [{lo:+.2f}, {hi:+.2f}]")
        print("  zi is symmetric by construction, so a CI containing 0 is the")
        print("  check that the matched-jump design is doing its job.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
