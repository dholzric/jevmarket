"""Does Jev ever return a non-degenerate distribution?

This decides whether `jev_sample` is a real arm. Sampling from a point mass is
argmax, so if `answers.action.probabilities` saturates at 1.0/0.0 everywhere,
H5 has no content and ECE collapses into a single bin.

Sweeps the trader's private value across the book and reports the shape of the
returned distribution at each point.

    python scripts/jev_probe.py --min 88 --max 112
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.agents.base import Observation  # noqa: E402
from jevmarket.jev.budget import SpendGate  # noqa: E402
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.client import JevClient  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402

SATURATED = 0.99


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min", type=int, default=88)
    parser.add_argument("--max", type=int, default=112)
    parser.add_argument("--step", type=int, default=2)
    parser.add_argument("--best-bid", type=int, default=99)
    parser.add_argument("--best-ask", type=int, default=101)
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--cache", type=pathlib.Path, default=pathlib.Path("data/cache"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/probe.json"))
    return parser.parse_args(argv)


def observation(value, best_bid, best_ask):
    return Observation(
        period=0,
        signal=float(value),
        private_value=float(value),
        best_bid=best_bid,
        best_ask=best_ask,
        last_price=(best_bid + best_ask) // 2,
        cash=100_000,
        inventory=50,
        available_cash=100_000,
        available_inventory=50,
    )


def main(argv=None) -> int:
    args = parse_args(argv)
    gate = SpendGate(max_calls=args.max_calls)
    client = JevClient(
        HttpTransport(), cache=DecisionCache(args.cache), budget=gate
    )

    mid = (args.best_bid + args.best_ask) / 2
    print(f"book {args.best_bid} / {args.best_ask}   mid {mid}\n")
    header = f"{'value':>6} {'edge':>6} {'action':>6} {'p(buy)':>7} {'p(sell)':>8} {'p(pass)':>8} {'max':>6} {'score':>6} {'aggr':>6} {'noul':>6}"
    print(header)
    print("-" * len(header))

    rows = []
    for value in range(args.min, args.max + 1, args.step):
        decision, response = client.decide(observation(value, args.best_bid, args.best_ask))
        probabilities = decision.action_probabilities
        peak = max(probabilities.values())
        score = response.answers["aggressiveness"]["score"]
        rows.append(
            {
                "value": value,
                "edge": value - mid,
                "action": decision.action.value,
                "probabilities": probabilities,
                "max_probability": peak,
                "score": score,
                "aggressiveness": decision.aggressiveness,
                "noul": decision.already_priced,
                "model_confidence": decision.model_confidence,
                "from_cache": response.from_cache,
            }
        )
        print(
            f"{value:>6} {value - mid:>6.1f} {decision.action.value:>6} "
            f"{probabilities['buy']:>7.3f} {probabilities['sell']:>8.3f} "
            f"{probabilities['pass']:>8.3f} {peak:>6.3f} {score:>6.2f} "
            f"{decision.aggressiveness:>6.3f} {decision.already_priced:>6.3f}"
        )

    saturated = [r for r in rows if r["max_probability"] >= SATURATED]
    print(f"\nstates probed          {len(rows)}")
    print(f"saturated (max >= {SATURATED}) {len(saturated)} / {len(rows)} "
          f"({len(saturated) / len(rows):.0%})")
    print(f"distinct actions       {sorted({r['action'] for r in rows})}")
    peaks = [r["max_probability"] for r in rows]
    print(f"max-probability range  {min(peaks):.3f} .. {max(peaks):.3f}")
    print(f"live calls             {gate.calls}  (cache hits {gate.cache_hits})")
    print(f"tokens in/out          {gate.input_tokens} / {gate.output_tokens}")

    if len(saturated) == len(rows):
        print("\nVERDICT: fully saturated everywhere. jev_sample == jev_argmax; H5 is dead.")
    elif saturated:
        print("\nVERDICT: saturates only where the edge is large. jev_sample is a real "
              "arm near the boundary, degenerate far from it.")
    else:
        print("\nVERDICT: never saturated. jev_sample is a genuinely distinct arm.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
