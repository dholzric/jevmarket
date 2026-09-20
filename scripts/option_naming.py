"""Option-naming control. Registered as prereg 10e.

G1  the choice follows the description, not the label
G2  any label effect is small relative to the ~25pp residual asymmetry

Our "neutral" mirror wording always puts the above-price description on
`option_a`, which maps to buy. If the model prefers the first option at all,
that appears as a buy bias -- exactly the residual the paper cannot explain --
and it would also contaminate the mirror control.

This asks the same states under two question sets differing ONLY in which label
carries which description, and compares in economic meaning space. Diagnostic
question sets are built inline; the frozen schemas are untouched.

    python scripts/option_naming.py
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

import scipy.stats as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.decision import load_schema  # noqa: E402
from jevmarket.jev.budget import (  # noqa: E402
    JEV_PRICING_ESTIMATE,
    BudgetExceeded,
    SpendGate,
)
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.jev.transport import JevRequest  # noqa: E402

MIRROR = load_schema("mirror")
ACTION = MIRROR["questions"]["action"]
ABOVE = ACTION["criteria"]["option_a"]
BELOW = ACTION["criteria"]["option_b"]
EQUAL = ACTION["criteria"]["option_c"]

# The two arrangements differ only in which label carries which description.
VARIANTS = {
    "mirror": (
        {"option_a": ABOVE, "option_b": BELOW, "option_c": EQUAL},
        {"option_a": "buy", "option_b": "sell", "option_c": "pass"},
    ),
    "mirror_swapped": (
        {"option_a": BELOW, "option_b": ABOVE, "option_c": EQUAL},
        {"option_a": "sell", "option_b": "buy", "option_c": "pass"},
    ),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-usd", type=float, default=0.25)
    parser.add_argument("--states", type=pathlib.Path,
                        default=pathlib.Path("data/repeated_response.json"))
    parser.add_argument("--out", type=pathlib.Path,
                        default=pathlib.Path("data/option_naming.json"))
    args = parser.parse_args(argv)

    states = [r["state"] for r in json.loads(args.states.read_text())["rows"]]
    transport = HttpTransport()
    gate = SpendGate(max_usd=args.max_usd, pricing=JEV_PRICING_ESTIMATE)
    cache = DecisionCache("data/cache_naming")

    print(f"{len(states)} states, two label arrangements of identical descriptions\n")
    by_variant = {}
    per_state = collections.defaultdict(dict)

    for name, (criteria, mapping) in VARIANTS.items():
        counts = collections.Counter()
        for i, state in enumerate(states):
            request = JevRequest(
                model=MIRROR["model"],
                state=state,
                questions={"action": {"type": "choice",
                                      "instructions": ACTION["instructions"],
                                      "criteria": criteria}},
                schema_version=f"naming:{name}",
            )
            hit = cache.get(request)
            if hit is not None:
                response = hit
                gate.note_cache_hit()
            else:
                try:
                    response = transport.send(request)
                except BudgetExceeded as error:
                    print(f"STOPPED by the spend gate: {error}")
                    return 1
                gate.charge(response.input_tokens, response.output_tokens)
                cache.put(request, response)
            meaning = mapping[response.answers["action"]["choice"]]
            counts[meaning] += 1
            per_state[i][name] = meaning

        total = sum(counts.values())
        by_variant[name] = {a: counts[a] / total for a in ("buy", "sell", "pass")}
        print(f"  {name:>15}: " + "  ".join(
            f"{a} {by_variant[name][a]:5.1%}" for a in ("buy", "sell", "pass")))

    # --- G1: does the choice follow the description or the label? -----------
    shift = {a: by_variant["mirror_swapped"][a] - by_variant["mirror"][a]
             for a in ("buy", "sell", "pass")}
    agree = sum(1 for v in per_state.values()
                if v.get("mirror") == v.get("mirror_swapped"))
    n = len(per_state)

    print("\n=== G1: choice follows the description, not the label ===")
    print("  shift in meaning space when labels swap:")
    for a in ("buy", "sell", "pass"):
        print(f"      {a:>5} {shift[a]:+6.1%}")
    print(f"  states choosing the same MEANING under both  {agree}/{n} "
          f"({agree / n:.1%})")
    lo = st.beta.ppf(0.025, agree + 0.5, n - agree + 0.5)
    print(f"  95% lower bound on that                      {lo:.3f}")
    g1 = abs(shift["buy"]) < 0.10
    print(f"  G1 (|shift in P(buy)| < 10pp): {'HOLDS' if g1 else 'FAILS'}")

    # --- G2: is any label effect small next to the residual? ----------------
    residual = 0.25  # ~90.0% up-side vs ~64.8% down-side agreement
    ratio = abs(shift["buy"]) / residual
    print("\n=== G2: size against the residual asymmetry ===")
    print(f"  residual to be explained                     {residual:.0%}")
    print(f"  label effect on P(buy)                       {abs(shift['buy']):.1%}")
    print(f"  fraction of the residual it could explain    {ratio:.1%}")
    g2 = ratio < 0.40
    print(f"  G2 (< 40% of the residual): {'HOLDS' if g2 else 'FAILS'}")

    print("\n=== interpretation, fixed in advance ===")
    if g1 and g2:
        print("  The choice follows the description. Option naming is not the")
        print("  residual asymmetry, and the mirror control is not contaminated.")
    else:
        print("  The choice follows the LABEL. The residual asymmetry is")
        print("  substantially an option-naming artefact, and the mirror wording")
        print("  is a contaminated control for Experiment 1. Both must be reported.")

    payload = {"n_states": n, "by_variant": by_variant, "shift": shift,
               "same_meaning": agree, "same_meaning_rate": agree / n,
               "G1_holds": g1, "G2_holds": g2, "cost": gate.summary()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\ncost: {gate.calls} live calls, ${gate.spent_usd:.4f}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
