"""Repeated-response sensitivity. Registered as prereg 10d.

F1  the modal action is stable across repeated live calls to the same state
F2  independent agreement is within 10pp of memoised agreement at N=8

The cache returns one stored response per distinct state, so the experiments
measure "one archived response per distinct state" rather than N agents each
calling a non-deterministic service. Memoisation can only increase within-state
agreement, which is the proposed mechanism. This measures how much.

Deliberately bypasses the cache: every repeat is a live call.

    python scripts/repeated_response.py --states 50 --repeats 5
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
from jevmarket.jev.budget import (  # noqa: E402
    JEV_PRICING_ESTIMATE,
    BudgetExceeded,
    SpendGate,
)
from jevmarket.jev.cache import DecisionCache  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.jev.transport import JevRequest  # noqa: E402


def sampled_states(n, seed, cache_dir="data/cache"):
    """Real states the confirmatory runs actually visited, drawn at random."""
    files = list(pathlib.Path(cache_dir).rglob("*.json"))
    rng = random.Random(seed)
    rng.shuffle(files)
    out, seen = [], set()
    for f in files:
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        request = entry.get("request", {})
        if request.get("schema_version") != "v1:original":
            continue
        state = request.get("state")
        if not state or state.get("best_bid") is None:
            continue
        key = json.dumps(state, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(state)
        if len(out) >= n:
            break
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", type=int, default=50)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--traders", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260919)
    parser.add_argument("--max-usd", type=float, default=0.50)
    parser.add_argument("--out", type=pathlib.Path,
                        default=pathlib.Path("data/repeated_response.json"))
    args = parser.parse_args(argv)

    schema = load_schema("original")
    transport = HttpTransport()
    gate = SpendGate(max_usd=args.max_usd, pricing=JEV_PRICING_ESTIMATE)
    states = sampled_states(args.states, args.seed)
    print(f"{len(states)} distinct states, {args.repeats} live repeats each "
          f"(cache deliberately bypassed)\n")

    rows = []
    for index, state in enumerate(states):
        request = JevRequest(model=schema["model"], state=state,
                             questions=schema["questions"], schema_version="v1:original")
        actions, probabilities = [], []
        try:
            for _ in range(args.repeats):
                response = transport.send(request)
                gate.charge(response.input_tokens, response.output_tokens)
                decision = Decision.from_answers(response.answers, schema=schema)
                actions.append(decision.action.value)
                probabilities.append(dict(decision.action_probabilities))
        except BudgetExceeded as error:
            print(f"\nSTOPPED by the spend gate after {index} states: {error}")
            break

        counts = collections.Counter(actions)
        modal, modal_n = counts.most_common(1)[0]
        rows.append({
            "state": state,
            "actions": actions,
            "mode_stability": modal_n / len(actions),
            "modal_action": modal,
            "mean_probs": {
                a: statistics.fmean(p[a] for p in probabilities)
                for a in ("buy", "sell", "pass")
            },
        })
        if (index + 1) % 10 == 0:
            print(f"  {index + 1}/{len(states)} states, {gate.calls} calls, "
                  f"${gate.spent_usd:.3f}")

    # --- F1: is the modal action stable? ------------------------------------
    stability = [r["mode_stability"] for r in rows]
    fully_stable = sum(1 for s in stability if s == 1.0)
    mean_stability = statistics.fmean(stability)
    print(f"\n=== F1: mode stability across {args.repeats} live repeats ===")
    print(f"  states                      {len(rows)}")
    print(f"  mean mode stability         {mean_stability:.3f}")
    print(f"  states with identical mode  {fully_stable}/{len(rows)} "
          f"({fully_stable / len(rows):.1%})")
    lo = st.beta.ppf(0.025, fully_stable + 0.5, len(rows) - fully_stable + 0.5)
    print(f"  95% lower bound on that     {lo:.3f}")
    f1 = mean_stability >= 0.95
    print(f"  F1 (>= 0.95): {'HOLDS' if f1 else 'FAILS'}")

    # --- F2: memoised vs independent agreement at N traders -----------------
    rng = random.Random(args.seed)
    memoised, independent = [], []
    for r in rows:
        # Memoised: all N traders read one stored response, so they agree by
        # construction whenever the state is identical.
        memoised.append(1.0)
        # Independent: each trader draws its own live response. Resample the
        # observed repeats with replacement to estimate agreement among N.
        trials = []
        for _ in range(400):
            draw = [rng.choice(r["actions"]) for _ in range(args.traders)]
            trials.append(collections.Counter(draw).most_common(1)[0][1] / args.traders)
        independent.append(statistics.fmean(trials))

    gap = [m - i for m, i in zip(memoised, independent)]
    mean_gap = statistics.fmean(gap)
    se_gap = statistics.stdev(gap) / len(gap) ** 0.5 if len(gap) > 1 else float("nan")
    print(f"\n=== F2: agreement among {args.traders} traders ===")
    print(f"  memoised (one stored response)   {statistics.fmean(memoised):.3f}")
    print(f"  independent (own live response)  {statistics.fmean(independent):.3f}")
    print(f"  inflation from memoisation       {mean_gap:+.3f} "
          f"({mean_gap * 100:+.1f}pp), SE {se_gap:.3f}")
    f2 = mean_gap < 0.10
    print(f"  F2 (< 10pp): {'HOLDS' if f2 else 'FAILS'}")

    print("\n=== interpretation, fixed in advance ===")
    if f1 and f2:
        print("  Both hold: memoisation is immaterial at the mode, and the argmax")
        print("  result generalises to independent callers. The limitation becomes")
        print("  a measured bound rather than an open caveat.")
    elif not f1:
        print("  F1 FAILS: the argmax arm is not the deterministic policy the")
        print("  mechanism assumes. The mechanism section must be rewritten.")
    else:
        print("  F2 FAILS: the effect size is inflated by memoisation and the")
        print("  headline number must be reported as an upper bound.")

    payload = {"states": len(rows), "repeats": args.repeats, "traders": args.traders,
               "mean_mode_stability": mean_stability,
               "fully_stable_states": fully_stable,
               "memoised_agreement": statistics.fmean(memoised),
               "independent_agreement": statistics.fmean(independent),
               "inflation": mean_gap, "inflation_se": se_gap,
               "F1_holds": f1, "F2_holds": f2,
               "cost": gate.summary(), "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\ncost: {gate.calls} live calls, ${gate.spent_usd:.4f}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
