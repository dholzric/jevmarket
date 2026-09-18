"""The frozen Jev decision contract.

Jev answers four things and nothing else: direction, how aggressive, whether
the signal is already priced, and how sure it is. Prices, sizes, budgets and
matching stay in code. These tests are the freeze: if the schema and the
dataclass drift apart, or a field is added, they fail.
"""

import json
import pathlib

import pytest

from jevmarket.decision import Action, Decision, SCHEMA_PATH, SCHEMA_VERSION

FROZEN_FIELDS = {
    "action",
    "aggressiveness",
    "already_priced",
    "confidence",
    "rationale",
}


def load_schema():
    return json.loads(pathlib.Path(SCHEMA_PATH).read_text(encoding="utf-8"))


def test_schema_file_exists_and_declares_its_version():
    schema = load_schema()
    assert schema["title"] == f"jev_decision_{SCHEMA_VERSION}"
    assert schema["additionalProperties"] is False


def test_schema_fields_match_the_dataclass_exactly():
    schema = load_schema()
    assert set(schema["properties"]) == FROZEN_FIELDS
    assert set(Decision.__dataclass_fields__) == FROZEN_FIELDS


def test_every_field_except_rationale_is_required():
    schema = load_schema()
    assert set(schema["required"]) == FROZEN_FIELDS - {"rationale"}


def test_action_enum_is_buy_sell_pass():
    schema = load_schema()
    assert schema["properties"]["action"]["enum"] == ["buy", "sell", "pass"]
    assert [a.value for a in Action] == ["buy", "sell", "pass"]


def test_confidence_and_aggressiveness_are_bounded_unit_intervals():
    schema = load_schema()
    for field in ("aggressiveness", "confidence"):
        spec = schema["properties"][field]
        assert spec["type"] == "number"
        assert spec["minimum"] == 0.0
        assert spec["maximum"] == 1.0


def test_decision_accepts_a_valid_payload():
    decision = Decision.from_payload(
        {
            "action": "buy",
            "aggressiveness": 0.4,
            "already_priced": False,
            "confidence": 0.7,
            "rationale": "signal above book",
        }
    )
    assert decision.action is Action.BUY
    assert decision.confidence == 0.7


def test_decision_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        Decision.from_payload(
            {
                "action": "buy",
                "aggressiveness": 0.4,
                "already_priced": False,
                "confidence": 1.4,
            }
        )


def test_decision_rejects_unknown_action():
    with pytest.raises(ValueError):
        Decision.from_payload(
            {
                "action": "hodl",
                "aggressiveness": 0.4,
                "already_priced": False,
                "confidence": 0.5,
            }
        )


def test_decision_rejects_extra_fields():
    with pytest.raises(ValueError):
        Decision.from_payload(
            {
                "action": "buy",
                "aggressiveness": 0.4,
                "already_priced": False,
                "confidence": 0.5,
                "target_price": 103,
            }
        )


def test_decision_rejects_missing_required_field():
    with pytest.raises(ValueError):
        Decision.from_payload({"action": "buy", "aggressiveness": 0.4})


def test_rationale_defaults_to_empty_and_is_truncated():
    decision = Decision.from_payload(
        {
            "action": "pass",
            "aggressiveness": 0.0,
            "already_priced": True,
            "confidence": 0.6,
        }
    )
    assert decision.rationale == ""

    long = Decision.from_payload(
        {
            "action": "pass",
            "aggressiveness": 0.0,
            "already_priced": True,
            "confidence": 0.6,
            "rationale": "x" * 500,
        }
    )
    assert len(long.rationale) <= 200
