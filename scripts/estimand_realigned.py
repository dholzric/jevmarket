"""Reanalyse F2 and G1 on claim-aligned outcomes. No new API calls.

Fifth-pass review found that both tests measured something adjacent to the
claim rather than the claim itself.

F2 measured the expected LARGEST ACTION SHARE among eight traders, and the
paper compared its 2.84pp bound against a 25.8pp liquidity effect. Those are
different quantities and the comparison does not hold. The mechanism is not
linear in majority share: it turns on whether ANY trader takes the opposite
side, which is `1 - sum_a p_a^N`. At p=0.986 the majority share is 1.4 points
from unanimity while P(all eight agree) is 0.893 -- a tenfold difference in
what matters.

G1 registered a shift in returned `P(buy)` but the implementation compared a
0/1 indicator of the MODAL choice. Given Experiment 1's central finding is that
wording moves probability mass while leaving the mode correct, testing the mode
is precisely the wrong test for contamination of a probability-based control.

Both are recomputed here from archived responses:
  data/raw_repeats.json   6,000 uncached repeats, with full answers
  data/cache_naming/      the label-swap responses, with full probabilities

    python scripts/estimand_realigned.py
"""

from __future__ import annotations

import collections
import json
import math
import pathlib
import statistics

import scipy.special as sp
import scipy.stats as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TRADERS = 8
MARGIN = 0.10

MEANING = {"option_a": "buy", "option_b": "sell", "option_c": "pass"}
MEANING_SWAPPED = {"option_a": "sell", "option_b": "buy", "option_c": "pass"}


def unanimity_probability(counts, repeats, n=TRADERS):
    """P(all n independent callers choose the same action), Bayesian in p.

    With only `repeats` observations per state, the empirical estimate p=1 for
    a state seen stable five times is biased: five repeats cannot rule out
    modest instability. Integrating a Jeffreys Beta posterior over p gives
    E[p^n] = B(a+n, b) / B(a, b), which is the honest version.
    """
    total = 0.0
    for action, k in counts.items():
        a, b = k + 0.5, repeats - k + 0.5
        total += math.exp(sp.betaln(a + n, b) - sp.betaln(a, b))
    return total


