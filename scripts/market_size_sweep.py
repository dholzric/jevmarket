"""Market-size sweep: robustness check and mechanism test. Prereg 10c.

E1  the jev_argmax up/down trading gap DECREASES with market size
E2  the jev_sample gap shows no such decay

If the halt is caused by every trader reaching the same conclusion, then with
~92% agreement the chance all N agree is ~0.92^N, and halting must fall steeply
as the market grows. A flat or rising argmax gap falsifies the mechanism.

    python scripts/market_size_sweep.py --sizes 4,16,32 --seeds 10
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

import numpy as np
import scipy.stats as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.fundamental import MatchedJumpFundamental, Signal  # noqa: E402
from jevmarket.jev.budget import (  # noqa: E402
    JEV_PRICING_ESTIMATE,
    BudgetExceeded,
    SpendGate,
)
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.client import JevClient  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.simulation import RunConfig, run  # noqa: E402

AGREEMENT = 0.92  # measured in the rounding probe


def gap_and_levels(result, window):
    path = result.fundamental_path
    traded = {"up": [], "down": []}
    for jump in result.jump_times:
        if jump == 0 or jump >= len(path):
            continue
        key = "up" if path[jump] > path[jump - 1] else "down"
        periods = list(range(jump, min(jump + window, len(path))))
        if periods:
            traded[key].append(
                sum(1 for t in periods if result.trade_prices[t] is not None) / len(periods)
            )
    if not traded["up"] or not traded["down"]:
        return None
    up, down = statistics.fmean(traded["up"]), statistics.fmean(traded["down"])
    return {"up": up, "down": down, "gap": down - up}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="4,8,16,32")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--seed-offset", type=int, default=24)
    parser.add_argument("--periods", type=int, default=160)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--max-usd", type=float, default=4.0)
    parser.add_argument("--out", type=pathlib.Path,
                        default=pathlib.Path("data/market_size.json"))
    args = parser.parse_args(argv)

    sizes = [int(x) for x in args.sizes.split(",")]
    seeds = list(range(args.seed_offset, args.seed_offset + args.seeds))
    gate = SpendGate(max_usd=args.max_usd, pricing=JEV_PRICING_ESTIMATE)
    client = JevClient(HttpTransport(), cache=DecisionCache("data/cache"), budget=gate)

    results = {}
    print(f"{'cell':>13} {'N':>4} {'up traded':>11} {'down traded':>12} {'gap':>9} {'predicted':>11}")
    print("-" * 66)
    for arm in ("jev_argmax", "jev_sample", "zi", "nbr"):
        for size in sizes:
            rows = []
            for seed in seeds:
                fundamental = MatchedJumpFundamental(
                    initial=100.0, jump_size=10.0, period_gap=20, seed=1000 + seed
                )
                try:
                    result = run(
                        RunConfig(
                            n_traders=size, periods=args.periods, seed=seed, arm=arm,
                            wording="original", burn_in_periods=5,
                            fundamental=fundamental, signal=Signal(seed=seed),
                            jev_client=client if arm.startswith("jev") else None,
                        )
                    )
                except BudgetExceeded as error:
                    print(f"\nSTOPPED by the spend gate at {arm} N={size} seed {seed}: {error}")
                    print(json.dumps(gate.summary(), indent=2))
                    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
                    return 1
                measured = gap_and_levels(result, args.window)
                if measured:
                    rows.append(measured)

            up = statistics.fmean(r["up"] for r in rows)
            down = statistics.fmean(r["down"] for r in rows)
            gaps = [r["gap"] for r in rows]
            results[f"{arm}|{size}"] = {"n": len(rows), "up": up, "down": down,
                                        "gaps": gaps, "gap": statistics.fmean(gaps)}
            predicted = 1 - AGREEMENT ** size if arm == "jev_argmax" else float("nan")
            note = f"{predicted:>10.0%}" if predicted == predicted else f"{'-':>10}"
            print(f"{arm:>13} {size:>4} {up:>10.1%} {down:>11.1%} "
                  f"{statistics.fmean(gaps):>+8.1%} {note}")

    print("\n=== E1 / E2: slope of the gap on log2(market size) ===")
    ps = {}
    for label, arm in (("E1", "jev_argmax"), ("E2", "jev_sample")):
        xs, ys = [], []
        for size in sizes:
            for g in results[f"{arm}|{size}"]["gaps"]:
                xs.append(np.log2(size))
                ys.append(g)
        fit = st.linregress(xs, ys)
        # one-sided: E1 predicts a negative slope
        p = fit.pvalue / 2 if fit.slope < 0 else 1 - fit.pvalue / 2
        ps[label] = p
        print(f"  {label} {arm:>12}  slope {fit.slope:+.3f} per doubling  "
              f"SE {fit.stderr:.3f}  t={fit.slope / fit.stderr:+.2f}  one-sided p={p:.5f}")

    print("\n=== Holm across E1/E2 ===")
    for rank, (name, p) in enumerate(sorted(ps.items(), key=lambda kv: kv[1])):
        adj = min(1.0, p * (len(ps) - rank))
        print(f"  {name}  raw p={p:.5f}  ->  Holm p={adj:.5f}   "
              f"{'SIGNIFICANT' if adj < 0.05 else 'NOT significant'}")

    print("\n=== cost ===")
    print(json.dumps(gate.summary(), indent=2))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
