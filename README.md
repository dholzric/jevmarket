# jevmarket

A continuous double auction in one abstract good, used to compare LLM traders
against zero-intelligence and noisy best-response baselines under full vs.
delayed/noisy information.

The engine owns matching, budgets, order sizes and the book. A brain answers
four things: direction, how aggressive, whether the signal looks already
priced, and how confident it is. That contract is frozen in
[`schema/schema_jev_v1.json`](schema/schema_jev_v1.json).

Read [`preregistration.md`](preregistration.md) first — the hypotheses and the
three primary outcomes were written before any result existed.

## Quick start

```bash
python -m pip install -e ".[dev]"
python -m pytest                 # 90 tests, ~3s
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

Phase 0–1 (engine). No LLM code yet, by design — see the phase table in the
preregistration.

| Phase | Output | State |
|---|---|---|
| 0 | Prereg, frozen schema, CDA chosen | done, pending verbatim H1–H5 |
| 1 | Engine, ZI + NBR, conservation tests | ZI done; NBR next |
| 2 | Jev client, mock, cache | not started |
| 3 | Live Jev, N=50, reliability diagram, real $/call | not started |
| 4 | Core sweep N=200, >=5 seeds then 30 | not started |
| 5 | Figures, robustness, LLM subsample | not started |
| 6 | Draft, public repo from cache | not started |