def main() -> int:
    # ---------- F2 realigned: counterparty availability -------------------
    raw = json.loads((DATA / "raw_repeats.json").read_text(encoding="utf-8"))
    by_state = collections.defaultdict(lambda: {"actions": [], "prov": None})
    for record in raw:
        key = json.dumps(record["state"], sort_keys=True)
        by_state[key]["actions"].append(record["answers"]["action"]["choice"])
        by_state[key]["prov"] = record["provenance"]

    rows = []
    for key, entry in by_state.items():
        counts = collections.Counter(entry["actions"])
        repeats = len(entry["actions"])
        p_unanimous = unanimity_probability(counts, repeats)
        rows.append({
            "direction": entry["prov"]["direction"],
            "repeats": repeats,
            "stable": len(counts) == 1,
            # Memoised: every trader reads one stored response, so the action
            # set is unanimous by construction.
            "p_unanimous_memoised": 1.0,
            "p_unanimous_independent": p_unanimous,
            "counterparty_gain": 1.0 - p_unanimous,
        })

    print("=== F2 realigned: probability the market has NO counterparty ===")
    print("    (all eight traders on the same side; this is the mechanism's")
    print("     actual outcome, not the expected majority share)\n")
    header = f"  {'states':>8} {'memoised':>10} {'independent':>13} {'counterparty gain':>19}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    summary = {}
    for label, subset in (("all", rows),
                          ("after up", [r for r in rows if r["direction"] == "up"]),
                          ("after down", [r for r in rows if r["direction"] == "down"])):
        if not subset:
            continue
        memo = statistics.fmean(r["p_unanimous_memoised"] for r in subset)
        indep = statistics.fmean(r["p_unanimous_independent"] for r in subset)
        gains = [r["counterparty_gain"] for r in subset]
        gain = statistics.fmean(gains)
        se = statistics.stdev(gains) / len(gains) ** 0.5 if len(gains) > 1 else float("nan")
        hi = gain + st.t.ppf(0.95, len(gains) - 1) * se if len(gains) > 1 else float("nan")
        summary[label] = {"n": len(subset), "memoised": memo, "independent": indep,
                          "gain": gain, "gain_se": se, "gain_upper95": hi}
        print(f"  {label:>8} n={len(subset):<3} {memo:>8.3f} {indep:>13.3f} "
              f"{gain * 100:>17.1f}pp")

    print(f"\n  Independent calling would supply a counterparty in "
          f"{summary['all']['gain'] * 100:.1f}% of post-shock states")
    print(f"  that memoisation renders unanimous (95% upper bound "
          f"{summary['all']['gain_upper95'] * 100:.1f}pp).")
    print("  This is a STATIC bound on counterparty availability. It does not")
    print("  identify the dynamic liquidity effect, which would require")
    print("  replaying the market with independent calls throughout.")

    # ---------- G1 realigned: probability mass, not modal choice -----------
    # Restrict to the corrected population. The first (crashed) run wrote
    # naming entries for the earlier empty-book states, and pooling the two
    # silently doubled the pair count.
    population = {json.dumps(r["state"], sort_keys=True) for r in raw}
    naming = []
    for f in (DATA / "cache_naming").rglob("*.json"):
        entry = json.loads(f.read_text(encoding="utf-8"))
        version = entry["request"].get("schema_version", "")
        if not version.startswith("naming2:"):
            continue
        state_key = json.dumps(entry["request"]["state"], sort_keys=True)
        if state_key not in population:
            continue
        naming.append((version.split(":")[1], state_key,
                       entry["response"]["answers"]["action"]))

    mass = collections.defaultdict(dict)
    for variant, state_key, answer in naming:
        mapping = MEANING if variant == "mirror" else MEANING_SWAPPED
        probs = answer.get("probabilities") or {}
        buy = sum(p for option, p in probs.items() if mapping.get(option) == "buy")
        mass[state_key][variant] = buy

    paired = [v["mirror_swapped"] - v["mirror"] for v in mass.values()
              if "mirror" in v and "mirror_swapped" in v]

    print("\n=== G1 realigned: shift in returned P(buy), not modal choice ===")
    if len(paired) < 2:
        print(f"  only {len(paired)} paired states recovered; cannot test")
        return 1
    mean = statistics.fmean(paired)
    se = statistics.stdev(paired) / len(paired) ** 0.5
    df = len(paired) - 1
    lo, hi = st.t.interval(0.90, df, loc=mean, scale=se) if se else (mean, mean)
    if se == 0:
        p_tost, g1 = 0.0, True
    else:
        p_tost = max(st.t.sf((mean + MARGIN) / se, df),
                     st.t.cdf((mean - MARGIN) / se, df))
        g1 = p_tost < 0.05
    print(f"  paired states                      {len(paired)}")
    print(f"  mean shift in P(buy) mass          {mean * 100:+.2f}pp")
    print(f"  90% CI                             [{lo * 100:+.2f}, {hi * 100:+.2f}]pp")
    print(f"  TOST p against +/-{MARGIN * 100:.0f}pp          {p_tost:.4f}")
    print(f"  G1 (probability mass): {'HOLDS' if g1 else 'NOT ESTABLISHED'}")
    print("  [secondary] modal agreement was 60/60, reported separately")
    print(f"  (restricted to the {len(population)} states of the corrected population)")

    payload = {"f2_realigned": summary,
               "f2_note": "static bound on counterparty availability, not the "
                          "dynamic liquidity effect",
               "g1_realigned": {"n": len(paired), "mean_shift": mean,
                                "ci90": [lo, hi], "tost_p": p_tost,
                                "holds": bool(g1)}}
    (DATA / "estimand_realigned.json").write_text(
        json.dumps(payload, indent=2, default=float), encoding="utf-8")
    print(f"\nwrote {DATA / 'estimand_realigned.json'}  (no API calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
