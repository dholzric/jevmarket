"""One live System One call, to verify the wire format against real servers.

Everything in `jev/http.py` was written from TypeSafe's published docs and
tested against a fake. This script is the first contact with the real API. It
prints the raw response so the assumptions can be checked by eye -- in
particular whether `score` is 0- or 1-indexed, which the docs do not say.

    python scripts/jev_smoke.py

Makes exactly one call. The API key is read from JEV_API_KEY and never printed.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from jevmarket.agents.base import Observation  # noqa: E402
from jevmarket.decision import Decision, load_schema  # noqa: E402
from jevmarket.jev.budget import SpendGate  # noqa: E402
from jevmarket.jev.http import HttpTransport  # noqa: E402
from jevmarket.jev.questions import build_request, render_state  # noqa: E402

# A trader whose private value sits well above the book: the obvious answer is
# buy, so a sane response is easy to recognise.
OBSERVATION = Observation(
    period=0,
    signal=112.0,
    private_value=112.0,
    best_bid=99,
    best_ask=101,
    last_price=100,
    cash=100_000,
    inventory=50,
    available_cash=100_000,
    available_inventory=50,
)


def main() -> int:
    request = build_request(OBSERVATION)
    gate = SpendGate(max_calls=1)

    print("=== state sent ===")
    print(json.dumps(render_state(OBSERVATION), indent=2))
    print(f"\ncache_key {request.cache_key}")
    print(f"model     {request.model}")
    print(f"questions {list(request.questions)}")

    transport = HttpTransport()
    print(f"\nPOST {transport.url}")

    response = transport.send(request)
    gate.charge(response.input_tokens, response.output_tokens)

    print("\n=== raw answers ===")
    print(json.dumps(response.answers, indent=2, sort_keys=True))
    print("\n=== usage ===")
    print(f"model          {response.model}")
    print(f"input_tokens   {response.input_tokens}")
    print(f"output_tokens  {response.output_tokens}")
    print(f"latency_s      {response.latency_s:.3f}")

    print("\n=== assumption checks ===")
    schema = load_schema()
    score_answer = response.answers.get("aggressiveness", {})
    legend = score_answer.get("legend")
    probabilities = score_answer.get("probabilities")
    print(f"declared score_levels  {schema['score_levels']} (base {schema['score_base']})")
    print(f"legend keys            {sorted(legend) if legend else 'ABSENT'}")
    print(f"score probability keys {sorted(probabilities) if probabilities else 'ABSENT'}")
    print(f"raw score              {score_answer.get('score')}")
    print(f"noul                   {response.answers.get('already_priced', {}).get('noul')}")

    print("\n=== parsed Decision ===")
    try:
        decision = Decision.from_answers(response.answers)
        print(json.dumps(decision.to_json(), indent=2))
        print(
            f"\nprivate value {render_state(OBSERVATION)['your_private_value']} "
            f"vs mid 100 -> expected 'buy', got {decision.action.value!r}"
        )
    except ValueError as error:
        print(f"PARSE FAILED: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
