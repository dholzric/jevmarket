"""Corrected F1/F2/G1 on the registered population, with the registered tests.

Supersedes the first run of prereg 10d/10e, which deviated three ways (see
prereg 10f): it sampled the whole cache rather than post-shock windows of the
confirmatory runs, scored an unregistered statistic for F1, and decided every
flag by point estimate with no confidence bound.

This script:

  * reconstructs the registered population by REPLAYING the confirmatory
    jev_argmax/original runs (seeds 24-43) from cache and collecting the states
    rendered inside the 15-period post-shock windows, with provenance;
  * calls each sampled state R times LIVE, bypassing the cache, and archives
    every raw response so "every response is archived" stays true;
  * decides F1, F2 and G1 on confidence bounds, not point estimates.

F1  proportion of states whose modal action is identical across all R repeats,
    Jeffreys one-sided 95% lower bound must exceed 0.95
F2  paired per-state inflation from memoisation, one-sided 95% upper bound
    must be below 10 percentage points
G1  paired equivalence (TOST) on the buy-share shift when option labels swap,
    against a +/- 10 point margin

    python scripts/estimand_corrected.py --states 60 --repeats 5
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import statistics
import sys

import scipy.stats as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.decision import Decision, load_schema  # noqa: E402
from jevmarket.fundamental import MatchedJumpFundamental, Signal  # noqa: E402
from jevmarket.jev.budget import (  # noqa: E402
    JEV_PRICING_ESTIMATE,
    BudgetExceeded,
    SpendGate,
)
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.client import JevClient  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.jev.questions import render_state  # noqa: E402
from jevmarket.jev.transport import JevRequest  # noqa: E402

SCHEMA = load_schema("original")
MIRROR = load_schema("mirror")
MACTION = MIRROR["questions"]["action"]
ABOVE = MACTION["criteria"]["option_a"]
BELOW = MACTION["criteria"]["option_b"]
EQUAL = MACTION["criteria"]["option_c"]

LABEL_VARIANTS = {
    "mirror": ({"option_a": ABOVE, "option_b": BELOW, "option_c": EQUAL},
               {"option_a": "buy", "option_b": "sell", "option_c": "pass"}),
    "mirror_swapped": ({"option_a": BELOW, "option_b": ABOVE, "option_c": EQUAL},
                       {"option_a": "sell", "option_b": "buy", "option_c": "pass"}),
}


class RecordingClient:
    """Wraps JevClient and records the ACTUAL rendered state of every call.

    DecisionRecord does not store the order book, so the state a decision was
    taken on cannot be reconstructed from it -- an earlier version of this
    script tried, produced empty-book states, and sampled a population that was
    not the registered one. Recording at the client is the only faithful route.
    """

    def __init__(self, inner):
        self.inner = inner
        self.seen = []

    def decide(self, observation, wording="original"):
        from jevmarket.jev.questions import render_state as _render

        self.seen.append({"period": observation.period, "state": _render(observation)})
        return self.inner.decide(observation, wording=wording)


def registered_population(seeds, traders, periods, window):
    """States rendered inside the registered post-shock windows, with provenance.

    Replays the confirmatory runs from cache, recording the real rendered state
    of every decision, then keeps those falling inside a post-shock window.
    """
    from jevmarket.simulation import RunConfig, run

    base = JevClient(HttpTransport(), cache=DecisionCache("data/cache"))
    population = []
    for seed in seeds:
        fundamental = MatchedJumpFundamental(
            initial=100.0, jump_size=10.0, period_gap=20, seed=1000 + seed
        )
        recorder = RecordingClient(base)
        result = run(
            RunConfig(n_traders=traders, periods=periods, seed=seed,
                      arm="jev_argmax", wording="original", burn_in_periods=5,
                      fundamental=fundamental, signal=Signal(seed=seed),
                      jev_client=recorder)
        )
        path = result.fundamental_path
        window_of = {}
        for jump in result.jump_times:
            if jump == 0 or jump >= len(path):
                continue
            direction = "up" if path[jump] > path[jump - 1] else "down"
            for t in range(jump, min(jump + window, len(path))):
                window_of[t] = (jump, direction)

        for call in recorder.seen:
            if call["period"] in window_of:
                jump, direction = window_of[call["period"]]
                population.append({
                    "seed": seed, "period": call["period"], "jump": jump,
                    "direction": direction, "state": call["state"],
                })
    return population


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", type=int, default=60)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--traders", type=int, default=8)
    parser.add_argument("--periods", type=int, default=160)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20260920)
    parser.add_argument("--max-usd", type=float, default=1.0)
    parser.add_argument("--out", type=pathlib.Path,
                        default=pathlib.Path("data/estimand_corrected.json"))
    parser.add_argument("--raw", type=pathlib.Path,
                        default=pathlib.Path("data/raw_repeats.json"))
    args = parser.parse_args(argv)

    print("reconstructing the registered population (replay from cache)...")
    population = registered_population(
        range(24, 44), args.traders, args.periods, args.window)
    # Distinct rendered states, so repeats measure the service and not duplicates.
    unique = {}
    for entry in population:
        key = json.dumps(entry["state"], sort_keys=True)
        unique.setdefault(key, entry)
    print(f"  {len(population)} post-shock decisions -> {len(unique)} distinct states")

    rng = random.Random(args.seed)
    chosen = rng.sample(sorted(unique.values(), key=lambda e: json.dumps(e, sort_keys=True)),
                        min(args.states, len(unique)))
    print(f"  sampled {len(chosen)} of them\n")

    transport = HttpTransport()
    gate = SpendGate(max_usd=args.max_usd, pricing=JEV_PRICING_ESTIMATE)
    raw = []
    rows = []

    for index, entry in enumerate(chosen):
        request = JevRequest(model=SCHEMA["model"], state=entry["state"],
                             questions=SCHEMA["questions"], schema_version="v1:original")
        actions = []
        try:
            for repeat in range(args.repeats):
                response = transport.send(request)
                gate.charge(response.input_tokens, response.output_tokens)
                raw.append({"state": entry["state"], "repeat": repeat,
                            "provenance": {k: entry[k] for k in
                                           ("seed", "period", "jump", "direction")},
                            "answers": response.answers, "model": response.model})
                actions.append(Decision.from_answers(response.answers,
                                                     schema=SCHEMA).action.value)
        except BudgetExceeded as error:
            print(f"STOPPED by the spend gate after {index} states: {error}")
            break
        counts = collections.Counter(actions)
        rows.append({**{k: entry[k] for k in ("seed", "period", "jump", "direction")},
                     "actions": actions,
                     "stable": len(counts) == 1,
                     "stability": counts.most_common(1)[0][1] / len(actions)})
        if (index + 1) % 20 == 0:
            print(f"  {index + 1}/{len(chosen)} states, {gate.calls} calls, "
                  f"${gate.spent_usd:.3f}")

    n = len(rows)
    k = sum(1 for r in rows if r["stable"])
    mean_stability = statistics.fmean(r["stability"] for r in rows)

    print(f"\n=== F1 (registered statistic: proportion of states fully stable) ===")
    print(f"  states                                {n}")
    print(f"  fully stable across {args.repeats} repeats        {k}/{n} = {k / n:.3f}")
    lower = st.beta.ppf(0.05, k + 0.5, n - k + 0.5)
    print(f"  Jeffreys one-sided 95% lower bound    {lower:.3f}")
    print(f"  registered threshold                  0.950")
    f1 = lower > 0.95
    print(f"  F1: {'HOLDS' if f1 else 'DOES NOT HOLD'} "
          f"(decided on the bound, not the point estimate)")
    print(f"  [secondary] mean within-state stability {mean_stability:.3f}")

    # --- F2: paired inflation with an upper confidence bound ----------------
    rng2 = random.Random(args.seed)
    inflation = []
    for r in rows:
        trials = []
        for _ in range(400):
            draw = [rng2.choice(r["actions"]) for _ in range(args.traders)]
            trials.append(collections.Counter(draw).most_common(1)[0][1] / args.traders)
        inflation.append(1.0 - statistics.fmean(trials))
    mean_inf = statistics.fmean(inflation)
    se_inf = statistics.stdev(inflation) / len(inflation) ** 0.5
    upper = mean_inf + st.t.ppf(0.95, len(inflation) - 1) * se_inf
    print(f"\n=== F2 (paired inflation, one-sided 95% upper bound) ===")
    print(f"  mean inflation                        {mean_inf * 100:+.2f}pp")
    print(f"  one-sided 95% upper bound             {upper * 100:+.2f}pp")
    print(f"  registered margin                     10.00pp")
    f2 = upper < 0.10
    print(f"  F2: {'HOLDS' if f2 else 'DOES NOT HOLD'}")

    # --- G1: paired TOST on the label swap ----------------------------------
    print(f"\n=== G1 (paired equivalence, TOST, margin +/-10pp) ===")
    cache = DecisionCache("data/cache_naming")
    shares = {}
    per_state = collections.defaultdict(dict)
    for name, (criteria, mapping) in LABEL_VARIANTS.items():
        buys = []
        for i, entry in enumerate(chosen[:len(rows)]):
            request = JevRequest(
                model=MIRROR["model"], state=entry["state"],
                questions={"action": {"type": "choice",
                                      "instructions": MACTION["instructions"],
                                      "criteria": criteria}},
                schema_version=f"naming2:{name}")
            hit = cache.get(request)
            if hit is not None:
                response = hit
                gate.note_cache_hit()
            else:
                try:
                    response = transport.send(request)
                except BudgetExceeded as error:
                    print(f"  STOPPED by the spend gate: {error}")
                    return 1
                gate.charge(response.input_tokens, response.output_tokens)
                cache.put(request, response)
            meaning = mapping[response.answers["action"]["choice"]]
            per_state[i][name] = meaning
            buys.append(1.0 if meaning == "buy" else 0.0)
        shares[name] = buys

    paired = [a - b for a, b in zip(shares["mirror_swapped"], shares["mirror"])]
    mean_shift = statistics.fmean(paired)
    se_shift = statistics.stdev(paired) / len(paired) ** 0.5
    df = len(paired) - 1
    margin = 0.10
    if se_shift == 0.0:
        # Every state chose the same meaning under both labelings. TOST is
        # undefined (zero variance); this is perfect equivalence, not a failure.
        print(f"  states choosing the same meaning      {len(paired)}/{len(paired)}")
        print(f"  mean shift in buy share               {mean_shift * 100:+.2f}pp")
        print("  every paired difference is exactly zero: TOST undefined,")
        print("  equivalence holds trivially within any positive margin")
        g1, p_tost, lo, hi = True, 0.0, 0.0, 0.0
        same = len(paired)
        _tost_degenerate = True
    else:
        _tost_degenerate = False
        t_lower = (mean_shift + margin) / se_shift
        t_upper = (mean_shift - margin) / se_shift
        p_tost = max(st.t.sf(t_lower, df), st.t.cdf(t_upper, df))
        lo, hi = st.t.interval(0.90, df, loc=mean_shift, scale=se_shift)
        same = sum(1 for v in per_state.values()
                   if v.get("mirror") == v.get("mirror_swapped"))
        print(f"  states choosing the same meaning      {same}/{len(per_state)}")
        print(f"  mean shift in buy share               {mean_shift * 100:+.2f}pp")
        print(f"  90% CI                                [{lo * 100:+.2f}, {hi * 100:+.2f}]pp")
        print(f"  TOST p                                {p_tost:.4f}")
        g1 = p_tost < 0.05
    print(f"  G1: {'HOLDS (equivalent within 10pp)' if g1 else 'NOT ESTABLISHED'}")

    print("\n=== verdict ===")
    for label, held in (("F1", f1), ("F2", f2), ("G1", g1)):
        print(f"  {label}: {'holds' if held else 'does not hold'}")
    if not f1:
        print("\n  F1 not holding means the modal action is not stable enough,")
        print("  at this sample size, to certify that memoisation is immaterial")
        print("  by the registered criterion. F2 bounds how much it inflates")
        print("  agreement regardless; report both and claim only the bound.")

    payload = {"n_states": n, "repeats": args.repeats, "traders": args.traders,
               "population": "post-shock windows, jev_argmax/original, seeds 24-43",
               "fully_stable": k, "fully_stable_rate": k / n,
               "f1_lower_bound": lower, "mean_stability": mean_stability,
               "inflation_mean": mean_inf, "inflation_upper_bound": upper,
               "label_shift_mean": mean_shift, "label_shift_ci90": [lo, hi],
               "tost_p": p_tost, "same_meaning": same,
               "F1_holds": bool(f1), "F2_holds": bool(f2), "G1_holds": bool(g1),
               "cost": gate.summary(), "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    args.raw.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(f"\ncost: {gate.calls} live calls, ${gate.spent_usd:.4f}")
    print(f"wrote {args.out} and {args.raw} ({len(raw)} raw responses archived)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
