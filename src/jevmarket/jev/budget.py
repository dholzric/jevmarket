"""Hard spend gates. They live in the runner, not in anyone's memory.

The rule from the plan: measure real cost in Phase 3 before buying 30 seeds.
A gate that silently fails to enforce a cap is worse than no gate, so a dollar
cap without pricing is refused at construction rather than ignored at runtime.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

TOKENS_PER_MTOK = 1_000_000

# TypeSafe does not publish pricing. The rate below is EMPIRICAL, fitted to the
# account meter after Phase 3: 2,643 calls / 2,251,476 tokens billed at $0.08,
# i.e. $0.0355 per million tokens blended. The input/output split is NOT known;
# a 5:1 ratio is assumed and then rounded up, so the gate over-estimates by
# roughly 6% -- the right direction for a spend cap. Replace with published
# rates if TypeSafe ever publishes them.
OBSERVED_BLENDED_USD_PER_MTOK = 0.0355
PRICING_NOTE = "empirical, fitted to the 2026-09-18 account meter; not official"



class BudgetExceeded(Exception):
    """The run hit its call or dollar cap. The charge is still recorded."""


@dataclass(frozen=True)
class Pricing:
    """Dollars per million tokens. Fill these in from the Phase 3 measurement."""

    input_per_mtok: float
    output_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / TOKENS_PER_MTOK


JEV_PRICING_ESTIMATE = None  # set below, once Pricing is defined


class SpendGate:
    def __init__(
        self,
        max_calls: int | None = None,
        max_usd: float | None = None,
        pricing: Pricing | None = None,
    ) -> None:
        if max_usd is not None and pricing is None:
            raise ValueError(
                "max_usd requires pricing; a dollar cap that cannot be computed "
                "would silently fail to enforce anything"
            )
        self.max_calls = max_calls
        self.max_usd = max_usd
        self.pricing = pricing
        self.calls = 0
        self.cache_hits = 0
        self.input_tokens = 0
        self.output_tokens = 0
        # Prereg 10h charges one gate from several seed threads at once.
        self._lock = threading.Lock()

    def note_cache_hit(self) -> None:
        """A cached answer costs nothing and does not consume the gate."""
        self.cache_hits += 1

    def charge(self, input_tokens: int, output_tokens: int) -> None:
        """Record a live call, then raise if that call breached a cap."""
        with self._lock:
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens

        if self.max_calls is not None and self.calls > self.max_calls:
            raise BudgetExceeded(
                f"call cap reached: {self.calls} > {self.max_calls}"
            )
        if (
            self.max_usd is not None
            and self.spent_usd is not None
            and self.spent_usd > self.max_usd
        ):
            raise BudgetExceeded(
                f"spend cap reached: ${self.spent_usd:.4f} > ${self.max_usd:.4f}"
            )

    @property
    def spent_usd(self) -> float | None:
        if self.pricing is None:
            return None
        return self.pricing.cost(self.input_tokens, self.output_tokens)

    @property
    def remaining_calls(self) -> int | None:
        return None if self.max_calls is None else self.max_calls - self.calls

    @property
    def remaining_usd(self) -> float | None:
        if self.max_usd is None or self.spent_usd is None:
            return None
        return self.max_usd - self.spent_usd

    def summary(self) -> dict:
        return {
            "live_calls": self.calls,
            "cache_hits": self.cache_hits,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "spent_usd": self.spent_usd,
            "remaining_calls": self.remaining_calls,
            "remaining_usd": self.remaining_usd,
        }


# Convenience: the working cost estimate for Jev, used by the run scripts.
JEV_PRICING_ESTIMATE = Pricing(input_per_mtok=0.028, output_per_mtok=0.14)
