"""Is the buy/sell asymmetry in Jev, or in our prompt?

The earlier probe ruled out price level, option order, and the option NAMES.
It did NOT rule out our criterion descriptions, which were not perfectly
symmetric: "underpriced / you want to acquire" vs "overpriced / you want to
dispose", under instructions that name buying first.

This script strips that out. `mirror` uses neutral labels, neutral
instructions, and two descriptions that are exact structural mirrors differing
only in the direction of one comparison. If the asymmetry survives that, it is
Jev. If it collapses, it was ours.

    python scripts/jev_wording.py
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.decision import load_schema  # noqa: E402
from jevmarket.jev.budget import SpendGate  # noqa: E402
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.jev.transport import JevRequest  # noqa: E402

SCHEMA = load_schema()
EDGES = [-12, -8, -4, -2, 2, 4, 8, 12]

NEUTRAL_INSTRUCTIONS = (
    "A trader holds a private value for one unit of a good and faces a market "
    "with a current price. Select the option that describes the trader's "
    "situation and the action it implies."
)

ABOVE = "The trader's private value is above the current market price. The trader should transact in the direction that profits from that gap."
BELOW = "The trader's private value is below the current market price. The trader should transact in the direction that profits from that gap."
EQUAL = "The trader's private value is at the current market price. No action is implied."

GAIN_BUY = "The good is cheap relative to the trader's private value. Acquiring one unit would gain the trader the difference."
GAIN_SELL = "The good is dear relative to the trader's private value. Disposing of one unit would gain the trader the difference."
GAIN_NONE = "The good is priced at the trader's private value. Neither action gains the trader anything."

ORIGINAL = SCHEMA["questions"]["action"]


def question(instructions: str, criteria: dict) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


VARIANTS = {
    # Our original wording, for reference.
    "original": (
        question(ORIGINAL["instructions"], dict(ORIGINAL["criteria"])),
        {"buy": "acquire", "sell": "dispose", "pass": "hold"},
    ),
    # Neutral labels, neutral instructions, exact mirror descriptions.
    "mirror": (
        question(NEUTRAL_INSTRUCTIONS, {"option_a": ABOVE, "option_b": BELOW, "option_c": EQUAL}),
        {"option_a": "acquire", "option_b": "dispose", "option_c": "hold"},
    ),
    # Same, with the two directions listed in the opposite order.
    "mirror_reversed": (
        question(NEUTRAL_INSTRUCTIONS, {"option_a": BELOW, "option_b": ABOVE, "option_c": EQUAL}),
        {"option_a": "dispose", "option_b": "acquire", "option_c": "hold"},
    ),
    # buy/sell labels back, but both sides framed as an equal gain.
    "gain_framed": (
        question(NEUTRAL_INSTRUCTIONS, {"buy": GAIN_BUY, "sell": GAIN_SELL, "pass": GAIN_NONE}),
        {"buy": "acquire", "sell": "dispose", "pass": "hold"},
    ),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/wording.json"))
    args = parser.parse_args(argv)

    transport = HttpTransport()
    gate = SpendGate(max_calls=args.max_calls)
    bid, ask = 99, 101
    mid = (bid + ask) / 2

    summary = {}
    all_rows = []

    for name, (action_question, meaning) in VARIANTS.items():
        cache = DecisionCache(pathlib.Path("data/cache_wording") / name)
        print(f"\n=== {name} ===")
        print(f"{'edge':>6} {'chose':>8} {'p(correct)':>11} {'p(hold)':>9}")
        print("-" * 37)

        rows = []
        for edge in EDGES:
            value = int(mid + edge)
            request = JevRequest(
                model=SCHEMA["model"],
                state={
                    "best_bid": bid, "best_ask": ask, "spread": ask - bid,
                    "last_trade_price": int(mid),
                    "your_private_value": value, "your_signal": value,
                },
                questions={"action": action_question},
                schema_version=f"wording:{name}",
            )
            cached = cache.get(request)
            if cached is not None:
                response = cached
                gate.note_cache_hit()
            else:
                response = transport.send(request)
                gate.charge(response.input_tokens, response.output_tokens)
                cache.put(request, response)

            answer = response.answers["action"]
            by_meaning = {meaning[k]: v for k, v in answer["probabilities"].items()}
            correct = "acquire" if edge > 0 else "dispose"
            rows.append({"variant": name, "edge": edge, "chosen": meaning[answer["choice"]],
                         "correct_side": correct, "p_correct": by_meaning[correct],
                         "p_hold": by_meaning["hold"], "probabilities": by_meaning})
            flag = "" if rows[-1]["chosen"] == correct else "  <- WRONG"
            print(f"{edge:>6} {rows[-1]['chosen']:>8} {by_meaning[correct]:>11.3f} "
                  f"{by_meaning['hold']:>9.3f}{flag}")

        acquire = [r["p_correct"] for r in rows if r["edge"] > 0]
        dispose = [r["p_correct"] for r in rows if r["edge"] < 0]
        gap = sum(acquire) / len(acquire) - sum(dispose) / len(dispose)
        summary[name] = {
            "mean_p_acquire": sum(acquire) / len(acquire),
            "mean_p_dispose": sum(dispose) / len(dispose),
            "asymmetry": gap,
        }
        print(f"\n  acquire {summary[name]['mean_p_acquire']:.3f}   "
              f"dispose {summary[name]['mean_p_dispose']:.3f}   "
              f"ASYMMETRY {gap:+.3f}")
        all_rows += rows

    print("\n=== verdict ===")
    print(f"{'variant':<18} {'acquire':>9} {'dispose':>9} {'asymmetry':>11}")
    print("-" * 50)
    for name, values in summary.items():
        print(f"{name:<18} {values['mean_p_acquire']:>9.3f} "
              f"{values['mean_p_dispose']:>9.3f} {values['asymmetry']:>+11.3f}")

    mirror_gap = summary["mirror"]["asymmetry"]
    original_gap = summary["original"]["asymmetry"]
    print()
    if abs(mirror_gap) < 0.05:
        print(f"Mirror wording asymmetry is {mirror_gap:+.3f}: the effect was OURS, "
              f"not Jev's. The original {original_gap:+.3f} came from the prompt.")
    elif mirror_gap > 0.5 * original_gap:
        print(f"Mirror wording still shows {mirror_gap:+.3f} vs original "
              f"{original_gap:+.3f}: the effect is substantially JEV'S.")
    else:
        print(f"Mirror {mirror_gap:+.3f} vs original {original_gap:+.3f}: mixed. "
              f"Some of the effect is ours, some is Jev's.")

    print(f"\nlive calls {gate.calls}, tokens {gate.input_tokens}/{gate.output_tokens}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"rows": all_rows, "summary": summary}, indent=2),
                        encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
