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

**Why it matters:** the argmax is correct on both sides at every edge. Anyone
using the model the normal way — take `.choice` — sees nothing wrong. The bias
exists only in the distribution, and only bites when you sample from it.

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
7. **Any guidance on writing symmetric criteria?** Given §5, this seems like a
   footgun worth documenting on their side.
