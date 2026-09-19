# Live Jev findings — 2026-09-18

89 live calls against `api.typesafe.ai/v1/systemone`, model `jev-1.13.0`.
Raw data in `data/probe.json`, `data/asymmetry.json`, `data/wording.json`.
Every call is cached under `data/cache*/` and reruns hit cache.

## 1. The wire format is exactly as documented

Endpoint, bearer auth, and the `{state, model, questions}` body all matched the
published reference on first contact. `score` is 0-indexed over `0..levels-1`,
confirmed from the `legend` keys (the docs do not state this).

## 2. Jev is not deterministic

Four identical requests returned:

| call | p(buy) | score | noul |
|---|---|---|---|
| 1 | 0.98 | 2.84 | 0.11 |
| 2 | 0.99 | 2.79 | 0.12 |
| 3 | 0.99 | 2.82 | 0.12 |
| 4 | 0.99 | 2.74 | 0.11 |

There is no seed or temperature parameter. Run-to-run noise is roughly
±0.05 on `score` (±1.2% of the aggressiveness scale) and ±0.01 on
probabilities.

**Consequence:** the response cache is load-bearing for reproducibility, not
just for cost. A rerun without it does not reproduce. `DecisionCache(...,
read_only=True)` raising `CacheMiss` is what makes the Phase 6 public repo
honest.

## 3. Probabilities are rounded to 2dp

Three-option distributions routinely arrive summing to 0.99 or 1.01. This
aborted the first live market run. Now accepted within 0.05 and renormalised,
since the sampling arm draws from it.

## 4. Jev behaves sensibly on the task

Across private values 88..112 against a 99/101 book:

- `aggressiveness` is cleanly monotone in mispricing: 0.25 at edge −12 rising
  to 0.88 at edge +8.
- `already_priced` (noul) peaks at **0.82 exactly at edge 0**, where the book
  really does already reflect the signal, and falls to ~0.09 at large edges.
  That is well-calibrated behaviour on a question we did not tune.
- probabilities are **not** saturated everywhere (range 0.70–1.00), so
  `jev_sample` is a genuinely distinct arm near the decision boundary and
  collapses to `jev_argmax` away from it.

## 5. The main result: wording induces a large conviction asymmetry

Our original criteria produced a **+0.250** gap in conviction between the buy
and sell sides at equal |mispricing|, with the missing mass sitting on `pass`.
It replicates at a second price level and survives option reordering and
neutral option names — but it disappears under mirror-image wording.

| Variant | acquire | dispose | asymmetry |
|---|---|---|---|
| original (`underpriced`/`overpriced`, buy-first instructions) | 0.988 | 0.738 | **+0.250** |
| baseline @ book 149/151 | 0.985 | 0.760 | +0.225 |
| option order reversed | 0.988 | 0.753 | +0.235 |
| neutral option names (`option_a/b/c`) | 0.982 | 0.797 | +0.185 |
| symmetric "gain" framing, buy/sell labels | 0.982 | 0.825 | +0.157 |
| **mirror wording, neutral instructions, neutral names** | 1.000 | 0.995 | **+0.005** |
| mirror, directions listed in the opposite order | 1.000 | 0.988 | +0.012 |

**Jev is symmetric when asked symmetrically.** The asymmetry is induced by
ordinary, natural-sounding domain wording, not by the model.

The effect is ~25x the model's own run-to-run noise (§2), so it is not
measurement error.

**Why it matters — corrected after the market pilot.** On the probe grid
(|edge| >= 2) the argmax is correct on both sides at every point, which led us
to claim the bias is invisible to anyone reading only `.choice`. **That claim
was wrong.** In a live market most states sit near edge 0, and there the
elevated sell-side `pass` mass is large enough to flip the mode itself.
Measured over 954 cached live decisions:

| wording | mode is `pass`, buy side | mode is `pass`, sell side | gap |
|---|---|---|---|
| original | 0.7% | 8.3% | **+7.6pp** |
| mirror | 0.0% | 2.4% | +2.4pp |

| wording | mean mass on `pass`, buy side | sell side | gap |
|---|---|---|---|
| original | 0.067 | 0.254 | **+0.188** |
| mirror | 0.013 | 0.028 | +0.015 |

