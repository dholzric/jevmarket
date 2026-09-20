# jevmarket

A continuous double auction populated by traders whose decisions come from a
typed language model that returns a probability distribution over actions. We
hold the model, the prompt, the market and the seeds fixed, and vary only how
that distribution is consumed.

**Result:** taking the model's modal action — a common deployment choice —
makes the market stop trading after positive shocks. The gap is
29.1 percentage points (95% CI [19.1, 39.1], preregistered, n=20, with an
independent live call for every trader decision); the original memoised
confirmatory run gave 25.8 (95% CI [17.3, 34.2]). Sampling from the same
distribution reduces it to 1.7 points (3.1 memoised). Two algorithmic
baselines that are symmetric by construction show −0.4 and +1.0 points.

The mechanism: every trader conditions on the same public signal, so a
deterministic decoder makes them act identically, and a market of unanimous
buyers has no counterparty. 100% of silent periods under modal decoding had one
side of the book empty, against 3.4% for the random baseline.

"Jev" is [TypeSafe AI's System One model](https://docs.typesafe.ai/), chosen
because it exposes its probabilities natively. Paper: [`paper/main.tex`](paper/main.tex).
Findings log: [`FINDINGS.md`](FINDINGS.md). Registrations:
[`preregistration.md`](preregistration.md).

## Reproducing

The model is non-deterministic and exposes no seed, so **code alone does not
reproduce these numbers** — only the saved responses do.

```bash
tar -xzf data/archive/cache.tar.gz -C data/
python -m pip install -e ".[dev]"

python scripts/check_all.py          # every gate, in dependency order
```

The three gates cover different things, because over three review rounds each
was caught certifying something the paper contradicted:

- `verify_paper.py` is a **data-regression test** over statistics hard-coded in
  itself. It cannot detect a paper that says otherwise, and says so in its own
  output.
- `audit_manuscript.py` parses `main.tex`: it re-derives every table cell from
  its named dataset, checks that levels quoted beside a gap actually produce
  that gap, compares provenance against a disk-generated manifest, and requires
  `pdflatex -halt-on-error` to exit 0.
- `check_all.py` runs them in dependency order and is the only command whose
  green result should be quoted. An earlier verification reported all-clear
  because the audits ran *before* the manifest they check against was
  regenerated.
- `audit_prose.py` reads the abstract, contributions, registration tally,
  discussion and limitations — which the table audit never touches. It asserts
  withdrawn claims are absent and current ones present, and runs **eight
  mutation tests** that reintroduce each past defect and require the audit to
  fail. An audit that cannot be made to fail is not evidence.

## What is established

| | Result | Status |
|---|---|---|
| Modal decoding halts the market asymmetrically | +25.8pp, t=6.37 (memoised) | registered, confirmed (D1) |
| It replicates with an independent live call per decision | +29.1pp, t=6.08; memoised − independent = −3.3pp, CI [−13.9, +7.2] | registered, confirmed (H1) |
| The gap exceeds sampling's | +22.7pp, t=6.01 (memoised); +27.4pp, t=5.83 (independent) | registered, confirmed (D2, H2) |
| It collapses as the market grows | −0.112/doubling, t=−7.78 | registered, confirmed |
| Domain wording skews stated conviction | +0.250 vs +0.005 mirror | exploratory, replicated |
| Wording does **not** move pricing error | −0.184, CI [−0.479, +0.111] | registered, **null** |
| Sampling shows no size decay | t=−2.00, p=0.060 | registered, **unresolved** |
| Modal policy is effectively deterministic | 51/60 stable at R=100, bound 0.887 | registered, **failed** (F1) |
| Memoisation's counterparty effect (static) | +10.1pp, upper bound 14.4pp, direction-balanced | measured bound; the dynamic replication (H1) shows no measurable contribution |
| Option naming shifts P(buy) | +0.33pp, TOST p<0.0001 | registered, confirmed (G1) |

Of twelve registered predictions, six were confirmed (D1, D2, E1, G1, H1, H2),
four failed (C1, C2, F1, and the original clause that modal decoding would be
immune), one is unresolved (E2) and one is not identified at the sample size
reached (F2's claim-aligned form). H1 and H2 (preregistration 10h) are the
dynamic replication of D1 and D2 with the cache bypassed: a fresh live call for
every trader decision, 49,600 calls, every response archived in call order. A separate post-hoc mechanism account is
withdrawn and identified as post-hoc rather than counted among the registered
failures. The F/G tests were first run on the wrong population with the wrong
statistics; the deviation, the correction, and the realignment of both tests to
their registered estimands are in preregistration sections 10f-10g.

The open question is why the arm is more decisive buying than selling at equal
mispricing (90.0% vs 59.4% at the shock); it is not reproduced by either
baseline and is not removed by mirror wording.

## Layout

```
src/jevmarket/
  book.py          limit order book: price-time priority, self-trade prevention
  exchange.py      accounts, budget/inventory constraints, settlement, invariants
  fundamental.py   jumping F_t, matched-jump process, information treatments
  decision.py      the frozen contract, mirrored by schema_jev_v1*.json
  quoting.py       aggressiveness in [0,1] -> an integer tick, clamped at value
  agents/          one class per arm; all share Observation -> Decision
  jev/             transport, live HTTP client, cache, spend gate, mock
  simulation.py    the run loop
  metrics.py       the pre-declared outcomes
scripts/           experiments, diagnostics, audits, figures
schema/            frozen question wordings, hash-locked
data/archive/      the response archive (421 MB of JSON, 18 MB compressed)
data/independent/  ordered per-run archives of the independent-calling replication
```

## Invariants

`Exchange.check_invariants()` asserts that total cash and total units are
exactly their endowed values, that no account is negative, that no trader has
committed more than it holds, and that the book is never crossed.
`tests/test_conservation.py` submits 20,000 random orders and checks after
every one. `quoting.py` is checked over 20,000 random cases to confirm no quote
is ever on the wrong side of its own private value.

The question wordings are hash-locked: `tests/test_decision.py` fails if any
instruction or criterion changes.

## Cost

The archive holds 118,628 **unique** responses, one per distinct request — a
lower bound on live calls rather than a count of them. Estimated spend from the
archived token counts is $3.85. Both are regenerated into `data/manifest.json`
from disk rather than transcribed. Replaying from the archive is free.

The independent-calling replication (prereg 10h) adds 49,600 archived live
calls in `data/independent/` (one gzipped, ordered archive per run, 5 MB) at an
estimated $1.61; `python scripts/independent_market.py --replay` reproduces
`data/independent_market.json` byte for byte from them without a key.

Note on the estimand: in the memoised runs, requests are content-addressed, so
traders rendering the same tick-rounded state share one stored response. That
measures *one archived response per distinct state*, not N agents independently
calling a non-deterministic service. The replication removes this by
construction and reproduces the result (+29.1pp against +25.8pp memoised).
