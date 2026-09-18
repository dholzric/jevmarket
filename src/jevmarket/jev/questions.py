"""What Jev is shown, and the request built around it.

Three deliberate choices in `render_state`, all aimed at cache reuse. Measured
on a 400-decision run: they take the within-run hit rate from 1% to 31%.

- the period number is left out. It is not decision-relevant, and including it
  would make every state unique and the cache worthless.
- prices and values are rounded to whole ticks. A trader cannot act on
  sub-tick precision anyway, and rounding turns thousands of near-identical
  situations into one cache entry.
- cash and inventory are left out entirely. They change after every fill, so
  including them made every decision a unique key. Leaving them out costs
  nothing: the exchange already enforces budget and inventory constraints, and
  the frozen question wording only ever refers to the book, the trader's
  private value, and its signal. Code owns the budget; Jev never sees it.

Note what this does NOT buy. Sharing one cache across the argmax and sample
arms saves only about 3%: the two arms take different actions, so they walk
into different books and visit different states almost immediately. One call
serves both arms for a *given observation*, but not across a whole run.

The state is part of the prompt in everything but name, so its field list is
locked in the schema alongside the question wording.
"""

from __future__ import annotations

from ..decision import SCHEMA_VERSION, load_schema
from .transport import JevRequest


def render_state(observation) -> dict:
    """The `state` object POSTed to System One. Structured, never prose."""
    best_bid = observation.best_bid
    best_ask = observation.best_ask
    spread = None if best_bid is None or best_ask is None else best_ask - best_bid
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "last_trade_price": observation.last_price,
        "your_private_value": round(observation.private_value),
        "your_signal": round(observation.signal),
    }


def build_request(observation, model: str | None = None) -> JevRequest:
    schema = load_schema()
    return JevRequest(
        model=model or schema["model"],
        state=render_state(observation),
        questions=schema["questions"],
        schema_version=SCHEMA_VERSION,
    )
