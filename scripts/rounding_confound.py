"""Did our tick-rounding manufacture the herding, or is it intrinsic to argmax?

We round the state shown to Jev to whole ticks, for cache efficiency. That
means traders with nearby private values send identical requests and therefore
get identical answers. The trade-cessation finding could be an artefact of that
choice rather than a fact about the model.

The sharp test does not need a market. After an up jump the fundamental is 110
while the book still sits near 100, and traders hold private values spread
around 110. If Jev returns "buy" as its top answer across that WHOLE spread --
rounded or not -- then rounding changes nothing: every trader herds anyway,
because the model is simply decisive over the entire relevant range.

Rounding is the culprit only if un-rounded values produce a meaningfully more
varied set of top answers than rounded ones do.

    python scripts/rounding_confound.py
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.decision import load_schema  # noqa: E402
from jevmarket.jev.budget import JEV_PRICING_ESTIMATE, SpendGate  # noqa: E402
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.jev.transport import JevRequest  # noqa: E402

SCHEMA = load_schema("original")


def request_for(value, bid, ask, last, wording="original"):
    schema = load_schema(wording)
    return JevRequest(
        model=schema["model"],
        state={
            "best_bid": bid, "best_ask": ask, "spread": ask - bid,
            "last_trade_price": last,
            "your_private_value": value, "your_signal": value,
        },
        questions=schema["questions"],
        schema_version=f"roundprobe:{wording}",
    )


def top_answer(response, wording):
    option_map = load_schema(wording).get("option_map") or {}
    choice = response.answers["action"]["choice"]
    return option_map.get(choice, choice)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traders", type=int, default=24)
    parser.add_argument("--value-sd", type=float, default=5.0)
    parser.add_argument("--max-usd", type=float, default=0.5)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/rounding.json"))
    args = parser.parse_args(argv)

    transport = HttpTransport()
    gate = SpendGate(max_usd=args.max_usd, pricing=JEV_PRICING_ESTIMATE)
    cache = DecisionCache("data/cache_rounding")

    # Two moments that matter: just after an up jump and just after a down jump,
    # with the book still at its pre-jump level.
    scenarios = [
        ("after UP jump   (F=110, book 99/101)", 110.0, 99, 101, 100),
        ("after DOWN jump (F=100, book 109/111)", 100.0, 109, 111, 110),
    ]

    rng = np.random.default_rng(20260919)
    results = {}

    for label, fundamental, bid, ask, last in scenarios:
        values = fundamental + rng.normal(0.0, args.value_sd, args.traders)
        print(f"\n=== {label} ===")
        print(f"{args.traders} traders, private values {values.min():.2f}..{values.max():.2f}")

        for mode in ("rounded", "unrounded"):
            shown = [round(v) for v in values] if mode == "rounded" else [round(float(v), 4) for v in values]
            answers = []
            for v in shown:
                request = request_for(v, bid, ask, last)
                hit = cache.get(request)
                if hit is not None:
                    response = hit
                    gate.note_cache_hit()
                else:
                    response = transport.send(request)
                    gate.charge(response.input_tokens, response.output_tokens)
                    cache.put(request, response)
                answers.append(top_answer(response, "original"))

            counts = collections.Counter(answers)
            distinct_states = len(set(shown))
            majority = counts.most_common(1)[0]
            print(f"  {mode:>10}: {distinct_states:>2} distinct states shown -> "
                  f"top answers {dict(counts)}  "
                  f"({majority[1]}/{len(answers)} = {majority[1]/len(answers):.0%} agree)")
            results[f"{label}|{mode}"] = {
                "distinct_states": distinct_states,
                "counts": dict(counts),
                "agreement": majority[1] / len(answers),
            }

    print("\n=== verdict ===")
    for label, *_ in scenarios:
        r = results[f"{label}|rounded"]["agreement"]
        u = results[f"{label}|unrounded"]["agreement"]
        ds_r = results[f"{label}|rounded"]["distinct_states"]
        ds_u = results[f"{label}|unrounded"]["distinct_states"]
        print(f"  {label}")
        print(f"    rounded  : {ds_r:>2} distinct states, {r:.0%} of traders pick the same side")
        print(f"    unrounded: {ds_u:>2} distinct states, {u:.0%} of traders pick the same side")
        # The question is whether un-rounding DISPERSES the herd, so compare the
        # two modes against each other. An absolute threshold would call 92% vs
        # 92% "partial", which is exactly backwards: identical agreement across
        # 11 vs 24 distinct states is the cleanest possible exoneration.
        if u < r - 0.10:
            print("    -> un-rounding breaks up the herd. Rounding IS doing the work.")
        elif abs(u - r) <= 0.05:
            print(f"    -> herding identical at {ds_u} distinct states as at {ds_r}. "
                  f"Rounding is NOT the cause.")
        else:
            print("    -> partial: rounding contributes but does not explain it.")

    print(f"\ncost: {gate.calls} live calls, ${gate.spent_usd:.4f} "
          f"(cache hits {gate.cache_hits})")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
