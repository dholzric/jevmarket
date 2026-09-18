"""The frozen Jev decision contract (schema v1).

Jev answers direction, aggressiveness, whether the signal looks already priced,
and how confident it is. Nothing else. `schema/schema_jev_v1.json` is the wire
format handed to the model's structured-output call; `Decision` is the same
contract in Python. A test asserts the two never drift.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from enum import Enum

SCHEMA_VERSION = "v1"
SCHEMA_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "schema" / "schema_jev_v1.json"
)

RATIONALE_MAX_CHARS = 200
_REQUIRED = ("action", "aggressiveness", "already_priced", "confidence")
_ALLOWED = _REQUIRED + ("rationale",)


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    PASS = "pass"


@dataclass(frozen=True)
class Decision:
    action: Action
    aggressiveness: float
    already_priced: bool
    confidence: float
    rationale: str = ""

    @classmethod
    def from_payload(cls, payload: dict) -> "Decision":
        """Validate a raw structured-output payload against the frozen contract.

        Every rejection path raises ValueError so the runner can count schema
        violations as a reported cost of the LLM arm rather than a crash.
        """
        if not isinstance(payload, dict):
            raise ValueError(f"payload must be an object, got {type(payload).__name__}")

        extra = set(payload) - set(_ALLOWED)
        if extra:
            raise ValueError(f"unknown field(s): {sorted(extra)}")
        missing = set(_REQUIRED) - set(payload)
        if missing:
            raise ValueError(f"missing required field(s): {sorted(missing)}")

        try:
            action = Action(payload["action"])
        except ValueError:
            raise ValueError(f"unknown action {payload['action']!r}") from None

        if not isinstance(payload["already_priced"], bool):
            raise ValueError("already_priced must be a boolean")

        values = {}
        for field in ("aggressiveness", "confidence"):
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field} must be a number, got {value!r}")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field} must be in [0, 1], got {value}")
            values[field] = float(value)

        rationale = payload.get("rationale", "") or ""
        if not isinstance(rationale, str):
            raise ValueError("rationale must be a string")

        return cls(
            action=action,
            aggressiveness=values["aggressiveness"],
            already_priced=payload["already_priced"],
            confidence=values["confidence"],
            rationale=rationale[:RATIONALE_MAX_CHARS],
        )

    def to_payload(self) -> dict:
        return {
            "action": self.action.value,
            "aggressiveness": self.aggressiveness,
            "already_priced": self.already_priced,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }
