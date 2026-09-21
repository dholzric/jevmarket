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


## 12. Trade cessation CONFIRMED (prereg 10b), on fresh seeds 24-43

| | registered hypothesis | result |
|---|---|---|
| **D1** | `jev_argmax` trades less after up jumps than down jumps | **+25.8%**, 95% CI [+17.3%, +34.2%], t=+6.37, 18/20 seeds positive |
| **D2** | that gap exceeds `jev_sample`'s | **+22.7%**, CI [+14.8%, +30.6%], t=+6.01 (sampling's own gap: +3.1%) |

Both Holm-significant. Exploratory estimate was +27.2%; confirmatory +25.8% on
seeds that did not generate it.

**Mechanism observed directly.** Share of *silent* post-jump periods in which
one side of the book was completely empty:

| cell | after up | after down |
|---|---|---|
| `jev_argmax` | **100.0%** | 95.6% |
| `jev_sample` | 71.9% | 56.2% |
| `zi` | 3.4% | 5.3% |
| `nbr` | 9.1% | 0.0% |

Every silent argmax period after good news had no counterparty at all. The
symmetric arms go quiet for the ordinary reason instead.

**Control caveat.** `nbr` returned +1.0% (t=+3.33) -- small but distinguishable
from zero, so the market has a slight genuine structural tilt. It is 1/26th the
argmax effect and `zi` is clean (-0.4%, t=-0.22), but the prereg said controls
must sit on zero and strictly this one does not. The per-size controls in §13
net it out: it does not survive there.

## 13. Market-size sweep (prereg 10c): E1 confirmed, **E2 falsified**

> **SUPERSEDED, see §16.** The "E2 falsified" conclusion below rests on a
> pooled regression that treated 20 seeds x 4 sizes as 80 independent points.
> Under the correct seed-paired analysis E1 is *stronger* (t=-7.78) and E2 is
> **unresolved**, not falsified (t=-2.00, two-sided p=0.060). The section is
> left unedited as the contemporaneous record; do not quote its conclusion.

20 seeds per cell per size, 37,259 live calls, 90% cache hit rate, $1.21.

| N | argmax gap | net of `zi` | `zi` gap | `nbr` gap | sample gap |
|---|---|---|---|---|---|
| 4 | +37.0% | +38.7% | -1.7% | -1.3% | +4.3% |
| 8 | +25.8% | +26.2% | -0.4% | +1.0% | +3.1% |
| 16 | +12.3% | +12.7% | -0.3% | +0.1% | -0.1% |
| 32 | **+4.2%** | +4.2% | +0.0% | +0.0% | +0.0% |

**E1 CONFIRMED.** The argmax gap collapses as the market grows: slope
**-0.112 per doubling**, t=-6.91. Robust to dropping the floor-constrained N=4
point (-0.108, t=-4.21). At N=32, where the symmetric arms trade 100% of
periods with a zero gap and there is no structural floor whatsoever, argmax
retains only +4.2%.

This is the no-counterparty mechanism doing exactly what it must. It is the
first mechanism prediction in this project to survive contact with data, and it
was registered before the run.

**E2 FALSIFIED.** We predicted sampling would show NO decay. It shows a real
one: slope -0.016 per doubling, t=-2.53 (two-sided p=0.011). The obvious rescue
-- blaming the floor-constrained N=4 point -- **also fails**: dropping N=4 makes
it *more* significant (t=-3.53), not less.

The honest reading is better than the prediction was. Sampling herds too, just
**7x more weakly**, and its herding dissolves with size on the same curve. At
99% buy probability most sampled traders still pick buy; sampling does not
abolish correlation, it dilutes it. So there is ONE mechanism whose strength is
set by how sharply the decode rule collapses the distribution, not two regimes.

**Quantitative check (secondary, exploratory).** The bound
`traded_share(up) ~ 1 - 0.92^N` is a lower bound, since real books carry stale
liquidity across a 15-period window. Observed sits above it at every size, as
it should, and converges as N grows:

| N | predicted | observed | difference |
|---|---|---|---|
| 4 | 28.4% | 33.9% | +5.5% |
| 8 | 48.7% | 65.6% | +16.9% |
| 16 | 73.7% | 84.1% | +10.5% |
| 32 | 93.1% | 95.7% | +2.6% |

