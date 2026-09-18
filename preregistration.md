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

### 1.1.1 The prediction — stated before the market runs

The induced asymmetry should reach the market **only where sampling transmits
it**, and only under the wording that induces it:

| | argmax | sample |
|---|---|---|
| **original** | no gap | **post-jump RMSE(down) > RMSE(up)** |
| **mirror** | no gap | no gap |

`jev_argmax` is the control that shows the mode is correct on both sides.
`mirror` is the control that shows the asymmetry is in the wording, not the
model. `zi` and `nbr` are symmetric by construction. A gap appearing anywhere
other than `jev_sample`/`original` falsifies the mechanism.

### 1.2 CDA vs call market — DECIDED: continuous double auction

Chosen because the primary outcome is *speed* of price discovery after a jump,
and a call market quantises exactly the thing being measured. A single-period
call market is retained as a **robustness arm only** (Section 7), not as a
second economy.

---

## 2. Hypotheses

> **[ACTION REQUIRED — the plan file was not in the workspace.]**
> H1–H5 must be pasted in **verbatim** from the locked plan before any Jev call
> is made. The drafts below are the author's reconstruction from the stated
> primary outcomes and are **not yet the preregistered text**. Replace this
> whole block, then delete this warning. Do not reword H1–H5 to fit them.

<!-- BEGIN PLACEHOLDER — REPLACE WITH VERBATIM H1-H5 -->

**H1 (discovery).** Under delayed/noisy information, both Jev arms achieve a
lower post-jump RMSE than `zi`, and no worse than `nbr`.

**H2 (no free lunch under full information).** Under full information the
arms are indistinguishable on post-jump RMSE: the signal is the fundamental,
so there is nothing for judgement to add.

**H3 (calibration).** Jev's stated `confidence` is miscalibrated — ECE for
both Jev arms exceeds ECE for `nbr`, in the direction of overconfidence.

**H4 (confidently wrong).** Jev's confidently-wrong rate exceeds `nbr`'s, and
the gap is larger under delayed/noisy information than under full information.

**H5 (sampling vs argmax).** `jev_sample` is better calibrated than
`jev_argmax` (lower ECE) at equal or worse post-jump RMSE — decoding trades
accuracy for honesty.

<!-- END PLACEHOLDER -->

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

## 11. Deviation log

Any departure from this document gets a dated row here, with the reason,
**before** the affected runs are executed.

| Date | Section | Change | Reason |
|---|---|---|---|
| 2026-09-18 | — | Document created. | Phase 0. |
