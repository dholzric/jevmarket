"""Confirmatory test of the trade-cessation finding. Registered as prereg 10b.

D1  jev_argmax: traded_share(down) - traded_share(up) > 0
D2  that gap is larger for jev_argmax than for jev_sample

Fresh seeds, disjoint from every seed used before. Also records, as an
exploratory diagnostic only, WHY periods failed to trade: one side of the book
empty (no counterparty) versus both sides present but not crossing.

    python scripts/cessation_confirm.py --seeds 20 --seed-offset 24
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

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

CELLS = [("jev_argmax", "original"), ("jev_sample", "original"), ("zi", None), ("nbr", None)]


def measure(result, window):
    """Per jump direction: share of post-jump periods that traded, plus why not."""
    path = result.fundamental_path
    traded = {"up": [], "down": []}
    one_sided = {"up": [], "down": []}
    for jump in result.jump_times:
        if jump == 0 or jump >= len(path):
            continue
        key = "up" if path[jump] > path[jump - 1] else "down"
        lo, hi = jump, min(jump + window, len(path))
        periods = list(range(lo, hi))
        if not periods:
            continue
        traded[key].append(
            sum(1 for t in periods if result.trade_prices[t] is not None) / len(periods)
        )
        silent = [t for t in periods if result.trade_prices[t] is None]
        if silent:
            one_sided[key].append(
                sum(
                    1 for t in silent
                    if (result.bid_depth[t] == 0) != (result.ask_depth[t] == 0)
                ) / len(silent)
            )
    return traded, one_sided


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--seed-offset", type=int, default=24)
    parser.add_argument("--periods", type=int, default=160)
    parser.add_argument("--traders", type=int, default=8)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--max-usd", type=float, default=1.6)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/cessation_confirm.json"))
    args = parser.parse_args(argv)

    gate = SpendGate(max_usd=args.max_usd, pricing=JEV_PRICING_ESTIMATE)
    client = JevClient(HttpTransport(), cache=DecisionCache("data/cache"), budget=gate)
    seeds = list(range(args.seed_offset, args.seed_offset + args.seeds))

    gaps = {}
    diagnostics = {}
    for arm, wording in CELLS:
        name = f"{arm}/{wording}" if wording else arm
        gaps[name] = {}
        diagnostics[name] = {"up": [], "down": []}
        for seed in seeds:
            fundamental = MatchedJumpFundamental(
                initial=100.0, jump_size=10.0, period_gap=20, seed=1000 + seed
            )
            try:
                result = run(
                    RunConfig(
                        n_traders=args.traders, periods=args.periods, seed=seed,
                        arm=arm, wording=wording or "original",
                        burn_in_periods=5 if arm.startswith("jev") else 0,
                        fundamental=fundamental, signal=Signal(seed=seed),
                        jev_client=client if arm.startswith("jev") else None,
                    )
                )
            except BudgetExceeded as error:
                print(f"\nSTOPPED by the spend gate in {name} seed {seed}: {error}")
                print(json.dumps(gate.summary(), indent=2))
                return 1
            result.exchange.check_invariants()
            traded, one_sided = measure(result, args.window)
            if traded["up"] and traded["down"]:
                gaps[name][seed] = (
                    statistics.fmean(traded["down"]) - statistics.fmean(traded["up"])
                )
            for key in ("up", "down"):
                if one_sided[key]:
                    diagnostics[name][key].append(statistics.fmean(one_sided[key]))
        series = list(gaps[name].values())
        mean = statistics.fmean(series)
        se = statistics.stdev(series) / len(series) ** 0.5
        print(f"{name:>22}  n={len(series):>2}  gap {mean:>+7.1%}  SE {se:>5.1%}  t={mean/se:>+5.2f}")

    # Pair by explicit seed key. Zipping dict values happens to work while
    # insertion order matches, which is a silent correctness dependency.
    argmax_by_seed = gaps["jev_argmax/original"]
    sample_by_seed = gaps["jev_sample/original"]
    common = sorted(set(argmax_by_seed) & set(sample_by_seed))
    assert set(argmax_by_seed) == set(sample_by_seed), (
        f"cells cover different seeds: "
        f"{sorted(set(argmax_by_seed) ^ set(sample_by_seed))}"
    )
    argmax = [argmax_by_seed[s] for s in common]
    sample = [sample_by_seed[s] for s in common]

    def one_sided_t(values, alternative="greater"):
        mean, sd = statistics.fmean(values), statistics.stdev(values)
        se = sd / len(values) ** 0.5
        t = mean / se
        p = st.t.sf(t, len(values) - 1) if alternative == "greater" else st.t.cdf(t, len(values) - 1)
        lo, hi = st.t.interval(0.95, len(values) - 1, loc=mean, scale=se)
        return mean, se, t, p, lo, hi

    print(f"\n=== D1 (primary): jev_argmax gap > 0, n={len(argmax)} ===")
    m, se, t, p1, lo, hi = one_sided_t(argmax)
    print(f"  mean {m:+.1%}  SE {se:.1%}  t={t:+.2f}  p={p1:.5f}  95% CI [{lo:+.1%}, {hi:+.1%}]")
    print(f"  {sum(1 for v in argmax if v > 0)}/{len(argmax)} seeds positive")

    print(f"\n=== D2 (primary): argmax gap > sample gap, n={len(common)} ===")
    m2, se2, t2, p2, lo2, hi2 = one_sided_t([a - b for a, b in zip(argmax, sample)])
    print(f"  jev_sample gap mean {statistics.fmean(sample):+.1%}")
    print(f"  difference mean {m2:+.1%}  SE {se2:.1%}  t={t2:+.2f}  p={p2:.5f}  "
          f"95% CI [{lo2:+.1%}, {hi2:+.1%}]")

    print("\n=== Holm across D1/D2 ===")
    ps = {"D1": p1, "D2": p2}
    for rank, (name, p) in enumerate(sorted(ps.items(), key=lambda kv: kv[1])):
        adj = min(1.0, p * (len(ps) - rank))
        print(f"  {name}  raw p={p:.5f}  ->  Holm p={adj:.5f}   "
              f"{'SIGNIFICANT' if adj < 0.05 else 'NOT significant'}")

    print("\n=== controls (must stay on zero) ===")
    for name in ("zi", "nbr"):
        series = list(gaps[name].values())
        mean = statistics.fmean(series)
        se = statistics.stdev(series) / len(series) ** 0.5
        print(f"  {name:>4}  gap {mean:+.1%}  SE {se:.1%}  t={mean/se:+.2f}")

    print("\n=== mechanism diagnostic (EXPLORATORY, not a test) ===")
    print("  of the silent post-jump periods, share where one side of the book was empty")
    print(f"  {'cell':>22} {'after UP':>10} {'after DOWN':>12}")
    for name in diagnostics:
        up = diagnostics[name]["up"]
        down = diagnostics[name]["down"]
        if up and down:
            print(f"  {name:>22} {statistics.fmean(up):>10.1%} {statistics.fmean(down):>12.1%}")

    print("\n=== cost ===")
    print(json.dumps(gate.summary(), indent=2))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"gaps": gaps, "diagnostics": diagnostics, "cost": gate.summary()},
                   indent=2, default=str), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