## 14. Where this leaves the project

Established, on registered tests with fresh data:

1. Natural domain wording skews Jev's stated conviction by 25 points (§5); it
   does **not** move post-jump pricing error (§9, a precisely-estimated null).
2. Argmax decoding causes asymmetric market halting (§12, D1/D2), by removing
   the counterparty (100% of silent periods one-sided).
3. That halting collapses as the market grows, exactly as the mechanism
   requires (§13, E1) -- and sampling shows the same effect 7x weaker, which
   falsified our cleaner two-regime story in favour of a single dose-response.

Still unexplained: why halting is worse after UP jumps than DOWN jumps. The
per-size controls show this is not a structural artefact of the market.

## 15. The directional bias is NOT our wording

The trade-cessation effect decomposes into two parts (§12-13). Unanimity sets
its magnitude and produces the size-scaling. A standing **buy bias** sets which
shock it strikes: after a down shock, where every trader's value lies below the
prevailing price and selling is plainly indicated, the modal arm still issues
more buys than sells, so the bias and the shock cancel and the market keeps
clearing. After an up shock they compound and it halts.

The obvious suspect was our own question wording, which §5 showed induces a
+0.250 conviction asymmetry. It is not the cause. Order flow under the mirror
wording, which removes that asymmetry entirely (+0.005):

| wording | after UP | after DOWN | silent from "no seller" |
|---|---|---|---|
| domain (original) | 65.9% buy / 28.2% sell | 48.8% / 42.3% | 100.0% / 96.2% |
| **mirror** | **68.2% buy / 27.7% sell** | **48.1% / 45.7%** | 99.7% / 92.9% |

Unchanged, if anything slightly stronger. Asking the question symmetrically
removes the model's stated conviction asymmetry but not its revealed
directional bias.

**Consequences.** The wording result (§5) and the liquidity result (§12-13) are
**independent findings**, not one causal chain, and the paper's two-experiment
structure is correct. Two explanations for the bias are now ruled out -- the
market's construction (both symmetric baselines are balanced at every size) and
our phrasing. What remains is the model, the task framing, or the state
representation, which this design cannot separate.

## 16. External review, and what it changed

Two independent adversarial reviews at commit `74ca20f`. Both found real
defects. Their overlapping findings were the most serious.

### Confirmed and fixed

