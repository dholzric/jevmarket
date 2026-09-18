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
A trader's brain answers exactly four things and nothing else:

| Field | Meaning |
|---|---|
| `action` | `buy` / `sell` / `pass` |
| `aggressiveness` | 0 = quote passively at the near touch, 1 = cross the spread |
| `already_priced` | does the book already reflect the signal? |
| `confidence` | probability this call is the profitable one |

This is the frozen contract (`schema_jev_v1.json`). The model never names a
price, a size, or a counterparty. **A model therefore cannot express a losing
price**: `quoting.quote_price` clamps every quote at the trader's own private
value. That clamp is the reason the comparison is about judgement rather than
about arithmetic slips.

### 1.1 Design — FROZEN

4 brains x 2 information treatments, between-run.

| Brain | Description |
|---|---|
| `zi` | Zero-intelligence. Random direction, random aggressiveness, flat 0.5 confidence. Budget- and value-constrained (Gode & Sunder ZI-C in spirit). |
| `nbr` | Noisy best-response. Best response to the book with logit noise. |
| `jev_argmax` | LLM, temperature 0 / greedy decode. |
| `jev_sample` | LLM, sampled from its own output distribution. |

| Information treatment | Signal |
|---|---|
| `full` | `Signal(delay=0, noise_sd=0)` — the trader observes `F_t` exactly |
| `delayed_noisy` | `Signal(delay=d>0, noise_sd=s>0)` — the trader observes `F_{t-d} + N(0, s)` |

That 2x4 is the paper. `zi` and `nbr` exist so that the LLM arms have a floor
and a ceiling a referee recognises.

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

1. **Post-jump RMSE.** `post_jump_rmse(prices, fundamental, jump_times,
   window=20)`. Root mean squared deviation of the per-period VWAP from `F_t`
   over the 20 periods following each jump, pooled across jumps. Periods with
   no trade are dropped, not interpolated.
2. **Expected calibration error (ECE).** `expected_calibration_error`, 10
   equal-width bins over stated `confidence`. A call is *correct* if its
   direction was the profitable one — see 3.1.
3. **Confidently-wrong rate.** Share of calls with `confidence >= 0.8` that
   were incorrect under the same definition.

### 3.1 What "correct" means — FROZEN

For a decision at period `t` with private value `v`:

- `buy` is correct iff `F_t > P_t`, where `P_t` is the per-period VWAP (the
  trader was buying something the market was underpricing).
- `sell` is correct iff `F_t < P_t`.
- `pass` is correct iff `already_priced` matched reality, defined as
  `|F_t - P_t| <= 0.5 * private_value_sd`.
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

## 11. Deviation log

Any departure from this document gets a dated row here, with the reason,
**before** the affected runs are executed.

| Date | Section | Change | Reason |
|---|---|---|---|
| 2026-09-18 | — | Document created. | Phase 0. |
