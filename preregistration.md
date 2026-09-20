# Preregistration — LLM traders in a continuous double auction (v1)

**Status:** Phase 0 draft. Frozen sections are marked FROZEN.
**Schema frozen:** `schema/schema_jev_v1.json`, 2026-09-18.
**Written before:** any Jev call, any live-model run, any plot of an LLM arm.

This document exists so that the result is decided by the design and not by
which figure turned out to look best. Anything not written here before Phase 3
is exploratory and must be labelled exploratory in the paper.

---

## 1. What is being tested

A continuous double auction in one abstract good `X`. A jumping fundamental
`F_t` sets the common component of value; each trader's private value is
`F_t + epsilon_i,t`. Code owns matching, budgets, order sizes and the book.
A trader's brain answers exactly three things and nothing else:

| Question | System One primitive | Returns |
|---|---|---|
| `action` | `choice` over buy/sell/pass | `choice`, `probabilities`, `confidence` |
| `aggressiveness` | `score`, 5 ordered levels | fractional level, normalised to [0,1] |
| `already_priced` | `noul` | a probability in [0,1], never thresholded |

This is the frozen contract (`schema_jev_v1.json`), whose question wording is
hash-locked (`instructions_sha256`) and enforced by `tests/test_decision.py`.
The model never names a price, a size, or a counterparty.

**Jev emits no text.** There is no `rationale` field and no qualitative
appendix is possible. `confidence` is likewise not self-reported: it is the
probability mass the arm placed on the action it took, which every arm has --
ZI reports its fixed randomisation, NBR its softmax, Jev its `probabilities`.
That makes the calibration outcome comparable across all four arms.

**A model cannot express a losing price.** `quoting.quote_price` clamps every
quote at the trader's own private value, so a bad answer degrades to a bad
trade, never to a broken run. That clamp is the reason the comparison is about
judgement rather than about arithmetic slips.

### 1.1 Design — FROZEN 2026-09-18 (revised after the Phase 3 wording probe)

**2x2: wording x decode**, plus two baselines. All six cells run on the same
engine, the same seeds, and the same fundamental paths.

| Cell | Wording | Decode |
|---|---|---|
| `jev_argmax` / `original` | natural domain wording | take `answers.action.choice` |
| `jev_sample` / `original` | natural domain wording | draw from `answers.action.probabilities` |
| `jev_argmax` / `mirror` | direction-neutral control | take the choice |
| `jev_sample` / `mirror` | direction-neutral control | draw from the distribution |
| `zi` | — | random, symmetric by construction |
| `nbr` | — | logit best-response |

The two wordings are frozen in `schema_jev_v1.json` and
`schema_jev_v1_mirror.json`, both hash-locked, and a test asserts they differ
**only** in the `action` question.

**Why this replaced the original 4-brain x 2-information design.** Two Phase 3
measurements forced it. First, `zi` re-prices in about one period under full
information (post-jump RMSE 1.78 vs steady-state 1.29), so the full-information
arm had almost no headroom and H2 was at risk of being true by construction.
Second, and decisively, the wording probe (`FINDINGS.md` §5) showed a +0.250
buy/sell conviction asymmetry under our natural wording that fell to +0.005
under mirror wording. That gave the project a manipulation *and* a control,
which the original design never had.

### 1.1.1 The prediction — REVISED 2026-09-18 after the Phase 3 pilot

**The original prediction was wrong and is recorded here as wrong**, not
silently replaced. It said:

> A gap appears only in `jev_sample`/`original`; `jev_argmax` is immune because
> its mode is correct on both sides.

The pilot falsified the second clause. `jev_argmax`/`original` returned a
+0.32 gap against +0.39 for sampling. Analysis of 954 cached live decisions
(`FINDINGS.md` §5) found why: the induced asymmetry does not only shift mass,
it **flips the mode to `pass`** on the sell side — 8.3% of sell-side states vs
0.7% of buy-side ones under the original wording, against 2.4% vs 0.0% under
mirror. Argmax never picks the wrong *direction*; it abstains asymmetrically,
and abstention is what withdraws liquidity from one side of the book.

**Revised prediction, to be tested on the matched-jump runs:**