So the induced asymmetry reaches the market through **two** channels, not one:
sampling (always), and mode-flipping to `pass` (often enough to matter). The
direction is never wrong under argmax -- but the *abstention* is asymmetric,
and abstention is what removes liquidity from one side of the book.

## 6. Labels outweigh the criteria they are attached to

In a `label_swap` variant the option named `"sell"` carried the *buy*
description and vice versa. Jev chose the option literally named `"buy"` at all
8 edges, including strongly negative ones where buying is plainly wrong — it
followed the label and ignored the rubric.

Caveat a referee will raise: that input is deliberately self-contradictory, so
this is evidence that labels carry substantial weight, not that the model
cannot read criteria. Worth a cleaner follow-up before it goes in a paper.

## 7. Open questions for TypeSafe

1. **Pricing and rate limits.** Not published anywhere we could find. What is
   the free-tier limit, and the per-token price? `SpendGate` refuses to enforce
   a dollar cap it cannot compute.
2. **Are `probabilities` calibrated posterior mass, or post-hoc sharpened?**
   They arrive at 2dp and often at exactly 1.00/0.00. This determines whether
   they can be used for sampling or calibration work at all.
3. **What is `confidence` computed from?** We saw `confidence: 0.99` alongside
   `probabilities: {buy: 1.0, ...}`. It is clearly not just `max(probabilities)`.
4. **Is `score` guaranteed 0-indexed over `0..levels-1`?** We inferred it from
   the `legend` keys; the reference does not say.
5. **Is there a seed or determinism mode?** §2 shows there is run-to-run
   variation with no way to pin it.
6. **Do mixed questions in one call really not condition on each other?** The
   docs say "in parallel and in isolation". Our design depends on it.
7. **Any guidance on authoring symmetric criteria?** Writing criteria in
   natural domain language ("underpriced/overpriced", "acquire/dispose")
   induced a 25-point asymmetry in `probabilities` between two mirror-image
   options; strict mirror wording removed it (§5). Worth documenting, since
   the effect is invisible to anyone reading only `.choice`.


## 8. Market pilot — the prediction failed, and why that is useful

One seed, 100 periods, 8 traders, 5 cells; stopped by the spend gate at 2,501
live calls partway through the fifth.

| cell | RMSE(up) | RMSE(down) | down − up | pass rate |
|---|---|---|---|---|
| `zi` | 4.31 | 3.49 | **−0.82** | 8.5% |
| `jev_argmax/original` | 4.46 | 4.78 | +0.32 | 10.4% |
| `jev_sample/original` | 3.54 | 3.93 | +0.39 | 22.5% |
| `jev_argmax/mirror` | 4.45 | 4.48 | +0.03 | 8.3% |
| `jev_sample/mirror` | — | — | gate tripped | — |

**Two things went wrong with the prediction, one substantive and one fatal.**

*Substantive:* we predicted a gap only in `jev_sample/original`. `jev_argmax/
original` shows +0.32, nearly as large. The cache analysis in §5 explains it —
the mode flips to `pass` asymmetrically — so the mechanism is real but has two
channels rather than one. The wording contrast still behaves: +0.32 under
original vs +0.03 under mirror, for the same decode rule.

*Fatal:* **the pilot cannot distinguish any of this from noise.** `zi` is
symmetric by construction and returned −0.82, larger in magnitude than every
Jev effect. With random jumps, one seed gives different counts of up and down
jumps, at different magnitudes, from different price levels. Per-seed noise on
this statistic is at least ±0.8; the effects are ~0.3–0.4.

**Fix: `MatchedJumpFundamental`.** Evenly spaced, identical magnitude, strictly
alternating direction, even count. Every up window is matched by a down window
of the same size between the same two price levels, so the comparison is paired
within a run and most of the noise cancels instead of having to be averaged
across seeds. Implemented and tested; costs nothing extra to run.

**Cost, measured:** 2,501 live calls and 1.96M input tokens bought roughly four
cell-seeds — about 625 calls each. Cache hit rate was only 8.9%, far below the
31% the mock suggested, because live runs visit many more distinct book states.
A 5-cell x 5-seed sweep on this design would be ~15,600 calls and ~12M input
tokens. That is very likely beyond a $5 free tier, which is why the matched-jump
redesign (more power per call) matters more than buying more seeds.


