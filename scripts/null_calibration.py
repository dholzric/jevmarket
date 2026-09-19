"""Null calibration of the up/down gap, from the two free symmetric arms.

`zi` and `nbr` are symmetric by construction, so whatever gap they show IS the
measurement noise of the design. Running them costs no API calls, so this can
be run at whatever n the paper needs.

Answers two questions the Jev cells cannot:
  1. is the matched-jump design unbiased? (mean gap should be ~0)
  2. how many seeds does an effect of size d need? (from the observed sd)

    python scripts/null_calibration.py --seeds 40
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.fundamental import MatchedJumpFundamental, Signal  # noqa: E402
from jevmarket.metrics import post_jump_rmse_by_sign  # noqa: E402
from jevmarket.simulation import RunConfig, run  # noqa: E402


def gaps(arm, seeds, periods, traders, jump_size, period_gap, window):
    out = []
    for seed in range(seeds):
        fundamental = MatchedJumpFundamental(
            initial=100.0, jump_size=jump_size, period_gap=period_gap, seed=1000 + seed
        )
        result = run(
            RunConfig(
                n_traders=traders, periods=periods, seed=seed, arm=arm,
                fundamental=fundamental, signal=Signal(seed=seed),
            )
        )
        by_sign = post_jump_rmse_by_sign(
            result.trade_prices, result.fundamental_path,
            result.jump_times, window=window,
        )
        if by_sign["up"] == by_sign["up"] and by_sign["down"] == by_sign["down"]:
            out.append(by_sign["down"] - by_sign["up"])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--periods", type=int, default=160)
    parser.add_argument("--traders", type=int, default=8)
    parser.add_argument("--jump-size", type=float, default=10.0)
    parser.add_argument("--period-gap", type=int, default=20)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/null.json"))
    args = parser.parse_args(argv)

    summary = {}
    print(f"{'arm':>5} {'n':>4} {'mean':>8} {'sd':>7} {'SE':>7} {'t':>7}   95% per-run range")
    print("-" * 66)
    for arm in ("zi", "nbr"):
        series = gaps(arm, args.seeds, args.periods, args.traders,
                      args.jump_size, args.period_gap, args.window)
        mean = statistics.fmean(series)
        sd = statistics.stdev(series)
        se = sd / len(series) ** 0.5
        lo, hi = np.quantile(series, [0.025, 0.975])
        summary[arm] = {"n": len(series), "mean": mean, "sd": sd, "se": se,
                        "t": mean / se, "gaps": series}
        print(f"{arm:>5} {len(series):>4} {mean:>+8.3f} {sd:>7.3f} {se:>7.3f} "
              f"{mean / se:>+7.2f}   [{lo:+.2f}, {hi:+.2f}]")

    sd = summary["zi"]["sd"]
    print(f"\nper-run noise sd = {sd:.2f}")
    print("seeds needed per cell for 80% power on an UNPAIRED comparison:")
    for d in (0.2, 0.4, 0.6, 0.8):
        print(f"   effect {d:.1f} -> n ~ {8 * (sd / d) ** 2:5.0f}")
    print("\nThe paired wording contrast cancels the shared fundamental path and")
    print("private-value draws, which is most of that sd -- which is why the")
    print("primary test is paired and not a comparison of cell means.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