| | argmax | sample |
|---|---|---|
| **original** | gap > 0 (mode-flip channel only) | gap > 0, **larger** (mode-flip + sampling) |
| **mirror** | ~0 | ~0 |

- **Primary test.** The wording main effect on `RMSE(down) - RMSE(up)`:
  original minus mirror, pooled over decode modes. Predicted positive.
- **Secondary test.** Within the original wording, `jev_sample` gap exceeds
  `jev_argmax` gap — the sampling channel adds to the mode-flip channel.
- **Falsification.** A gap of comparable size under `mirror`, or in `zi`/`nbr`,
  kills the mechanism.

This revision is **exploratory-to-confirmatory**: it was informed by the pilot,
so the pilot cannot also be its evidence. The matched-jump runs are the
confirmatory test and the pilot is reported as the exploratory step that
produced the hypothesis.

### 1.1.2 Why the jump process is designed, not random — FROZEN

The pilot's decisive failure was statistical, not substantive: `zi`, which is
symmetric by construction, returned a **-0.82** up/down gap on one seed —
larger than every effect being measured. With random jumps each run draws
different counts of up and down jumps, at different magnitudes, from different
price levels.

`MatchedJumpFundamental` removes that by design: evenly spaced jumps, identical
magnitude, strictly alternating direction, guaranteed even count. Every up
window is paired with a down window of the same size between the same two price
levels, so the comparison is within-run and matched, and the noise cancels
instead of having to be averaged across seeds. `zi` and `nbr` returning ~0 under
this design is the check that it worked.

### 1.2 CDA vs call market — DECIDED: continuous double auction

Chosen because the primary outcome is *speed* of price discovery after a jump,
and a call market quantises exactly the thing being measured. A single-period
call market is retained as a **robustness arm only** (Section 7), not as a
second economy.

---

## 2. Hypotheses

**SUPERSEDED.** H1-H5 were the hypotheses of the original four-brain design,
written before the Phase 3 measurements that retired it (see 1.1). They were
never tested and no result in the paper rests on them. The live registrations
are 10a (C1/C2), 10b (D1/D2) and 10c (E1/E2), each committed before its data
existed. The placeholder that stood here is removed rather than left to imply
a pending action.

---

## 3. Primary outcomes — FROZEN

Exactly three. Implemented in `src/jevmarket/metrics.py`, each pinned to a
hand-worked test case in `tests/test_metrics.py`.

1. **Post-jump RMSE, split by jump direction.**
   `post_jump_rmse_by_sign(prices, fundamental, jump_times, window=20)`. Root
   mean squared deviation of the per-period VWAP from `F_t` over the 20 periods
   following each jump, pooled separately over up-jumps and down-jumps. The
   headline statistic is the **gap**, `RMSE(down) - RMSE(up)`, per cell.
   Periods with no trade are dropped, not interpolated.
2. **Expected calibration error (ECE).** `expected_calibration_error`, 10
   equal-width bins over `confidence`, defined for every arm as
   `action_probabilities[action taken]`. Jev's own `confidence` scalar is
   logged but is a *secondary* outcome. A call is *correct* if its direction
   was the profitable one — see 3.1.
3. **Confidently-wrong rate.** Share of calls with `confidence >= 0.8` that
   were incorrect under the same definition.

### 3.1 What "correct" means — FROZEN

For a decision at period `t` with private value `v`:

- `buy` is correct iff `F_t > P_t`, where `P_t` is the per-period VWAP (the
  trader was buying something the market was underpricing).
- `sell` is correct iff `F_t < P_t`.
- `pass` is correct iff the signal really was already priced, defined as
  `|F_t - P_t| <= 0.5 * private_value_sd`. Because `already_priced` comes back
  as a probability rather than a boolean, it is scored as a second calibration
  surface in its own right (Brier score), not collapsed to a yes/no.
- Periods with no trade contribute no `P_t` and are dropped from calibration.

This definition is fixed now, before any Jev output exists.

## 4. Secondary outcomes — labelled secondary in the paper

Overall RMSE, realised surplus per trader, allocative efficiency vs. the
competitive benchmark, trade volume, spread, rejected-order counts, share of
decisions that are `pass`, and the `already_priced` hit rate.

## 5. Nuisance / cost outcomes