## 9. Confirmatory test — the registered hypotheses are NULL

Seeds 4-23, disjoint from the exploratory seeds 0-3. 80 cell-seeds, ~42,000
live calls, $1.36. Controls held throughout (`zi` t=+1.16, `nbr` t=+0.70 at
n=40, both on zero), so the design was sound and the cells interpretable.

| | registered hypothesis | result |
|---|---|---|
| **C1** | `jev_argmax` paired wording contrast > 0 | mean **-0.184**, 95% CI [-0.479, +0.111], 7/19 seeds positive, one-sided p=0.897 |
| **C2** | `jev_sample` contrast < `jev_argmax` contrast | mean +0.161, p=0.800 |

Both NOT significant; C1's point estimate is the wrong sign. The exploratory
+0.629 (4/4 seeds positive, Holm p=0.061) was a **false positive**, and the
confirmatory CI excludes it entirely. At SE 0.140 the run had ample power to
see +0.63 (t would have been ~4.5), so this is evidence of absence.

This is the outcome the preregistration committed to publishing, and it stands:
**natural wording measurably skews Jev's stated conviction (+0.250, §5) but
does not measurably change post-jump pricing error.**

## 10. The metric was measuring the wrong thing

One cell-seed returned NaN. Investigating it rather than dropping it changed
the project. In `jev_argmax/original` seed 7:

| jump | direction | periods with a trade, 15-period window |
|---|---|---|
| t=20 | up | **0/15** |
| t=40 | down | 15/15 |
| t=60 | up | **0/15** |
| t=80 | down | 12/15 |
| t=100 | up | **0/15** |
| t=120 | down | 15/15 |

270 trades in the run, none of them in the 45 periods following an up jump.

`post_jump_rmse` is computed only over periods that traded, so it **discards
exactly the periods where the effect is strongest**. C1 was measuring pricing
error in the windows that still had trades while the real effect was the
windows going silent. The null in §9 is correct for the question it asked; the
question was wrong.

## 11. The real effect is decode, not wording

Share of post-jump periods that produced a trade, n=20 seeds, replayed from
cache at zero cost:

| cell | up jumps | down jumps | gap | t |
|---|---|---|---|---|
| `jev_argmax/original` | 66.6% | 93.8% | **+27.2pp** | +4.9 |
| `jev_argmax/mirror` | 71.6% | 96.1% | **+24.6pp** | +4.7 |
| `jev_sample/original` | 93.0% | 93.9% | +0.9pp | +1.0 |
| `jev_sample/mirror` | 97.2% | 99.3% | +2.1pp | +3.3 |
| `zi` | 77.3% | 75.0% | -2.3pp | -1.6 |
| `nbr` | 99.8% | 99.3% | -0.4pp | -1.3 |

Paired wording contrast on this measure: `jev_argmax` +2.7pp (t=0.57),
`jev_sample` -1.2pp (t=-1.10). **Both null.**

So the wording is not the cause. The **decode rule** is:

- argmax halts the market after up jumps, under BOTH wordings, at t~5.
- sampling from the same distribution removes the asymmetry almost entirely.
- the two algorithmic baselines show nothing.

**Mechanism.** Under full information every trader sees the same `F_t` and the
state is rounded to whole ticks, so traders with nearby private values submit
*identical* requests. Argmax is a deterministic function of the request, so
they return identical decisions: the arm herds perfectly, everyone wants the
same side, and there is no counterparty. Sampling breaks the tie -- even at
p(buy)=0.99 it produces ~1% sellers, which is enough to clear the market.

Not yet explained: why the halt is asymmetric (up jumps far worse than down)
even under mirror wording, where conviction is symmetric. `zi` and `nbr` show
no such asymmetry, so it is specific to the herding regime.

**Status: post-hoc.** This was found by investigating a NaN in seeds 4-23, so
those seeds cannot test it. It needs registering and running on fresh seeds
before it is a result. The effect is large (t~5 at n=20), so a confirmatory run
can be small.