| Finding | Raised by | Status |
|---|---|---|
| Table 1 mixed exploratory levels with confirmatory gaps; 93.8 - 66.6 = 27.2, not the stated 25.8 | both | fixed; table now one dataset |
| `verify_paper.py` checks hard-coded claims, not the manuscript, so it blessed that table | both | new `audit_manuscript.py` parses `main.tex` |
| `pdflatex -halt-on-error` exits 1; 18 table rows ended in `\` not `\` | Reviewer 1 | fixed; build gated at exit 0 |
| Size sweep pooled 20 seeds x 4 sizes as 80 independent points | both | reanalysed per-seed |
| E2 "falsified" does not survive the correct analysis | both | withdrawn; reported unresolved |
| Provenance counts stale (110,805 vs 118,628 on disk) | both | `make_manifest.py` generates from disk |
| "Ruled out" too strong for the symmetric-baseline and mirror evidence | Reviewer 1 | softened to "not reproduced" |
| Mechanism diagnostic presented as confirmatory | Reviewer 1 | labelled exploratory |
| "Never short of buyers in any arm" false for sampling (4-7%) | Reviewer 2 | corrected |
| D2 paired by `zip` over dict values | Reviewer 1 | keyed by seed, with an assertion |
| README, `pyproject` deps, prereg placeholder stale | both | fixed |

### The substantive scientific correction

Reviewer 2's second must-fix was the most valuable single item in either review. The
paper claimed the modal arm "never reaches a sell majority", citing window
averages while narrating the jump instant. Replaying the confirmatory runs by
lag:

| period | after up (buy/sell/pass) | after down (buy/sell/pass) |
|---|---|---|
| **t** | **90.0 / 7.9 / 2.1** | **34.6 / 59.4 / 6.0** |
| t+1 | 72.7 / 23.1 / 4.2 | 51.0 / 37.7 / 11.2 |
| window | 65.9 / 28.2 / 5.8 | 48.8 / 42.3 / 8.8 |

At the shock the arm **does** sell, 59.4% against 34.6%. The sell majority is
gone by t+1 once the book moves. So the claim was false, and the "standing buy
bias" second mechanism we invented to explain the direction was unnecessary:
market agreement at the shock is 90% after up and 59% after down, which is
already directional. The static probe's 96% down-side agreement was never a
market fact -- that probe freezes the book and sets signal equal to private
value.

The paper is simpler for it: one mechanism, measured in the market.

### Where a reviewer was wrong

Reviewer 1's top release blocker was that `JevSample` shares one RNG draw across
traders, making the sampling arm a common-random-number treatment and
invalidating D2. It does not: the trader index arrives inside `self.seed`,
which the runner sets to `config.seed * 100_003 + i`. Eight traders given an
identical returned distribution produce mixed actions, and 4,000 pooled draws
recover 0.506/0.302/0.192 against a 0.5/0.3/0.2 target.

The underlying concern was fair -- trader identity was implicit, and nothing
pinned it. Three regression tests now do.

### Not yet done

- Reviewer 2's suggested `option_map` swap (`option_a` always maps to buy), a cheap
  confirmatory cell that could shrink the unexplained directional remainder.
- Equivalence testing for E2 with a declared margin.
- Repeated-response sensitivity: the cache memoises one response per distinct
  state, which is not the same estimand as many agents independently calling a
  non-deterministic model. Reviewer 1 is right that this should be stated and
  ideally tested.


## 17. Two reviewer objections converted into measurements

Both had been answered twice with prose. Both were cheaply measurable, and
measuring beat arguing.

### Cache estimand (prereg 10d): F1 and F2 both hold

50 distinct states from the confirmatory runs, five live calls each, cache
bypassed.

| | |
|---|---|
| modal action identical across 5 repeats | 47/50 states |
| mean mode stability | 0.976 |
| agreement among 8 traders, memoised | 1.000 |
| agreement among 8 traders, independent | 0.979 |
| **inflation from memoisation** | **+2.1pp** (SE 1.2) |

Against a measured liquidity effect of 25.8 points. Memoisation is not what
drives the mechanism. Registered with its failure branches first: F1 failing
would have meant rewriting the mechanism section, F2 failing would have meant
reporting 25.8 as an upper bound. 250 calls, $0.008.

### Option naming (prereg 10e): G1 and G2 both hold

The mirror wording always puts the above-price description on `option_a`, which
maps to buy. Same 50 states, two arrangements differing only in which label
carried which description.

| | mirror | mirror_swapped | shift |
|---|---|---|---|
| buy | 46.0% | 50.0% | **+4.0pp** |
| sell | 52.0% | 48.0% | -4.0pp |

48/50 states chose the same economic meaning under both. The shift runs
*opposite* to a first-option preference: moving buy off `option_a` made it
slightly more likely. At 4pp it explains at most a sixth of the ~25pp residual,
and the mirror control is not contaminated. 100 calls, $0.002.

### What is still unexplained

The residual directional asymmetry -- 90.0% agreement at an up shock against
59.4% at a down shock. Four candidate causes are now ruled out by measurement:
the market's construction (symmetric baselines), our question wording (mirror),
state rounding (rounding probe), and option naming (above). What remains is the
model, the task framing, or the state representation.

## 18. The estimand tests were not run as registered; corrected

External review found that §17's F/G runs deviated from prereg 10d/10e three
ways: they sampled the whole response archive rather than the registered
post-shock population, scored an unregistered statistic for F1, and decided
every flag by point estimate with no confidence bound. Logged as prereg 10f
before any corrected run.

A further bug surfaced while correcting it: the first attempt at reconstructing
the registered population rebuilt states with an **empty order book**, because
`DecisionRecord` never stored the book. Those states were trivially stable. The
population is now recovered by replaying the confirmatory runs through a
recording client that captures the real rendered state of every call.

### Corrected results, 60 states from the registered post-shock windows

| | Estimate | Criterion | Verdict |
|---|---|---|---|
| F1: states fully stable over 5 repeats | 57/60 = 0.950 | lower bound > 0.95 | **does not hold** (bound 0.887) |
| F2: inflation from memoisation | +1.43pp | upper bound < 10pp | **holds** (bound +2.84pp) |
| G1: same meaning under swapped labels | 60/60 | equivalence within 10pp | **holds** |

**F1 fails.** At this sample size we cannot certify that the modal action is
stable above the registered threshold, so we do not claim the modal policy is
effectively deterministic. The earlier run reported F1 as holding only because
it scored mean within-state stability instead of the registered proportion.

**F2 holds and is the claim that matters**: memoisation inflates within-state
agreement by at most 2.84 percentage points with 95% confidence, against a
25.8-point liquidity effect.

**G1 is stronger on the correct population** than on the flawed one: 60/60
identical meanings against 48/50.

All 6,000 raw responses (60 states times 100 uncached calls) are archived in
`data/raw_repeats.json`, so the claim that every response is retained remains true.

### Process change

`scripts/check_all.py` runs every gate in dependency order, regenerating the
provenance manifest first. A previous "all green" was reported from a run whose
inputs changed immediately afterwards.

## 19. F2 and G1 realigned to their claims; the memoisation story ends honestly

Fifth-pass review found both corrected tests measured a quantity adjacent to
the claim drawn from them. Both were realigned (prereg 10g, logged before the
identifying run finished), and the R=100 run settles it.

**F1 (R=100):** 51/60 states perfectly stable; nine unstable, four
substantially (modal shares 0.76-0.86). The modal policy is not certifiably
deterministic, and the paper no longer says it is.

**F2, claim-aligned:** the mechanism turns on whether ANY counterparty exists
(1 - sum p^8), not on majority share. The old "+2.84pp vs 25.8pp" comparison is
withdrawn as incommensurable. Measured properly:

| | memoised | independent | counterparty gain |
|---|---|---|---|
| all (n=60) | 1.000 | 0.899 | +10.1pp (upper bound 14.4) |
| after up (n=30) | 1.000 | 0.899 | +10.1pp |
| after down (n=30) | 1.000 | 0.899 | +10.1pp |

Memoisation is NOT immaterial: independent calling would supply a counterparty
in ~10% of post-shock states it renders unanimous. The 25.8pp headline is a
property of the memoised regime. But the gain is balanced to 0.01pp across
shock directions, from different unstable-state compositions on each side --
so memoisation cannot explain WHICH shock halts. The asymmetry survives it.

**G1, realigned to registered probability mass:** +0.33pp shift, 90% CI
[-0.33, +1.00], TOST p<0.0001, restricted to the corrected population after
finding the naming cache contaminated by the crashed run's empty-book states.
Holds, and more strongly than the modal version suggested.

Cost of the whole estimand saga: ~7,700 live calls, ~$0.25. The rendered PDF
was text-extracted and scanned for mangle signatures before commit.

Registration scorecard, final: confirmed D1, D2, E1, G1; failed C1, C2, F1,
original-immunity; unresolved E2; not identified F2. Ten registered, all
reported.

## 20. The dynamic replication under independent calling: the halt is not a memoisation artefact

Section 19 ended with the paper saying the 25.8pp headline "is a property of
the memoised regime" and that the dynamic experiment "remains unrun". It has
now been run, as prereg 10h, registered and committed before the code and
before any call.

**Design.** The 10b confirmatory design unchanged in every respect but one:
every trader decision is a fresh live call. The content-addressed cache is
neither read (that would memoise) nor written (that would overwrite the entries
the memoised runs replay from). Every response is appended in call order to
`data/independent/<arm>_seed<k>.json.gz`, and a replay transport serves them
back, refusing any request whose key differs from the archived one. Two
replays produce a byte-identical `data/independent_market.json`, and the live
analysis matches the replayed one on every statistic. 2 arms x 20 seeds x 8
traders x 155 periods = 49,600 live calls, about $1.61, run ten seeds at a
time (0.3-0.4 s per call, no penalty for concurrency).

**Results.**

| | independent calling | memoised (10b) |
|---|---|---|
| jev_argmax traded share after up / down | 63.2% / 92.3% | 65.6% / 91.3% |
| jev_argmax gap (H1 / D1) | +29.1pp, SE 4.8, t=6.08, 95% CI [19.1, 39.1], 19/20 seeds | +25.8pp, t=6.37, 18/20 |
| jev_sample gap | +1.7pp | +3.1pp |
| argmax minus sample (H2 / D2) | +27.4pp, t=5.83, CI [17.6, 37.3] | +22.7pp, t=6.01 |
| Holm across H1/H2 | both p < 0.0001 | |
| H3: memoised minus independent, paired by seed | -3.3pp, SE 5.0, 95% CI [-13.9, +7.2], 7/20 seeds positive | |
| one-sided book in silent periods, up / down | 100.0% / 98.1% | 100% / -- |

H1 and H2 hold. H3's interval spans zero and its point estimate has the wrong
sign for the memoisation story: the independent gap is, if anything, larger.
The registered interpretation rule says the independent-regime number becomes
the headline and the memoised number is reported alongside it; the abstract,
intro, README and Experiment 2 now do that.

**Why the static bound was loose (exploratory, free, from `raw_repeats.json`).**
Section 19's +10.1pp counterparty gain counted ANY disagreement among eight
callers, `1 - sum p_a^8`. But of the nine unstable states at R=100, seven
involve `pass` (either a pass minority or a pass mode with a sell minority),
and a trader that passes breaks unanimity without supplying a counterparty.
Only three states show any opposite-side minority, and the largest is 2 of
100 calls. The bound was an honest upper bound on a quantity that mostly
consisted of passes.

**One deviation, disclosed.** One sampling run (seed 26) died on a socket-level
connection reset (WinError 10054) that the transport did not retry: it handled
HTTP 5xx but not failures before any status arrived. The run was redone from
scratch after adding the retry (tests first). The 550 responses of the failed
attempt were discarded, not archived, because an archive is written only when
its run completes. So the archives hold every response of every completed run,
not every round-trip; the paper says so. Logged in the prereg deviation table.

**Registration scorecard, updated:** confirmed D1, D2, E1, G1, H1, H2; failed
C1, C2, F1, original-immunity; unresolved E2; not identified F2. Twelve
registered, all reported.

## 21. Sixth review: the 10.1pp statistic was non-unanimity, not counterparty supply

Three external reviewers read 22e21a6. No further experiment was asked for.
Three corrections, all zero-cost:

1. **Naming.** Section 19's "+10.1pp counterparty gain" is `1 - sum_a p_a^8`,
   the probability that eight independent calls are not all identical. A
   buy/pass mixture satisfies it while supplying no seller. Relabelled
   "non-unanimity gain" throughout the paper and README (one reviewer applied this
   directly in the working tree; verified here). The claim-aligned quantity,
   P(at least one buy AND at least one sell among eight),
   `1 - (p_b+p_p)^8 - (p_s+p_p)^8 + p_p^8` with plug-in frequencies, is
   **0.63%** over the sixty states (0.50% after up, 0.75% after down),
   descriptive and not uncertainty-adjusted; one to two orders of magnitude
   below the non-unanimity figure, and consistent with the dynamic replication
   finding no memoisation effect. Now computed in `independent_market.py`,
   pinned in `verify_paper.py`, required by `audit_prose.py`.
2. **Counts.** The paper still said 300 deliberately uncached calls (the R=5
   count); `raw_repeats.json` holds 6,000. README still said 118,628 unique
   responses against the manifest's 118,968. Both fixed; the manifest now
   records `raw_repeats_calls` from disk and the audits check it, with a
   mutation test. Two stale counts survived three passing gates because no
   gate read those sentences. That hole is closed for these two numbers.
3. **H3 wording.** "Contributed nothing measurable" overstated an interval
   of [-13.9, +7.2]. Now "detected no difference", with the interval; the
   old phrase is forbidden by the prose audit.

Also labelled: Table 3 (silence classification) and the abstract's 90.0% /
59.4% agreement figures are from the memoised confirmatory run, next to a
headline from the independent-calling run; both now say so. The $1.61
replication cost is the cost of the archived runs; the discarded 550-call
attempt adds about $0.02. One reviewer additionally added `py.typed`, tightened
type hints, and cleared 22 ruff warnings; ruff and mypy pass.

Review status: "conditional go after this pass", "send it after changing
300 to 6,000", and "go". All conditions met.

