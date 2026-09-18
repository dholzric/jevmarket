"""Is Jev's buy/sell confidence asymmetry real, and what drives it?

The baseline probe found that at equal |edge| Jev is far more confident buying
than selling, keeping 20-27% mass on `pass` on the sell side and ~0% on the
buy side. The argmax is correct on both sides, so the bias is invisible in
point predictions and shows up only in the distribution.

Three confounds to kill before that is a finding:

  level   does it replicate at a different price level?
  order   is it just that "buy" is listed first in the criteria?
  label   is it the WORD "buy", or the semantics of acquiring?

The `label_swap` variant is the sharp one: the option named "sell" carries the
buy description and vice versa. If the asymmetry follows the name, it is the
word. If it follows the description, it is the semantics.

These variants deliberately do NOT touch schema_jev_v1.json. They are
diagnostics, not the frozen experiment.

    python scripts/jev_asymmetry.py
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
BASE = SCHEMA["questions"]["action"]
BUY_TEXT = BASE["criteria"]["buy"]
SELL_TEXT = BASE["criteria"]["sell"]
PASS_TEXT = BASE["criteria"]["pass"]

EDGES = [-12, -8, -4, -2, 2, 4, 8, 12]


def action_question(criteria: dict) -> dict:
    return {"type": "choice", "instructions": BASE["instructions"], "criteria": criteria}


# Each variant maps a returned option name back to its economic meaning.
VARIANTS = {
    "baseline": (
        action_question({"buy": BUY_TEXT, "sell": SELL_TEXT, "pass": PASS_TEXT}),
        {"buy": "acquire", "sell": "dispose", "pass": "hold"},
    ),
    "order_reversed": (
        action_question({"sell": SELL_TEXT, "pass": PASS_TEXT, "buy": BUY_TEXT}),
        {"buy": "acquire", "sell": "dispose", "pass": "hold"},
    ),
    "neutral_labels": (
        action_question(
            {"option_a": BUY_TEXT, "option_b": SELL_TEXT, "option_c": PASS_TEXT}
        ),
        {"option_a": "acquire", "option_b": "dispose", "option_c": "hold"},
    ),
    "label_swap": (
        # The option NAMED "sell" carries the BUY description.
        action_question({"sell": BUY_TEXT, "buy": SELL_TEXT, "pass": PASS_TEXT}),
        {"sell": "acquire", "buy": "dispose", "pass": "hold"},
    ),
}


def build(questions_action: dict, value: int, bid: int, ask: int) -> JevRequest:
    return JevRequest(
        model=SCHEMA["model"],
        state={
            "best_bid": bid,
            "best_ask": ask,
            "spread": ask - bid,
            "last_trade_price": (bid + ask) // 2,
            "your_private_value": value,
            "your_signal": value,
        },
        questions={"action": questions_action},
        schema_version="probe",
    )


def run_variant(name, questions_action, meaning, transport, gate, cache, bid, ask):
    mid = (bid + ask) / 2
    rows = []
    for edge in EDGES:
        value = int(mid + edge)
        request = build(questions_action, value, bid, ask)

        cached = cache.get(request)
        if cached is not None:
            response = cached
            gate.note_cache_hit()
        else:
            response = transport.send(request)
            gate.charge(response.input_tokens, response.output_tokens)
            cache.put(request, response)

        answer = response.answers["action"]
        # Re-key the returned distribution by economic meaning, not by label.
        by_meaning = {
            meaning[option]: probability
            for option, probability in answer["probabilities"].items()
        }
        correct = "acquire" if edge > 0 else "dispose"
        rows.append(
            {
                "variant": name,
                "book": f"{bid}/{ask}",
                "edge": edge,
                "chosen": meaning[answer["choice"]],
                "correct_side": correct,
                "p_correct_side": by_meaning[correct],
                "p_hold": by_meaning["hold"],
                "probabilities": by_meaning,
            }
        )
    return rows


def summarise(rows, title):
    print(f"\n=== {title} ===")
    print(f"{'edge':>6} {'chose':>8} {'p(correct side)':>16} {'p(hold)':>9}")
    print("-" * 43)
    for row in rows:
        flag = "" if row["chosen"] == row["correct_side"] else "  <- WRONG SIDE"
        print(
            f"{row['edge']:>6} {row['chosen']:>8} {row['p_correct_side']:>16.3f} "
            f"{row['p_hold']:>9.3f}{flag}"
        )

    buys = [r for r in rows if r["edge"] > 0]
    sells = [r for r in rows if r["edge"] < 0]
    buy_mean = sum(r["p_correct_side"] for r in buys) / len(buys)
    sell_mean = sum(r["p_correct_side"] for r in sells) / len(sells)
    print(f"\n  mean p(correct) when acquiring is right: {buy_mean:.3f}")
    print(f"  mean p(correct) when disposing is right: {sell_mean:.3f}")
    print(f"  ASYMMETRY (acquire - dispose):            {buy_mean - sell_mean:+.3f}")
    return buy_mean - sell_mean


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/asymmetry.json"))
    args = parser.parse_args(argv)

    transport = HttpTransport()
    gate = SpendGate(max_calls=args.max_calls)
    all_rows = []
    gaps = {}

    # 1. Does it replicate at another price level?
    for bid, ask in ((99, 101), (149, 151)):
        questions_action, meaning = VARIANTS["baseline"]
        cache = DecisionCache(pathlib.Path("data/cache_probe") / "baseline")
        rows = run_variant("baseline", questions_action, meaning, transport, gate, cache, bid, ask)
        all_rows += rows
        gaps[f"baseline @ {bid}/{ask}"] = summarise(rows, f"baseline, book {bid}/{ask}")

    # 2. Is it option order, or the word, or the semantics?
    for name in ("order_reversed", "neutral_labels", "label_swap"):
        questions_action, meaning = VARIANTS[name]
        cache = DecisionCache(pathlib.Path("data/cache_probe") / name)
        rows = run_variant(name, questions_action, meaning, transport, gate, cache, 99, 101)
        all_rows += rows
        gaps[name] = summarise(rows, f"{name}, book 99/101")

    print("\n=== asymmetry (acquire - dispose) across variants ===")
    for name, gap in gaps.items():
        print(f"  {name:<24} {gap:+.3f}")

    print(f"\nlive calls {gate.calls}, cache hits {gate.cache_hits}, "
          f"tokens {gate.input_tokens}/{gate.output_tokens}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"rows": all_rows, "gaps": gaps}, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
