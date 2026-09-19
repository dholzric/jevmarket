"""Does the market stop trading after a jump, and asymmetrically?

The confirmatory run returned a null on post-jump RMSE. Investigating the one
NaN cell-seed showed why: in that run `jev_argmax/original` had ZERO trades in
all three up-jump windows and full trading in all three down-jump windows.

RMSE is computed only over periods that traded, so it silently discards the
periods where the effect is strongest. The effect is not that price is wrong
after a jump -- it is that the market HALTS after a jump, on one side only.

Mechanism: under the original wording buy conviction is ~0.99 with almost no
`pass` mass, so after an up jump every trader wants to buy, there is no
counterparty, and no trade can occur. After a down jump the sell side carries
21-27% `pass` mass, selling is less unanimous, and dispersion keeps producing
buyers.

Everything here replays from cache: no API calls, no cost.

    python scripts/trade_cessation.py --seeds 20 --seed-offset 4
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.fundamental import MatchedJumpFundamental, Signal  # noqa: E402
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.client import JevClient  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.simulation import RunConfig, run  # noqa: E402

CELLS = [
    ("jev_argmax", "original"), ("jev_argmax", "mirror"),
    ("jev_sample", "original"), ("jev_sample", "mirror"),
    ("zi", "original"), ("nbr", "original"),
]


def traded_share(result, window):
    """Share of post-jump periods that produced a trade, split by jump sign."""
    path = result.fundamental_path
    out = {"up": [], "down": []}
    for jump in result.jump_times:
        if jump == 0 or jump >= len(path):
            continue
        key = "up" if path[jump] > path[jump - 1] else "down"
        periods = result.trade_prices[jump:jump + window]
        if periods:
            out[key].append(sum(1 for p in periods if p is not None) / len(periods))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--seed-offset", type=int, default=4)
    parser.add_argument("--periods", type=int, default=160)
    parser.add_argument("--traders", type=int, default=8)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/cessation.json"))
    args = parser.parse_args(argv)

    client = JevClient(HttpTransport(), cache=DecisionCache("data/cache"))
    seeds = range(args.seed_offset, args.seed_offset + args.seeds)
    summary = {}

    print(f"{'cell':>22} {'up traded':>11} {'down traded':>13} {'down - up':>11}")
    print("-" * 60)
    for arm, wording in CELLS:
        name = f"{arm}/{wording}" if arm.startswith("jev") else arm
        ups, downs, per_seed = [], [], []
        for seed in seeds:
            fundamental = MatchedJumpFundamental(
                initial=100.0, jump_size=10.0, period_gap=20, seed=1000 + seed
            )
            result = run(
                RunConfig(
                    n_traders=args.traders, periods=args.periods, seed=seed, arm=arm,
                    wording=wording, burn_in_periods=5 if arm.startswith("jev") else 0,
                    fundamental=fundamental, signal=Signal(seed=seed),
                    jev_client=client if arm.startswith("jev") else None,
                )
            )
            shares = traded_share(result, args.window)
            if not shares["up"] or not shares["down"]:
                continue
            u, d = statistics.fmean(shares["up"]), statistics.fmean(shares["down"])
            ups.append(u)
            downs.append(d)
            per_seed.append(d - u)

        up_mean, down_mean = statistics.fmean(ups), statistics.fmean(downs)
        gap = statistics.fmean(per_seed)
        sd = statistics.stdev(per_seed) if len(per_seed) > 1 else float("nan")
        se = sd / len(per_seed) ** 0.5 if len(per_seed) > 1 else float("nan")
        summary[name] = {
            "n": len(per_seed), "up_traded": up_mean, "down_traded": down_mean,
            "gap": gap, "sd": sd, "se": se, "t": gap / se if se == se and se else None,
            "per_seed": per_seed,
        }
        print(f"{name:>22} {up_mean:>10.1%} {down_mean:>12.1%} {gap:>+10.1%}"
              f"   t={gap / se:+.1f}" if se == se and se else
              f"{name:>22} {up_mean:>10.1%} {down_mean:>12.1%} {gap:>+10.1%}")

    print("\n=== paired wording contrast on the trading-share gap ===")
    for decode in ("jev_argmax", "jev_sample"):
        original = summary[f"{decode}/original"]["per_seed"]
        mirror = summary[f"{decode}/mirror"]["per_seed"]
        paired = [o - m for o, m in zip(original, mirror)]
        mean = statistics.fmean(paired)
        se = statistics.stdev(paired) / len(paired) ** 0.5
        print(f"  {decode:>11}  mean {mean:+.1%}  SE {se:.1%}  t={mean / se:+.2f}  "
              f"n={len(paired)}  {sum(1 for v in paired if v > 0)}/{len(paired)} positive")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
