# jevmarket

A continuous double auction populated by traders whose decisions come from a
typed language model that returns a probability distribution over actions. We
hold the model, the prompt, the market and the seeds fixed, and vary only how
that distribution is consumed.

**Result:** taking the model's modal action — the default in nearly every
deployment — makes the market stop trading after positive shocks. The gap is
25.8 percentage points (95% CI [17.3, 34.2], preregistered, n=20). Sampling
from the same distribution reduces it to 3.1 points. Two algorithmic baselines
that are symmetric by construction show −0.4 and +1.0 points.

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

python scripts/verify_paper.py       # recompute every claimed number from data/
python scripts/audit_manuscript.py   # parse paper/main.tex and check it against data/
python -m pytest                     # test suite
```

`audit_manuscript.py` reads the manuscript directly rather than a transcription
of it: it re-derives every table cell from the named dataset, checks that levels
quoted beside a gap actually produce that gap, compares provenance counts
against a manifest generated from disk, and requires `pdflatex -halt-on-error`
to exit 0. It exists because an earlier verifier that checked hard-coded claims
reported "55/55 passing" while a table in the paper was internally inconsistent.

## What is established

| | Result | Status |
|---|---|---|
| Modal decoding halts the market asymmetrically | +25.8pp, t=6.37 | registered, confirmed |
| The gap exceeds sampling's | +22.7pp, t=6.01 | registered, confirmed |
| It collapses as the market grows | −0.112/doubling, t=−7.78 | registered, confirmed |
| Domain wording skews stated conviction | +0.250 vs +0.005 mirror | exploratory, replicated |
| Wording does **not** move pricing error | −0.184, CI [−0.479, +0.111] | registered, **null** |
| Sampling shows no size decay | t=−2.00, p=0.060 | registered, **unresolved** |

Four preregistered predictions did not survive and are reported as such. The
open question is why the arm is more decisive buying than selling at equal
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

$3.85 across 118,628 model calls, regenerated into `data/manifest.json` from
disk rather than transcribed. Replaying from the archive is free.