Dollars per run, tokens per call, wall-clock, schema-violation rate, and
retry count. The **LLM structured-output arm is a cost/error subsample**, not
a fifth economy. Measured in Phase 3, before buying 30 seeds.

---

## 6. Analysis plan

- **Seeds.** >= 5 seeds for the Phase 4 pilot; 30 seeds for the headline table,
  conditional on the Phase 3 cost measurement clearing the spend gate.
- **Unit of analysis.** One run = one (brain, treatment, seed). Runs are
  independent; within-run periods are not.
- **Test.** For each primary outcome, a between-arm comparison on run-level
  means, with bootstrap CIs over seeds. No period-level significance tests.
- **Multiple comparisons.** 3 primary outcomes x the contrasts named in H1–H5.
  Holm correction within each outcome family.
- **Stopping rule.** Seed count is fixed in advance per phase. No looking at
  results and adding seeds.

## 7. Robustness (pre-declared, secondary)

Call market instead of CDA; `private_value_sd` at half and double; jump size at
half and double; post-jump window at 10 and 40; ECE with 5 and 20 bins;
confidently-wrong threshold at 0.7 and 0.9.

## 8. What would falsify the interesting claim

If Jev's post-jump RMSE is indistinguishable from `zi` under **both**
treatments, there is no discovery story and the paper is a calibration paper.
If Jev's ECE is at or below `nbr`'s, H3/H4 are dead and the paper reports that.
Both outcomes get written up.

## 9. Explicitly out of scope in v1

No second good. No bank, credit, or lending. No macro aggregates. No map,
geography, or transport. No branded or differentiated goods. No inventory
sizing channel (order size is fixed at 1 unit). No agent memory across
periods beyond what is in `Observation`. These are sequels, after Table 1.

---

## 10. Engine decisions taken in Phase 0 — FROZEN

Recorded because each one is a degree of freedom that could otherwise be
tuned after seeing results.

| Decision | Choice | Why |
|---|---|---|
| Price grid | integer ticks | exact arithmetic; conservation is checkable to the unit |
| Trade price | the **resting** order's price | standard CDA; incoming order gets price improvement |
| Priority | price, then time | standard |
| Self-trade | submitting on one side pulls the trader's resting orders on the other | prevents wash trades without leaving a crossed book |
| Order replacement | a trader's resting orders are withdrawn at the top of its turn | keeps the book fresh; one live order per trader |
| Order size | fixed at 1 unit | sizing is a second channel; shutting it off isolates aggressiveness |
| Shorting / borrowing | both disallowed (`max_short=0`, `max_borrow=0`) | "conserved accounts": no trader can deliver what it does not hold |
| Period price | volume-weighted mean of that period's trades; `None` if none | avoids last-trade noise |
| Arrival order | reshuffled every period, seeded | no positional advantage |
| Private value | `signal + N(0, private_value_sd)`, redrawn each period | standard induced-value design |
| Fundamental | piecewise constant, Bernoulli(`jump_prob`) jumps of `N(0, jump_sd)` | makes "how fast does price find `F`" well posed |
| RNG | every draw seeded on `(seed, period, index)`, never a running stream | a rerun reproduces exactly, independent of call order |
| ZI action space | ZI emits the same `Decision` as Jev | the arms differ only in the function, not the interface |
| Jev call shape | one call per decision, all three questions together | cheapest; TypeSafe evaluates mixed questions in parallel and in isolation |
| Conditioning | `aggressiveness` is NOT conditioned on the chosen `action` | a consequence of that isolation, pre-registered rather than discovered |
| State shown to Jev | book, spread, last trade, own private value, own signal -- all rounded to whole ticks | frozen in `schema_jev_v1.json` as `state_fields` |
| Cash/inventory in state | excluded | they change after every fill, which made every decision a unique cache key and collapsed the hit rate from 31% to 1%. The exchange enforces both constraints in code, so Jev never needs them |
| Period number in state | excluded | not decision-relevant, and including it makes the cache worthless |

## 10a. Confirmatory test — REGISTERED 2026-09-18, BEFORE the run

The 4-seed matched-jump sweep (seeds 0-3) is **exploratory**. It produced two
results and one new hypothesis, none of which it can itself test:

- `jev_argmax` paired contrast +0.629, 4/4 seeds positive, t=3.88, raw p=0.030,
  **Holm p=0.061 — not significant.**
- `jev_sample` paired contrast -0.339, t=-0.84, p=0.464. The revised prediction
  that sampling would show the *larger* effect is falsified.
- **New hypothesis (post-hoc, from those seeds):** sampling *dilutes* the
  induced asymmetry rather than transmitting it. Under the original wording the
  distribution is soft, so sampling randomises on both sides (pass rate 19.6%
  vs 6.6% under mirror), and that symmetric noise washes out the systematic
  sell-side abstention. Under mirror the distribution is near-saturated, so
  sampling is effectively argmax (6.3% vs 5.6% pass).

**Confirmatory run: seeds 4-23, disjoint from every seed used so far.** All four
Jev cells. Nothing below was chosen after seeing seeds 4-23, because they do
not exist yet.

| | Hypothesis | Test |
|---|---|---|
| **C1 (primary)** | `jev_argmax` paired contrast > 0 | paired t over 20 seeds |
| **C2 (primary)** | `jev_sample` paired contrast < `jev_argmax` paired contrast | paired t on the difference of contrasts |

- **Correction.** Holm across the C1/C2 family. Significance requires Holm
  p < 0.05.
- **Power.** Observed paired sd 0.32; at n=20, SE ~ 0.072, so a +0.63 effect
  gives t ~ 8.7. The run is therefore decisive in either direction: a null
  result at this n is real evidence of absence, not weak evidence.
- **Controls that must hold.** `zi` and `nbr` gaps must remain consistent with
  zero (n=40 null calibration: t=+1.16 and +0.70). If either moves, the design
  is at fault and the Jev cells are not to be interpreted.
- **Falsification.** C1 failing at n=20 retires the mechanism. We would then
  report a precisely-estimated null: natural wording measurably skews Jev's
  conviction (+0.250, §5 of FINDINGS) but does **not** measurably move market
  price discovery. That is a publishable negative and it will be written up as
  one.

## 10b. Second confirmatory test — REGISTERED 2026-09-19, BEFORE the run

The trade-cessation result (`FINDINGS.md` §11) is **post-hoc**: it was found by
investigating a NaN in seeds 4-23, so those seeds cannot test it. Registered
here on **seeds 24-43**, disjoint from every seed used so far.

### What changed, and why the outcome measure is different

The first confirmatory test measured post-jump RMSE and returned a clean null.
That null is correct for the question it asked, but the question was wrong:
RMSE is defined only over periods that traded, so it discarded exactly the
periods where the effect lives. The outcome measure here is therefore
**liquidity, not pricing error**:

    traded_share(direction) = share of the 15 periods after a jump of that
                              direction in which at least one trade occurred

This is defined for every period, including the silent ones.

### Hypotheses

| | Hypothesis | Test |
|---|---|---|
| **D1 (primary)** | `jev_argmax` trades less after UP jumps than after DOWN jumps: `traded_share(down) - traded_share(up) > 0` | paired t over 20 seeds |
| **D2 (primary)** | that gap is larger for `jev_argmax` than for `jev_sample` | paired t on the within-seed difference of gaps |

- **Correction.** Holm across the D1/D2 family; Holm p < 0.05 required.
- **Power.** Exploratory estimate +27.2pp at t=4.9, n=20, implying sd ~24.6pp.
  At n=20, SE ~5.5pp, so a true effect of that size gives t ~5. Decisive either
  way; a null at this n is evidence of absence.
- **Cells.** `jev_argmax/original` and `jev_sample/original` only. The wording
  dimension is deliberately dropped: it was measured at +2.7pp (t=0.57) on this
  outcome and is not part of either hypothesis, so spending a third of the
  remaining budget to re-confirm a null would be waste.
- **Controls.** `zi` and `nbr` on the same seeds (free). Both must stay
  consistent with zero (established at n=40: -2.3pp and -0.4pp).
- **Falsification.** D1 failing retires the finding, and we report a
  precisely-estimated null. D2 failing while D1 holds means the halt is not
  about the decode rule, and the mechanism claim is wrong even if the effect
  is real.

### Mechanism — MEASURED, not predicted

