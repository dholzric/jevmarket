"""Transport + cache + spend gate -> a Decision.

The client is the only place that knows an API exists. Brains ask it for a
decision; the runner never sees a request or a token count.
"""

from __future__ import annotations

from ..decision import DEFAULT_WORDING, Decision, load_schema
from .cache import DecisionCache
from .questions import build_request
from .transport import JevRequest, JevResponse, Transport


class JevClient:
    def __init__(
        self,
        transport: Transport,
        cache: DecisionCache | None = None,
        budget=None,
        model: str | None = None,
    ) -> None:
        self.transport = transport
        self.cache = cache
        self.budget = budget
        self.model = model
        self.schema_violations = 0

    def decide(
        self, observation, wording: str = DEFAULT_WORDING
    ) -> tuple[Decision, JevResponse]:
        request = build_request(observation, model=self.model, wording=wording)
        response = self._fetch(request)
        try:
            return Decision.from_answers(
                response.answers, schema=load_schema(wording)
            ), response
        except ValueError:
            # Counted as a reported cost of the Jev arms, then re-raised so the
            # runner decides whether to fall back or stop.
            self.schema_violations += 1
            raise

    def _fetch(self, request: JevRequest) -> JevResponse:
        if self.cache is not None:
            hit = self.cache.get(request)
            if hit is not None:
                if self.budget is not None:
                    self.budget.note_cache_hit()
                return hit

        response = self.transport.send(request)
        if self.budget is not None:
            self.budget.charge(response.input_tokens, response.output_tokens)
        if self.cache is not None:
            self.cache.put(request, response)
        return response
