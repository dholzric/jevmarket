"""Recompute a FIXED LIST of statistics from the saved data files.

SCOPE, stated plainly because overstating it caused two review failures.
This script checks that numbers hard-coded *in this script* still match
data/*.json. It does not read the manuscript. "55/55" therefore means the
data has not shifted under the analysis -- it is a data-regression test, not
a manuscript audit, and it cannot detect a paper that says something else.

Some entries below are deliberately retained as SUPERSEDED: they are the
pooled statistics the paper used before the seed-aware reanalysis. Keeping
them pinned documents what changed and stops the old numbers being quietly
rederived. They are labelled, and must not be cited as current.

For the manuscript itself use:
    scripts/audit_manuscript.py   tables, provenance, build
    scripts/audit_prose.py        headline claims, with mutation tests

Makes no API calls.

    python scripts/verify_paper.py
"""

from __future__ import annotations

import json
import math
import pathlib
import statistics
import sys

import numpy as np
import scipy.stats as st

DATA = pathlib.Path("data")
checks: list[tuple[str, str, object, object, bool]] = []


def check(section, claim, claimed, actual, tol=0.05):
    if isinstance(claimed, (int, float)) and isinstance(actual, (int, float)):
        ok = abs(claimed - actual) <= tol
    else:
        ok = claimed == actual
    checks.append((section, claim, claimed, actual, ok))


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def one_sided_t(values, alternative="greater"):
    mean, sd = statistics.fmean(values), statistics.stdev(values)
    se = sd / len(values) ** 0.5
    t = mean / se
    p = (st.t.sf(t, len(values) - 1) if alternative == "greater"
         else st.t.cdf(t, len(values) - 1))
    lo, hi = st.t.interval(0.95, len(values) - 1, loc=mean, scale=se)
    return mean, se, t, p, lo, hi


# --- Experiment 1: wording --------------------------------------------------
w = load("wording.json")["summary"]
check("Exp 1", "original wording asymmetry = 0.250", 0.250, w["original"]["asymmetry"], 0.002)
check("Exp 1", "mirror wording asymmetry = 0.005", 0.005, w["mirror"]["asymmetry"], 0.002)
check("Exp 1", "original conviction buying = 0.988", 0.988, w["original"]["mean_p_acquire"], 0.002)
check("Exp 1", "original conviction selling = 0.738", 0.738, w["original"]["mean_p_dispose"], 0.002)
check("Exp 1", "mirror conviction buying = 1.000", 1.000, w["mirror"]["mean_p_acquire"], 0.002)
check("Exp 1", "mirror conviction selling = 0.995", 0.995, w["mirror"]["mean_p_dispose"], 0.002)

# --- Experiment 1: the preregistered null (C1) ------------------------------
c = load("confirmatory.json")["results"]
gaps = {(r["cell"], r["seed"]): r["post_jump_down"] - r["post_jump_up"] for r in c}
seeds = sorted({r["seed"] for r in c})
paired = [
    gaps[("jev_argmax/original", s)] - gaps[("jev_argmax/mirror", s)]
    for s in seeds
    if not (math.isnan(gaps[("jev_argmax/original", s)])
            or math.isnan(gaps[("jev_argmax/mirror", s)]))
]
mean, se, t, p, lo, hi = one_sided_t(paired)
check("Exp 1 null", "C1 mean = -0.184", -0.184, mean, 0.002)
check("Exp 1 null", "C1 CI low = -0.479", -0.479, lo, 0.002)
check("Exp 1 null", "C1 CI high = +0.111", 0.111, hi, 0.002)
check("Exp 1 null", "C1 one-sided p = 0.897", 0.897, p, 0.002)
check("Exp 1 null", "C1 seeds positive = 7/19",
      "7/19", f"{sum(1 for v in paired if v > 0)}/{len(paired)}")

# --- Experiment 2: liquidity (D1/D2) ---------------------------------------
cc = load("cessation_confirm.json")["gaps"]
argmax = list(cc["jev_argmax/original"].values())
sample = list(cc["jev_sample/original"].values())
mean, se, t, p, lo, hi = one_sided_t(argmax)
check("Exp 2", "D1 gap = +25.8pp", 25.8, mean * 100, 0.1)
check("Exp 2", "D1 CI = [17.3, 34.2]", 17.3, lo * 100, 0.1)
check("Exp 2", "D1 CI high = 34.2", 34.2, hi * 100, 0.1)
check("Exp 2", "D1 t = 6.37", 6.37, t, 0.02)
check("Exp 2", "D1 seeds positive = 18/20",
      "18/20", f"{sum(1 for v in argmax if v > 0)}/{len(argmax)}")