Section 11 of FINDINGS could not explain why the halt is worse after UP jumps
than after DOWN jumps, and two attempts to predict a mechanism in this project
have already failed. So this run instruments rather than guesses.
`RunResult.bid_depth` / `ask_depth` now record resting quantity on each side at
the close of every period, which separates two different failures:

- **no counterparty** — one side has depth, the other is empty. Every trader
  wants the same side.
- **no crossing** — both sides have depth but the prices do not meet.

This is reported as an exploratory diagnostic, explicitly not a test, and it is
labelled as such in any write-up.

## 10c. Market-size sweep — REGISTERED 2026-09-19, BEFORE the run

This is a robustness check and a **mechanism test at the same time**, and it is
registered before the data exists.

### The mechanism, stated as a number

The claim is that the market halts after a jump because every trader reaches
the same conclusion, leaving no counterparty. Measured directly
(`FINDINGS.md`, rounding probe): about **92%** of traders pick the same side in
the instant after an up jump, and this is unaffected by state rounding.

If that is the cause, then the probability that ALL `N` traders agree is
roughly `0.92^N`, and halting must **fall sharply as the market grows**:

| Traders | 0.92^N | expected halting |
|---|---|---|
| 4 | 0.72 | severe |
| 8 | 0.51 | as measured (up traded 66.6%) |
| 16 | 0.26 | much milder |
| 32 | 0.07 | nearly gone |

The real market is more forgiving than this bound -- stale orders persist, and
a window spans 15 periods -- so the levels will not match exactly. The
*direction and steepness* are what is being tested.

### Hypotheses

| | Hypothesis | Test |
|---|---|---|
| **E1 (primary)** | the `jev_argmax` up/down trading gap **decreases** with market size | OLS slope of gap on `log2(N)`, across N in {4, 8, 16, 32}; predicted negative |
| **E2 (primary)** | the `jev_sample` gap shows no such decay | same slope for sampling; predicted indistinguishable from zero |

- **Correction.** Holm across the E1/E2 family.
- **Sizes.** N in {4, 8, 16, 32}. **N=2 is excluded**, and N=4 is flagged as
  floor-constrained, on the basis of a free structural check run BEFORE the
  sweep. `zi` and `nbr` are symmetric by construction, so their trading rate at
  each size measures what the market can do structurally:

  | N | zi periods traded | nbr periods traded | zi up/down gap |
  |---|---|---|---|
  | 2 | 10.8% | 21.6% | -0.4% |
  | 4 | 32.9% | 70.3% | -4.2% |
  | 8 | 76.2% | 99.4% | +2.0% |
  | 16 | 99.4% | 99.9% | -0.4% |
  | 32 | 100.0% | 100.0% | +0.0% |

  A thin market barely trades whatever its traders believe, so a +25pp halting
  gap is arithmetically impossible at N=2. Since the prediction is that halting
  worsens at small N, thinness would mimic the mechanism and we would measure a
  confound. Conversely at N=16 and N=32 the symmetric arms trade ~100% of
  periods with a zero gap, so there is **no structural floor** and any argmax
  halting there is unambiguously attributable to the arm. That is where E1 is
  most falsifiable, and it is the part of the curve the test rests on.

- **Seeds.** 20 per cell per size (seeds 24-43), fixed in advance. N=8 is
  already cached from prereg 10b and costs nothing.
- **Per-size control.** `zi` and `nbr` run free at every size; the argmax gap is
  read against the symmetric-arm gap at the SAME size, so any residual
  structural effect is differenced out.
- **Falsification, and why this test matters.** If the argmax gap is **flat or
  rising** in N, the no-counterparty mechanism is WRONG even if the effect
  itself is real, and the finding would have to be reported without a
  mechanism. Two mechanism predictions in this project have already failed
  (prereg 1.1.1, and the sampling-amplification prediction), so this one is
  deliberately quantitative and falsifiable rather than a story fitted after
  the fact.
- **Secondary.** Whether the *level* of `traded_share(up)` tracks `1 - 0.92^N`.
  Exploratory: the bound ignores stale liquidity and multi-period windows.

## 11. Deviation log

Any departure from this document gets a dated row here, with the reason,
**before** the affected runs are executed.

| Date | Section | Change | Reason |
|---|---|---|---|
| 2026-09-18 | — | Document created. | Phase 0. |
