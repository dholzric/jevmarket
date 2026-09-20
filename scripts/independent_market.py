"""Dynamic replication under independent calling. Registered as prereg 10h.

The confirmatory design of 10b (seeds 24-43, N=8, 160 periods, 15-period
post-shock windows) rerun with ONE CHANGE: every trader decision is a fresh
live call. The content-addressed cache is neither read nor written.

H1  jev_argmax: traded_share(down) - traded_share(up) > 0      (one-sided paired t)
H2  that gap exceeds jev_sample's, both independent             (one-sided paired t)
H3  gap_memoised - gap_independent for jev_argmax, paired by seed
    against data/cessation_confirm.json                         (two-sided 95% CI)

Every response is archived in call order to data/independent/<arm>_seed<k>.json.gz.
A run whose archive already exists is replayed from it rather than re-bought,
so a crashed sweep resumes where it stopped and a reader with the archive can
reproduce every number here without a key.

    python scripts/independent_market.py                # live, resumes from archives
    python scripts/independent_market.py --replay       # archives only, no key needed
    python scripts/independent_market.py --mock --seeds 2 --periods 40   # free dry run
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import scipy.stats as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from cessation_confirm import measure  # noqa: E402  the registered statistic, unchanged
from jevmarket.fundamental import MatchedJumpFundamental, Signal  # noqa: E402
from jevmarket.jev.archive import CallLog, ReplayTransport  # noqa: E402
from jevmarket.jev.budget import (  # noqa: E402
    JEV_PRICING_ESTIMATE,
    BudgetExceeded,
    SpendGate,
)
from jevmarket.jev.client import JevClient  # noqa: E402
from jevmarket.jev.mock import MockTransport  # noqa: E402
from jevmarket.simulation import RunConfig, run  # noqa: E402

ARMS = ("jev_argmax", "jev_sample")


def archive_path(directory: pathlib.Path, arm: str, seed: int) -> pathlib.Path:
    return directory / f"{arm}_seed{seed}.json.gz"


def one_run(arm, seed, args, transport, gate):
    """Run one (arm, seed) cell. Returns (result, calls, source)."""
    path = archive_path(args.archive_dir, arm, seed)
    if path.is_file():
        client = JevClient(ReplayTransport(CallLog.load(path)))
        source = "archive"
    elif args.replay:
        raise FileNotFoundError(f"--replay but no archive at {path}")
    else:
        client = JevClient(transport, cache=None, budget=gate, archive=CallLog())
        source = "live"

    result = run(
        RunConfig(
            n_traders=args.traders, periods=args.periods, seed=seed, arm=arm,
            wording="original", burn_in_periods=5,
            fundamental=MatchedJumpFundamental(
                initial=100.0, jump_size=10.0, period_gap=20, seed=1000 + seed
            ),
            signal=Signal(seed=seed), jev_client=client,
        )
    )
    result.exchange.check_invariants()
    if source == "live":
        client.archive.save(path)
    calls = len(client.archive) if source == "live" else client.transport.position
    return result, calls, source


def one_sided_t(values):
    mean, sd = statistics.fmean(values), statistics.stdev(values)
    se = sd / len(values) ** 0.5
    t = mean / se
    p = st.t.sf(t, len(values) - 1)
    lo, hi = st.t.interval(0.95, len(values) - 1, loc=mean, scale=se)
    return mean, se, t, p, lo, hi


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--seed-offset", type=int, default=24)
    parser.add_argument("--periods", type=int, default=160)
    parser.add_argument("--traders", type=int, default=8)
    parser.add_argument("--window", type=int, default=15)
    parser.add_argument("--max-usd", type=float, default=2.5)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--replay", action="store_true", help="archives only; never call live")
    parser.add_argument("--mock", action="store_true", help="free dry run on the mock transport")
    parser.add_argument("--archive-dir", type=pathlib.Path, default=ROOT / "data" / "independent")
    parser.add_argument("--memoised", type=pathlib.Path, default=ROOT / "data" / "cessation_confirm.json")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "data" / "independent_market.json")
    args = parser.parse_args(argv)

    if args.mock:
        args.archive_dir = pathlib.Path(args.archive_dir).with_name("independent_mock")
        args.out = pathlib.Path(args.out).with_name("independent_market_mock.json")
        transport = MockTransport(seed=7)
    elif args.replay:
        transport = None
    else:
        from jevmarket.jev.http import HttpTransport
        transport = HttpTransport()
    gate = SpendGate(max_usd=args.max_usd, pricing=JEV_PRICING_ESTIMATE)
    seeds = list(range(args.seed_offset, args.seed_offset + args.seeds))
    jobs = [(arm, seed) for arm in ARMS for seed in seeds]

    started = time.monotonic()
    outcomes = {}
    failures = {}

    def work(job):
        arm, seed = job
        try:
            result, calls, source = one_run(arm, seed, args, transport, gate)
        except BudgetExceeded as error:
            failures[job] = f"spend gate: {error}"
            print(f"  STOPPED {arm} seed {seed}: {error}", flush=True)
            return
        except Exception as error:  # noqa: BLE001  one dead run must not kill the sweep
            failures[job] = f"{type(error).__name__}: {error}"
            print(f"  FAILED {arm} seed {seed}: {type(error).__name__}: {error}", flush=True)
            return
        outcomes[job] = (result, calls, source)
        spent = gate.spent_usd or 0.0
        print(f"  {arm:>10} seed {seed:>2}  {source:>7}  {calls:>5} calls  "
              f"cumulative live {gate.calls:>6} calls ${spent:.3f}  "
              f"{time.monotonic() - started:6.0f}s", flush=True)

    print(f"{len(jobs)} runs, {args.workers} workers, cache bypassed, "
          f"archives in {args.archive_dir}\n", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, jobs))

    if failures:
        print(f"\n{len(failures)} run(s) did not complete; rerun to resume:")
        for (arm, seed), why in sorted(failures.items()):
            print(f"  {arm} seed {seed}: {why}")
        print(json.dumps(gate.summary(), indent=2))
        return 1

    # --- the registered statistics -----------------------------------------
    gaps = {arm: {} for arm in ARMS}
    per_seed_levels = {arm: {"up": [], "down": []} for arm in ARMS}
    diagnostics = {arm: {"up": [], "down": []} for arm in ARMS}
    # Seed order, not thread-completion order, so the output file is identical
    # whether the runs were bought live or replayed from the archives.
    for (arm, seed) in sorted(outcomes):
        result = outcomes[(arm, seed)][0]
        traded, one_sided = measure(result, args.window)
        if traded["up"] and traded["down"]:
            gaps[arm][seed] = statistics.fmean(traded["down"]) - statistics.fmean(traded["up"])
            per_seed_levels[arm]["up"].append(statistics.fmean(traded["up"]))
            per_seed_levels[arm]["down"].append(statistics.fmean(traded["down"]))
        for key in ("up", "down"):
            if one_sided[key]:
                diagnostics[arm][key].append(statistics.fmean(one_sided[key]))

    common = sorted(set(gaps["jev_argmax"]) & set(gaps["jev_sample"]))
    assert set(gaps["jev_argmax"]) == set(gaps["jev_sample"]), "cells cover different seeds"
    argmax = [gaps["jev_argmax"][s] for s in common]
    sample = [gaps["jev_sample"][s] for s in common]

    # Levels as in market_size.json: mean over seeds of the per-seed mean share.
    levels = {arm: {k: statistics.fmean(v) for k, v in per_seed_levels[arm].items()}
              for arm in ARMS}
    print("\n=== traded share (mean over seeds) ===")
    for arm in ARMS:
        print(f"  {arm:>10}  after UP {levels[arm]['up']:.1%}  after DOWN {levels[arm]['down']:.1%}")

    print(f"\n=== H1 (primary): independent jev_argmax gap > 0, n={len(argmax)} ===")
    m1, se1, t1, p1, lo1, hi1 = one_sided_t(argmax)
    print(f"  mean {m1:+.1%}  SE {se1:.1%}  t={t1:+.2f}  p={p1:.5f}  95% CI [{lo1:+.1%}, {hi1:+.1%}]")
    print(f"  {sum(1 for v in argmax if v > 0)}/{len(argmax)} seeds positive")

    print(f"\n=== H2 (primary): independent argmax gap > independent sample gap, n={len(common)} ===")
    m2, se2, t2, p2, lo2, hi2 = one_sided_t([a - b for a, b in zip(argmax, sample)])
    print(f"  jev_sample gap mean {statistics.fmean(sample):+.1%}")
    print(f"  difference mean {m2:+.1%}  SE {se2:.1%}  t={t2:+.2f}  p={p2:.5f}  "
          f"95% CI [{lo2:+.1%}, {hi2:+.1%}]")

    print("\n=== Holm across H1/H2 ===")
    holm = {}
    ps = {"H1": p1, "H2": p2}
    for rank, (name, p) in enumerate(sorted(ps.items(), key=lambda kv: kv[1])):
        holm[name] = min(1.0, p * (len(ps) - rank))
        print(f"  {name}  raw p={p:.5f}  ->  Holm p={holm[name]:.5f}   "
              f"{'SIGNIFICANT' if holm[name] < 0.05 else 'NOT significant'}")

    h3 = None
    if args.memoised.is_file() and not args.mock:
        memo = json.loads(args.memoised.read_text(encoding="utf-8"))["gaps"]["jev_argmax/original"]
        paired = [(s, memo[str(s)] - gaps["jev_argmax"][s]) for s in common if str(s) in memo]
        diffs = [d for _, d in paired]
        mean, sd = statistics.fmean(diffs), statistics.stdev(diffs)
        se = sd / len(diffs) ** 0.5
        lo, hi = st.t.interval(0.95, len(diffs) - 1, loc=mean, scale=se)
        h3 = {"n": len(diffs), "memoised_mean": statistics.fmean(memo[str(s)] for s, _ in paired),
              "independent_mean": statistics.fmean(gaps["jev_argmax"][s] for s, _ in paired),
              "difference_mean": mean, "se": se, "ci95": [lo, hi],
              "seeds_positive": sum(1 for d in diffs if d > 0)}
        print(f"\n=== H3 (secondary, estimation): memoised - independent argmax gap, n={len(diffs)} ===")
        print(f"  memoised {h3['memoised_mean']:+.1%}  independent {h3['independent_mean']:+.1%}")
        print(f"  difference {mean:+.1%}  SE {se:.1%}  95% CI [{lo:+.1%}, {hi:+.1%}]  "
              f"{h3['seeds_positive']}/{len(diffs)} seeds positive")

    print("\n=== mechanism diagnostic (EXPLORATORY, not a test) ===")
    print("  of the silent post-jump periods, share where one side of the book was empty")
    for arm in ARMS:
        up, down = diagnostics[arm]["up"], diagnostics[arm]["down"]
        if up and down:
            print(f"  {arm:>10}  after UP {statistics.fmean(up):.1%}  after DOWN {statistics.fmean(down):.1%}")

    # Why the static counterparty bound (10g, +10.1pp) need not show up in the
    # market: it counted ANY disagreement among eight callers, and a minority
    # that passes breaks unanimity without supplying a counterparty. Classify
    # the minority actions in the unstable repeated-call states.
    minority = None
    raw = ROOT / "data" / "raw_repeats.json"
    if raw.is_file() and not args.mock:
        import collections
        by_state = collections.defaultdict(list)
        for record in json.loads(raw.read_text(encoding="utf-8")):
            by_state[json.dumps(record["state"], sort_keys=True)].append(
                record["answers"]["action"]["choice"])
        opposite = {"buy": "sell", "sell": "buy"}
        unstable = []
        for actions in by_state.values():
            counts = collections.Counter(actions)
            modal, n = counts.most_common(1)[0]
            if n < len(actions):
                others = {a: k for a, k in counts.items() if a != modal}
                unstable.append({
                    "modal": modal, "modal_share": n / len(actions),
                    "opposite_side_share": others.get(opposite.get(modal), 0) / len(actions),
                    "pass_share": others.get("pass", 0) / len(actions),
                })
        minority = {
            "states": len(by_state), "unstable": len(unstable),
            "unstable_with_opposite_side_minority": sum(1 for u in unstable if u["opposite_side_share"] > 0),
            "max_opposite_side_share": max((u["opposite_side_share"] for u in unstable), default=0.0),
            "unstable_with_pass_minority_or_pass_mode": sum(
                1 for u in unstable if u["pass_share"] > 0 or u["modal"] == "pass"),
            "detail": sorted(unstable, key=lambda u: u["modal_share"]),
        }
        print("\n=== static bound decomposition (EXPLORATORY, from data/raw_repeats.json) ===")
        print(f"  {minority['unstable']}/{minority['states']} unstable states; "
              f"{minority['unstable_with_opposite_side_minority']} have any opposite-side minority "
              f"(largest {minority['max_opposite_side_share']:.0%}); "
              f"{minority['unstable_with_pass_minority_or_pass_mode']} involve pass")

    sources = {f"{arm}_seed{seed}": outcomes[(arm, seed)][2] for (arm, seed) in sorted(outcomes)}
    calls = {f"{arm}_seed{seed}": outcomes[(arm, seed)][1] for (arm, seed) in sorted(outcomes)}
    print("\n=== cost (this invocation's live calls only) ===")
    print(json.dumps(gate.summary(), indent=2))
    payload = {
        "registration": "10h",
        "design": {"seeds": seeds, "traders": args.traders, "periods": args.periods,
                   "burn_in": 5, "window": args.window, "cache": "bypassed"},
        "gaps": gaps,
        "levels": levels,
        "diagnostics": diagnostics,
        "h1": {"mean": m1, "se": se1, "t": t1, "p": p1, "ci95": [lo1, hi1],
               "seeds_positive": sum(1 for v in argmax if v > 0), "n": len(argmax)},
        "h2": {"mean": m2, "se": se2, "t": t2, "p": p2, "ci95": [lo2, hi2],
               "sample_gap_mean": statistics.fmean(sample), "n": len(common)},
        "holm": holm,
        "h3": h3,
        "static_bound_decomposition": minority,
        "calls_per_run": calls,
        "sources": sources,
        "cost_this_invocation": gate.summary(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