check("Exp 2", "sampling gap = +3.1pp", 3.1, statistics.fmean(sample) * 100, 0.1)
d2mean, d2se, d2t, d2p, d2lo, d2hi = one_sided_t([a - b for a, b in zip(argmax, sample)])
check("Exp 2", "D2 difference = +22.7pp", 22.7, d2mean * 100, 0.1)
check("Exp 2", "D2 t = 6.01", 6.01, d2t, 0.02)
check("Exp 2", "zi control = -0.4pp", -0.4, statistics.fmean(cc["zi"].values()) * 100, 0.1)
check("Exp 2", "nbr control = +1.0pp", 1.0, statistics.fmean(cc["nbr"].values()) * 100, 0.1)

# levels quoted in the abstract
cell = load("market_size.json")
check("Exp 2", "argmax traded after up = 65.6%", 65.6, cell["jev_argmax|8"]["up"] * 100, 0.1)
check("Exp 2", "argmax traded after down = 91.3%", 91.3, cell["jev_argmax|8"]["down"] * 100, 0.1)
for arm, key, up, down in (("Jev-sample", "jev_sample", 92.2, 95.3),
                           ("ZI", "zi", 76.0, 75.6), ("NBR", "nbr", 98.7, 99.7)):
    check("Exp 2", f"{arm} traded after up = {up}%", up, cell[f"{key}|8"]["up"] * 100, 0.1)
    check("Exp 2", f"{arm} traded after down = {down}%", down, cell[f"{key}|8"]["down"] * 100, 0.1)

# --- Experiment 3: market size (E1/E2) --------------------------------------
sizes = [4, 8, 16, 32]
for n, claimed in zip(sizes, [37.0, 25.8, 12.3, 4.2]):
    check("Exp 3", f"argmax gap at N={n} = {claimed}pp",
          claimed, cell[f"jev_argmax|{n}"]["gap"] * 100, 0.1)
for arm, label, claimed_slope, claimed_t in (
    ("jev_argmax", "E1", -0.112, -6.91),
    ("jev_sample", "E2", -0.016, -2.53),
):
    # SUPERSEDED: pooled OLS over 80 observations that are 20 seeds x 4 sizes.
    # The paper now reports the seed-paired estimates (checked just below).
    xs, ys = [], []
    for n in sizes:
        for g in cell[f"{arm}|{n}"]["gaps"]:
            xs.append(np.log2(n))
            ys.append(g)
    fit = st.linregress(xs, ys)
    check("Exp 3 [superseded]", f"{label} pooled slope = {claimed_slope}",
          claimed_slope, fit.slope, 0.001)
    check("Exp 3 [superseded]", f"{label} pooled t = {claimed_t}",
          claimed_t, fit.slope / fit.stderr, 0.02)

# The statistics the paper actually reports.
clustered = load("size_slope_clustered.json")
for label, arm, slope_t in (("E1", "jev_argmax", -7.78), ("E2", "jev_sample", -2.00)):
    check("Exp 3 [current]", f"{label} seed-paired t = {slope_t}",
          slope_t, clustered[arm]["paired_t"], 0.02)
check("Exp 3 [current]", "E2 two-sided p = 0.060", 0.060,
      clustered["jev_sample"]["two_sided_p"], 0.002)

# Agreement at the shock, which replaced the static-probe figures as the
# mechanism evidence.
lag = load("lag_flow.json")
check("Mechanism [current]", "agreement at shock, up = 90.0%", 90.0,
      lag["0"]["up"]["buy"] * 100, 0.2)
check("Mechanism [current]", "agreement at shock, down = 59.4%", 59.4,
      lag["0"]["down"]["sell"] * 100, 0.2)
lag_mirror = load("lag_flow_mirror.json")
check("Mechanism [current]", "mirror agreement at shock, up = 89.8%", 89.8,
      lag_mirror["0"]["up"]["buy"] * 100, 0.2)
check("Mechanism [current]", "mirror agreement at shock, down = 64.8%", 64.8,
      lag_mirror["0"]["down"]["sell"] * 100, 0.2)
check("Exp 3", "N=4 zi floor = 33% traded", 33.0,
      (cell["zi|4"]["up"] + cell["zi|4"]["down"]) / 2 * 100, 1.5)

# --- Mechanism --------------------------------------------------------------
r = load("rounding.json")
for key, claimed in (("after UP jump   (F=110, book 99/101)|unrounded", 0.92),
                     ("after DOWN jump (F=100, book 109/111)|unrounded", 0.96)):
    check("Mechanism", f"agreement {key.split('|')[0].strip()} = {claimed:.0%}",
          claimed, r[key]["agreement"], 0.005)
for key, claimed in (("after UP jump   (F=110, book 99/101)|rounded", 0.92),
                     ("after DOWN jump (F=100, book 109/111)|rounded", 0.96)):
    check("Mechanism", f"rounding makes no difference ({key.split('|')[0].strip()})",
          claimed, r[key]["agreement"], 0.005)

