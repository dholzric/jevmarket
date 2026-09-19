"""Does Jev's sell-side hesitancy slow the market down after negative shocks?

The probe found Jev is ~0.23 less confident when disposing than when acquiring
at equal mispricing, with the missing mass sitting on `pass`. `jev_argmax`
discards that -- it takes the mode, which is correct on both sides. `jev_sample`
draws from the distribution, so the hesitancy becomes real passes, real missing
sell-side liquidity, and (the prediction) slower repricing after DOWN jumps.

Prediction, stated before the run:

    jev_sample:  post-jump RMSE(down) > post-jump RMSE(up)
    jev_argmax:  no such gap
    zi:          no such gap (it is symmetric by construction)

    python scripts/jev_market_asymmetry.py --periods 120 --traders 12 --seeds 1
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.fundamental import (  # noqa: E402
    Fundamental,
    MatchedJumpFundamental,
    Signal,
)
from jevmarket.jev.budget import (  # noqa: E402
    JEV_PRICING_ESTIMATE,
    BudgetExceeded,
    SpendGate,
)
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.client import JevClient  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.metrics import (  # noqa: E402
    post_jump_rmse,
    post_jump_rmse_by_sign,
    rmse_vs_fundamental,
)
from jevmarket.simulation import RunConfig, run  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", type=int, default=120)
    parser.add_argument("--traders", type=int, default=12)
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--seed-offset", type=int, default=0,
                        help="first seed; use to run seeds disjoint from an earlier sweep")
    parser.add_argument("--jump-prob", type=float, default=0.06)
    parser.add_argument("--jump-sd", type=float, default=10.0)
    parser.add_argument("--burn-in", type=int, default=5)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--max-calls", type=int, default=40_000)
    parser.add_argument("--max-usd", type=float, default=2.0)
    parser.add_argument("--matched", action="store_true",
                        help="use MatchedJumpFundamental (paired up/down windows)")
    parser.add_argument("--period-gap", type=int, default=20)
    parser.add_argument(
        "--cells",
        default="zi/-,jev_argmax/original,jev_sample/original,jev_argmax/mirror,jev_sample/mirror",
        help="comma-separated arm/wording pairs",
    )
    parser.add_argument("--cache", type=pathlib.Path, default=pathlib.Path("data/cache"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/market_asymmetry.json"))
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    gate = SpendGate(
        max_calls=args.max_calls, max_usd=args.max_usd, pricing=JEV_PRICING_ESTIMATE
    )
    client = JevClient(HttpTransport(), cache=DecisionCache(args.cache), budget=gate)

    cells = [c.split("/") for c in args.cells.split(",")]
    results = []
    for arm, wording in cells:
        for seed in range(args.seed_offset, args.seed_offset + args.seeds):
            if args.matched:
                fundamental = MatchedJumpFundamental(
                    initial=100.0, jump_size=args.jump_sd,
                    period_gap=args.period_gap, seed=1000 + seed,
                )
            else:
                fundamental = Fundamental(
                    initial=100.0, jump_prob=args.jump_prob,
                    jump_sd=args.jump_sd, seed=1000 + seed,
                )
            config = RunConfig(
                n_traders=args.traders,
                periods=args.periods,
                seed=seed,
                arm=arm,
                burn_in_periods=args.burn_in if arm != "zi" else 0,
                wording=wording if wording != "-" else "original",
                fundamental=fundamental,
                signal=Signal(delay=0, noise_sd=0.0, seed=seed),
                jev_client=client if arm.startswith("jev") else None,
            )
            try:
                result = run(config)
            except BudgetExceeded as error:
                print(f"\nSTOPPED by the spend gate during {arm} seed {seed}: {error}")
                print(json.dumps(gate.summary(), indent=2))
                return 1

            result.exchange.check_invariants()
            by_sign = post_jump_rmse_by_sign(
                result.trade_prices, result.fundamental_path,
                result.jump_times, window=args.window,
            )
            passes = sum(
                1 for d in result.decisions
                if d.arm == arm and d.decision.action.value == "pass"
            )
            acted = sum(1 for d in result.decisions if d.arm == arm)
            results.append(
                {
                    "arm": arm,
                    "wording": wording,
                    "cell": f"{arm}/{wording}",
                    "seed": seed,
                    "jumps": len(result.jump_times),
                    "trades": result.exchange.trade_count,
                    "rmse": rmse_vs_fundamental(result.trade_prices, result.fundamental_path),
                    "post_jump": post_jump_rmse(
                        result.trade_prices, result.fundamental_path,
                        result.jump_times, window=args.window),
                    "post_jump_up": by_sign["up"],
                    "post_jump_down": by_sign["down"],
                    "pass_rate": passes / acted if acted else float("nan"),
                }
            )
            row = results[-1]
            print(
                f"{arm + '/' + wording:>22} seed {seed}  trades {row['trades']:>5}  "
                f"RMSE {row['rmse']:>6.2f}  post-jump {row['post_jump']:>6.2f}  "
                f"up {row['post_jump_up']:>6.2f}  down {row['post_jump_down']:>6.2f}  "
                f"pass {row['pass_rate']:>5.1%}"
            )

    print("\n=== the prediction: a gap in exactly one cell ===")
    print(f"{'cell':>22} {'up':>8} {'down':>8} {'down - up':>11} {'pass rate':>10}")
    print("-" * 62)
    gaps = {}
    for arm, wording in cells:
        name = f"{arm}/{wording}"
        rows = [r for r in results if r["cell"] == name]
        if not rows:
            continue
        up = sum(r["post_jump_up"] for r in rows) / len(rows)
        down = sum(r["post_jump_down"] for r in rows) / len(rows)
        passes = sum(r["pass_rate"] for r in rows) / len(rows)
        gaps[name] = down - up
        print(f"{name:>22} {up:>8.2f} {down:>8.2f} {down - up:>+11.2f} {passes:>10.1%}")

    predicted = gaps.get("jev_sample/original")
    controls = [v for k, v in gaps.items() if k != "jev_sample/original"]
    if predicted is not None and controls:
        print(f"\n  predicted cell (jev_sample/original) gap {predicted:+.2f}")
        print(f"  largest control gap in magnitude          "
              f"{max(controls, key=abs):+.2f}")
        if predicted > max(abs(c) for c in controls):
            print("  -> the gap is where the theory says it should be")
        else:
            print("  -> NOT cleanly isolated to the predicted cell")

    print("\n=== cost ===")
    print(json.dumps(gate.summary(), indent=2))
    print(f"cache hit rate {client.cache.hit_rate:.1%}")
    if gate.calls:
        print(f"mean input tokens/call {gate.input_tokens / gate.calls:.0f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"args": vars(args) | {"cache": str(args.cache), "out": str(args.out)},
                    "results": results, "cost": gate.summary()}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
