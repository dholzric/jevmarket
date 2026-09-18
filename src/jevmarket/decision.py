"""The frozen Jev contract (schema v1), in TypeSafe System One primitives.

Jev is not a chat model. It answers three typed questions against one `state`
and returns typed answers carrying its own probability distribution:

    action          choice  -> choice, probabilities, confidence
    aggressiveness  score   -> score (fractional level), legend, probabilities
    already_priced  noul    -> noul (a probability, not a boolean)

`Decision` is the arm-agnostic internal form. Every brain -- ZI, NBR, and both
Jev arms -- produces one, and every brain therefore carries a real distribution
over {buy, sell, pass}. That is what makes calibration comparable across arms.

Two consequences of the model's shape, both deliberate:

- there is no `rationale`; Jev emits no text at all.
- `confidence` is not self-reported. It is the probability mass the model put
  on the action it chose, which is the quantity with a frequentist meaning.
"""

from __future__ import annotations

import functools
import json
import pathlib
from dataclasses import dataclass, field
from enum import Enum

SCHEMA_VERSION = "v1"
SCHEMA_DIR = pathlib.Path(__file__).resolve().parents[2] / "schema"

# The wording treatment. `original` is the natural domain wording that induced a
# +0.250 buy/sell conviction asymmetry; `mirror` is the control that measured
# +0.005. They differ ONLY in the `action` question. See FINDINGS.md.
WORDINGS = {
    "original": SCHEMA_DIR / "schema_jev_v1.json",
    "mirror": SCHEMA_DIR / "schema_jev_v1_mirror.json",
}
DEFAULT_WORDING = "original"
SCHEMA_PATH = WORDINGS[DEFAULT_WORDING]

# Jev rounds probabilities to 2dp, so a three-option distribution routinely
# arrives summing to 0.99 or 1.01. Accept that and renormalise; reject anything
# that is not plausibly a rounded distribution.
PROBABILITY_TOLERANCE = 0.05
QUESTION_TYPES = {"action": "choice", "aggressiveness": "score", "already_priced": "noul"}


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    PASS = "pass"


@functools.lru_cache(maxsize=len(WORDINGS))
def load_schema(wording: str = DEFAULT_WORDING) -> dict:
    if wording not in WORDINGS:
        raise ValueError(f"unknown wording {wording!r}; known: {sorted(WORDINGS)}")
    return json.loads(WORDINGS[wording].read_text(encoding="utf-8"))


def normalise_score(score: float, levels: int, base: int = 0) -> float:
    """Jev's fractional level -> the [0,1] that `quote_price` expects."""
    if levels < 2:
        raise ValueError(f"score needs at least 2 levels, got {levels}")
    unit = (float(score) - base) / (levels - 1)
    return min(1.0, max(0.0, unit))


def _unit(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value}")
    return value


def _validated_probabilities(probabilities) -> dict:
    if not isinstance(probabilities, dict):
        raise ValueError("action_probabilities must be a mapping")
    missing = {a.value for a in Action} - set(probabilities)
    if missing:
        raise ValueError(f"action_probabilities missing {sorted(missing)}")
    extra = set(probabilities) - {a.value for a in Action}
    if extra:
        raise ValueError(f"action_probabilities has unknown key(s) {sorted(extra)}")

    clean = {key: _unit(probabilities[key], f"probability[{key}]") for key in probabilities}
    total = sum(clean.values())
    if abs(total - 1.0) > PROBABILITY_TOLERANCE:
        raise ValueError(f"action_probabilities must sum to 1, got {total}")
    if total <= 0.0:
        raise ValueError("action_probabilities are all zero")
    # Renormalise: the sampling arm draws from this, so it must be exact.
    return {key: value / total for key, value in clean.items()}


@dataclass(frozen=True)
class Decision:
    action: Action
    aggressiveness: float
    already_priced: float
    action_probabilities: dict = field(default_factory=dict)
    model_confidence: float | None = None

    @property
    def confidence(self) -> float:
        """PRIMARY calibration input: mass the arm put on the action it took."""
        return self.action_probabilities[Action(self.action).value]

    @classmethod
    def create(
        cls,
        action,
        aggressiveness: float,
        already_priced: float,
        action_probabilities: dict,
        model_confidence: float | None = None,
    ) -> "Decision":
        """The constructor every arm goes through, Jev included."""
        try:
            action = Action(action)
        except ValueError:
            raise ValueError(f"unknown action {action!r}") from None
        return cls(
            action=action,
            aggressiveness=_unit(aggressiveness, "aggressiveness"),
            already_priced=_unit(already_priced, "already_priced"),
            action_probabilities=_validated_probabilities(action_probabilities),
            model_confidence=(
                None if model_confidence is None else _unit(model_confidence, "model_confidence")
            ),
        )

    @classmethod
    def from_answers(cls, answers: dict, schema: dict | None = None) -> "Decision":
        """Parse one System One answer set against the frozen contract.

        Every rejection path raises ValueError so the runner can count schema
        violations as a reported cost of the Jev arms rather than a crash.
        """
        if not isinstance(answers, dict):
            raise ValueError(f"answers must be an object, got {type(answers).__name__}")
        schema = schema or load_schema()

        for name, expected_type in QUESTION_TYPES.items():
            if name not in answers:
                raise ValueError(f"answers missing question {name!r}")
            found = answers[name].get("type")
            if found is not None and found != expected_type:
                raise ValueError(
                    f"question {name!r} came back as {found!r}, expected {expected_type!r}"
                )

        action_answer = answers["action"]
        aggressiveness_answer = answers["aggressiveness"]

        if "score" not in aggressiveness_answer:
            raise ValueError("aggressiveness answer has no score")

        # A wording may name its options neutrally (option_a/b/c) to avoid the
        # lexical component of the asymmetry; map them back before anything else
        # in the codebase sees them.
        option_map = schema.get("option_map") or {}

        def translate(option):
            if not option_map:
                return option
            if option not in option_map:
                raise ValueError(
                    f"option {option!r} is not in this wording's option_map "
                    f"({sorted(option_map)})"
                )
            return option_map[option]

        raw_probabilities = action_answer.get("probabilities")
        if isinstance(raw_probabilities, dict):
            raw_probabilities = {
                translate(option): p for option, p in raw_probabilities.items()
            }

        return cls.create(
            action=translate(action_answer.get("choice")),
            aggressiveness=normalise_score(
                aggressiveness_answer["score"],
                levels=schema["score_levels"],
                base=schema.get("score_base", 0),
            ),
            already_priced=_unit(answers["already_priced"].get("noul"), "noul"),
            action_probabilities=raw_probabilities,
            model_confidence=action_answer.get("confidence"),
        )

    def to_json(self) -> dict:
        return {
            "action": Action(self.action).value,
            "aggressiveness": self.aggressiveness,
            "already_priced": self.already_priced,
            "action_probabilities": self.action_probabilities,
            "model_confidence": self.model_confidence,
            "confidence": self.confidence,
        }