flow = load("asymmetry_diagnostic.json")
for direction, claimed in (("up", (65.9, 28.2)), ("down", (48.8, 42.3))):
    counts = flow["order_flow"][direction]
    total = sum(counts.values())
    check("Mechanism", f"argmax buy share after {direction} = {claimed[0]}%",
          claimed[0], counts["buy"] / total * 100, 0.2)
    check("Mechanism", f"argmax sell share after {direction} = {claimed[1]}%",
          claimed[1], counts["sell"] / total * 100, 0.2)
mirror = load("asym_argmax_mirror.json")
for direction, claimed in (("up", (68.2, 27.7)), ("down", (48.1, 45.7))):
    counts = mirror["order_flow"][direction]
    total = sum(counts.values())
    check("Mechanism", f"mirror buy share after {direction} = {claimed[0]}%",
          claimed[0], counts["buy"] / total * 100, 0.2)
    check("Mechanism", f"mirror sell share after {direction} = {claimed[1]}%",
          claimed[1], counts["sell"] / total * 100, 0.2)

silence = flow["silence_reasons"]
for direction, claimed in (("up", 100.0), ("down", 96.2)):
    total = sum(silence[direction].values())
    check("Mechanism", f"argmax 'no seller' share after {direction} = {claimed}%",
          claimed, silence[direction].get("bids only (no seller)", 0) / total * 100, 0.2)

# --- Repeated-response sensitivity (prereg 10d) ------------------------------
rr = load("repeated_response.json")
check("Estimand", "mode stability = 0.976", 0.976, rr["mean_mode_stability"], 0.002)
check("Estimand", "states fully stable = 47/50",
      "47/50", f"{rr['fully_stable_states']}/{rr['states']}")
check("Estimand", "independent agreement = 0.979", 0.979, rr["independent_agreement"], 0.002)
check("Estimand", "memoisation inflation = +2.1pp", 2.1, rr["inflation"] * 100, 0.1)
check("Estimand", "F1 holds", True, rr["F1_holds"])
check("Estimand", "F2 holds", True, rr["F2_holds"])

# --- Estimand tests, realigned (prereg 10d/10e/10f/10g) ----------------------
ec = load("estimand_corrected.json")
check("Estimand", "R = 100 repeats per state", 100, ec["repeats"])
check("Estimand", "fully stable at R=100 = 51/60",
      "51/60", f"{ec['fully_stable']}/{ec['n_states']}")
check("Estimand", "F1 DOES NOT hold", False, ec["F1_holds"])

er = load("estimand_realigned.json")
check("Estimand", "counterparty gain (all) = 10.1pp", 10.1,
      er["f2_realigned"]["all"]["gain"] * 100, 0.1)
check("Estimand", "counterparty gain upper bound = 14.4pp", 14.4,
      er["f2_realigned"]["all"]["gain_upper95"] * 100, 0.1)
check("Estimand", "gain after up = gain after down (to 0.1pp)", True,
      abs(er["f2_realigned"]["after up"]["gain"]
          - er["f2_realigned"]["after down"]["gain"]) < 0.001)
check("Estimand", "G1 mass shift = +0.33pp", 0.33,
      er["g1_realigned"]["mean_shift"] * 100, 0.05)
check("Estimand", "G1 TOST p < 0.0001", True, er["g1_realigned"]["tost_p"] < 0.0001)
check("Estimand", "G1 pairs restricted to corrected population = 60",
      60, er["g1_realigned"]["n"])

# SUPERSEDED twice over: the first F/G run sampled the wrong population and
# scored unregistered statistics; the second compared majority share to a
# liquidity gap. Pinned so the history stays visible; never cite as current.
rr = load("repeated_response.json")
check("Estimand [superseded]", "old F1 sample 47/50",
      "47/50", f"{rr['fully_stable_states']}/{rr['states']}")

# --- Null calibration -------------------------------------------------------
null = load("null.json")
check("Design", "per-run noise sd = 0.74", 0.74, null["zi"]["sd"], 0.01)
check("Design", "zi null t = 1.16", 1.16, null["zi"]["t"], 0.02)
check("Design", "nbr null t = 0.70", 0.70, null["nbr"]["t"], 0.02)

# --- report -----------------------------------------------------------------
width = max(len(c[1]) for c in checks) + 2
section = None
failures = 0
for sec, claim, claimed, actual, ok in checks:
    if sec != section:
        print(f"\n--- {sec} ---")
        section = sec
    shown = f"{actual:.3f}" if isinstance(actual, float) else str(actual)
    mark = "ok  " if ok else "FAIL"
    if not ok:
        failures += 1
    print(f"  [{mark}] {claim:<{width}} data: {shown}")

print(f"\n{len(checks) - failures}/{len(checks)} pinned statistics match the saved data.")
print("This is a DATA-REGRESSION test, not a manuscript audit: it checks numbers")
print("hard-coded in this script, and cannot detect a paper that says otherwise.")
print("For the manuscript run scripts/audit_manuscript.py and scripts/audit_prose.py.")
if failures:
    print(f"{failures} MISMATCH(ES) -- the paper is wrong, not the reviewer.")
sys.exit(1 if failures else 0)
