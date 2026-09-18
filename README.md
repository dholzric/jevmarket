# jevmarket

A continuous double auction in one abstract good, used to compare LLM traders
against zero-intelligence and noisy best-response baselines under full vs.
delayed/noisy information.

The engine owns matching, budgets, order sizes and the book. A brain answers
three typed questions: direction (`choice`), urgency (`score`), and whether the
signal is already priced (`noul`). That contract -- including the exact question
wording, hash-locked -- is frozen in
[`schema/schema_jev_v1.json`](schema/schema_jev_v1.json).

"Jev" is [TypeSafe AI's System One model](https://docs.typesafe.ai/), which
returns typed decisions with their probability distributions rather than text.
Confidence is therefore never self-reported: it is the mass the arm put on the
action it took, which ZI, NBR and both Jev arms all have.

Read [`preregistration.md`](preregistration.md) first — the hypotheses and the
three primary outcomes were written before any result existed.

## Quick start

```bash
python -m pip install -e ".[dev]"
python -m pytest                 # 170 tests, ~4s, no network
python scripts/zi_price_path.py  # writes figures/zi_price_path.png
```

`scripts/zi_price_path.py` prints the run summary and the primary outcomes,
and saves the price path against the fundamental:

```
periods              600
traders              40
jumps                8
trades               6055
periods with a trade 600 / 600
rejected orders      4
cash conserved       4000000
units conserved      2000
RMSE vs F_t          1.290
post-jump RMSE (20)  1.784
```

## Layout

```
src/jevmarket/
  book.py          limit order book: price-time priority, self-trade prevention
  exchange.py      accounts, budget/inventory constraints, settlement, invariants
  fundamental.py   jumping F_t and the two information treatments
  decision.py      the frozen Jev contract, mirrored by schema_jev_v1.json
  quoting.py       aggressiveness in [0,1] -> an integer tick, clamped at value
  agents/          one class per brain; all share Observation -> Decision
  jev/             transport, live HTTP client, cache, spend gate, mock
  simulation.py    the run loop
  metrics.py       the three pre-declared primary outcomes
tests/             conservation, matching, schema freeze, metrics, end-to-end
schema/            schema_jev_v1.json  (FROZEN — changing it needs a v2 + rerun)
scripts/           figure and run entry points
```

## The invariants

`Exchange.check_invariants()` is called after every submission in the property
tests. It asserts that total cash and total units are exactly what they were at
endowment, that no account is negative, that no trader has committed more than
it holds, and that the book is never crossed. `tests/test_conservation.py` runs
20,000 random submissions against it.

## Status

Phase 0–2. See the open items at the end of the preregistration — H1–H5 are
still placeholders and no live Jev call has been made.

## Cost control

Jev calls go through `JevClient`, which sits in front of a content-addressed
cache and a `SpendGate`. Two things are load-bearing:

- `render_state` excludes the period number, cash and inventory, and rounds
  prices to whole ticks. Measured on a 400-decision run, that takes the cache
  hit rate from 1% to 31%. `tests/test_simulation.py` guards the regression.
- `SpendGate` refuses a dollar cap it cannot compute (TypeSafe does not publish
  pricing), and a cached answer never consumes the gate.

`DecisionCache(path, read_only=True)` raises `CacheMiss` rather than calling the
API, which is what lets Phase 6 publish a repo that provably reproduces every
figure from cache.

| Phase | Output | State |
|---|---|---|
| 0 | Prereg, frozen schema, CDA chosen | done, pending verbatim H1–H5 |
| 1 | Engine, ZI + NBR, conservation tests | ZI done; NBR next |
| 2 | Jev client, mock, cache | done (live transport untested against the real API) |
| 3 | Live Jev, N=50, reliability diagram, real $/call | not started |
| 4 | Core sweep N=200, >=5 seeds then 30 | not started |
| 5 | Figures, robustness, LLM subsample | not started |
| 6 | Draft, public repo from cache | not started |
