"""Order flow by period after a shock, not averaged over the whole window.

Reviewers caught the paper narrating a fifteen-period window average as though
it described the instant after the shock. It does not: at the shock itself the
modal arm takes the correct side on both up and down shocks. The sell majority
disappears by the next period, once the book starts to move.

This writes data/lag_flow.json, which the manuscript audit checks the
order-flow table against. Replays from cache; no API calls.

    python scripts/lag_flow.py
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.fundamental import MatchedJumpFundamental, Signal  # noqa: E402
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.client import JevClient  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.simulation import RunConfig, run  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="jev_argmax")
    parser.add_argument("--wording", default="original")
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--seed-offset", type=int, default=24)
    parser.add_argument("--traders", type=int, default=8)
    parser.add_argument("--lags", type=int, default=5)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/lag_flow.json"))
    args = parser.parse_args(argv)

    client = JevClient(HttpTransport(), cache=DecisionCache("data/cache"))
    lag = {"up": collections.defaultdict(collections.Counter),
           "down": collections.defaultdict(collections.Counter)}
    window = {"up": collections.Counter(), "down": collections.Counter()}

    for seed in range(args.seed_offset, args.seed_offset + args.seeds):
        fundamental = MatchedJumpFundamental(
            initial=100.0, jump_size=10.0, period_gap=20, seed=1000 + seed
        )
        result = run(
            RunConfig(
                n_traders=args.traders, periods=160, seed=seed, arm=args.arm,
                wording=args.wording, burn_in_periods=5,
                fundamental=fundamental, signal=Signal(seed=seed),
                jev_client=client if args.arm.startswith("jev") else None,
            )
        )
        path = result.fundamental_path
        by_period = collections.defaultdict(list)
        for record in result.decisions:
            by_period[record.period].append(record)

        for jump in result.jump_times:
            if jump == 0 or jump >= len(path):
                continue
            key = "up" if path[jump] > path[jump - 1] else "down"
            for offset in range(args.window):
                t = jump + offset
                if t >= len(path):
                    break
                for record in by_period[t]:
                    action = record.decision.action.value
                    window[key][action] += 1
                    if offset < args.lags:
                        lag[key][offset][action] += 1

    def share(counter):
        total = sum(counter.values()) or 1
        return {a: counter[a] / total for a in ("buy", "sell", "pass")}

    payload = {str(o): {k: share(lag[k][o]) for k in ("up", "down")}
               for o in range(args.lags)}
    payload["window"] = {k: share(window[k]) for k in ("up", "down")}

    header = f"{'period':>8} {'up buy/sell/pass':>26} {'down buy/sell/pass':>26}"
    print(f"{args.arm}/{args.wording}, {args.traders} traders, "
          f"seeds {args.seed_offset}-{args.seed_offset + args.seeds - 1}\n")
    print(header)
    print("-" * len(header))
    for key in [str(o) for o in range(args.lags)] + ["window"]:
        row = []
        for direction in ("up", "down"):
            s = payload[key][direction]
            row.append(f"{s['buy']:6.1%} /{s['sell']:6.1%} /{s['pass']:6.1%}")
        label = key if key == "window" else (f"t+{key}" if key != "0" else "t")
        print(f"{label:>8} {row[0]:>26} {row[1]:>26}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
