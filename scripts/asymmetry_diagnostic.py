"""Why is the halt worse after UP jumps than DOWN jumps?

Unanimity does not explain it. Measured agreement is HIGHER after down jumps
(96%) than up jumps (92%), yet down jumps barely halt at all. So the
no-counterparty mechanism accounts for the overall level and the size-scaling
but points the wrong way for the direction.

This replays cached runs and measures, period by period around each jump, what
the order book and the order flow actually looked like. No API calls.

    python scripts/asymmetry_diagnostic.py
"""

from __future__ import annotations

import argparse
import collections
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="jev_argmax")
    parser.add_argument("--wording", default="original")
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--seed-offset", type=int, default=24)
    parser.add_argument("--traders", type=int, default=8)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--out", type=pathlib.Path,
                        default=pathlib.Path("data/asymmetry_diagnostic.json"))
    args = parser.parse_args(argv)

    client = JevClient(HttpTransport(), cache=DecisionCache("data/cache"))

    # Everything is accumulated per jump direction.
    pre = {"up": [], "down": []}          # book depth in the period BEFORE the jump
    post_bid = {"up": [], "down": []}     # bid depth in the window after
    post_ask = {"up": [], "down": []}
    actions = {"up": collections.Counter(), "down": collections.Counter()}
    empty_side = {"up": collections.Counter(), "down": collections.Counter()}
    crossable = {"up": [], "down": []}

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

            pre[key].append((result.bid_depth[jump - 1], result.ask_depth[jump - 1]))
            for t in range(jump, min(jump + args.window, len(path))):
                post_bid[key].append(result.bid_depth[t])
                post_ask[key].append(result.ask_depth[t])
                for record in by_period[t]:
                    actions[key][record.decision.action.value] += 1
                if result.trade_prices[t] is None:
                    bids, asks = result.bid_depth[t], result.ask_depth[t]
                    if bids == 0 and asks == 0:
                        empty_side[key]["book empty"] += 1
                    elif asks == 0:
                        empty_side[key]["bids only (no seller)"] += 1
                    elif bids == 0:
                        empty_side[key]["asks only (no buyer)"] += 1
                    else:
                        empty_side[key]["both sides, no cross"] += 1
                        crossable[key].append(t)

    print(f"arm = {args.arm}/{args.wording}, {args.traders} traders, "
          f"seeds {args.seed_offset}-{args.seed_offset + args.seeds - 1}\n")

    print("=== book depth in the period BEFORE each jump ===")
    for key in ("up", "down"):
        bids = statistics.fmean(b for b, _ in pre[key])
        asks = statistics.fmean(a for _, a in pre[key])
        print(f"  before {key:>4} jump:  bids {bids:5.2f}   asks {asks:5.2f}")

    print("\n=== average book depth during the post-jump window ===")
    for key in ("up", "down"):
        print(f"  after  {key:>4} jump:  bids {statistics.fmean(post_bid[key]):5.2f}"
              f"   asks {statistics.fmean(post_ask[key]):5.2f}")

    print("\n=== order flow during the post-jump window ===")
    for key in ("up", "down"):
        total = sum(actions[key].values())
        parts = "  ".join(f"{a} {actions[key][a] / total:5.1%}"
                          for a in ("buy", "sell", "pass"))
        print(f"  after  {key:>4} jump:  {parts}")

    print("\n=== why each SILENT post-jump period was silent ===")
    for key in ("up", "down"):
        total = sum(empty_side[key].values()) or 1
        print(f"  after {key} jump ({total} silent periods):")
        for reason, count in empty_side[key].most_common():
            print(f"      {reason:<26} {count:>5}  ({count / total:5.1%})")

    payload = {
        "arm": args.arm,
        "pre_jump_depth": {k: {"bids": statistics.fmean(b for b, _ in v),
                               "asks": statistics.fmean(a for _, a in v)}
                           for k, v in pre.items()},
        "post_jump_depth": {k: {"bids": statistics.fmean(post_bid[k]),
                                "asks": statistics.fmean(post_ask[k])}
                            for k in ("up", "down")},
        "order_flow": {k: dict(actions[k]) for k in ("up", "down")},
        "silence_reasons": {k: dict(empty_side[k]) for k in ("up", "down")},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
