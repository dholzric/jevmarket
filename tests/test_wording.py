"""The wording treatment: two frozen question sets, identical but for `action`.

`original` is the natural domain wording that induced a +0.250 conviction
asymmetry. `mirror` is the control that measured +0.005. Everything else --
the aggressiveness and already_priced questions, the state, the engine -- is
held fixed, so the wording is the only thing that varies between arms.
"""

import hashlib
import json

import pytest

from jevmarket.decision import WORDINGS, Action, Decision, load_schema
from jevmarket.jev.questions import build_request
from tests.test_jev_client import observation


def test_both_wordings_are_available():
    assert set(WORDINGS) == {"original", "mirror"}


def test_an_unknown_wording_is_rejected():
    with pytest.raises(ValueError):
        load_schema("sideways")


def test_the_two_wordings_differ_only_in_the_action_question():
    original = load_schema("original")["questions"]
    mirror = load_schema("mirror")["questions"]
    assert original["aggressiveness"] == mirror["aggressiveness"]
    assert original["already_priced"] == mirror["already_priced"]
    assert original["action"] != mirror["action"]


def test_the_mirror_wording_names_no_direction():
    action = load_schema("mirror")["questions"]["action"]
    blob = json.dumps(action).lower()
    for loaded in ("buy", "sell", "underpriced", "overpriced", "acquire", "dispose"):
        assert loaded not in blob, f"mirror wording still contains {loaded!r}"


def test_the_mirror_criteria_are_structural_mirrors():
    criteria = load_schema("mirror")["questions"]["action"]["criteria"]
    above, below = criteria["option_a"], criteria["option_b"]
    assert above.replace(" above ", " below ") == below


def test_both_wordings_are_hash_locked():
    for wording in WORDINGS:
        schema = load_schema(wording)
        locked = {
            name: {"instructions": q["instructions"], "criteria": q.get("criteria")}
            for name, q in schema["questions"].items()
        }
        blob = json.dumps(locked, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        assert hashlib.sha256(blob.encode("utf-8")).hexdigest() == schema["instructions_sha256"]


def test_neutral_option_names_map_back_to_the_internal_vocabulary():
    answers = {
        "action": {
            "type": "choice",
            "choice": "option_b",
            "probabilities": {"option_a": 0.1, "option_b": 0.8, "option_c": 0.1},
            "confidence": 0.8,
        },
        "aggressiveness": {"type": "score", "score": 2.0, "probabilities": {}, "legend": {}},
        "already_priced": {"type": "noul", "noul": 0.2},
    }
    decision = Decision.from_answers(answers, schema=load_schema("mirror"))
    assert decision.action is Action.SELL
    assert decision.action_probabilities["sell"] == pytest.approx(0.8)
    assert set(decision.action_probabilities) == {"buy", "sell", "pass"}


def test_the_original_wording_needs_no_translation():
    decision = Decision.from_answers(
        {
            "action": {
                "type": "choice", "choice": "sell",
                "probabilities": {"buy": 0.1, "sell": 0.8, "pass": 0.1},
                "confidence": 0.8,
            },
            "aggressiveness": {"type": "score", "score": 2.0, "probabilities": {}, "legend": {}},
            "already_priced": {"type": "noul", "noul": 0.2},
        },
        schema=load_schema("original"),
    )
    assert decision.action is Action.SELL


def test_a_choice_outside_the_option_map_is_rejected():
    answers = {
        "action": {
            "type": "choice", "choice": "option_z",
            "probabilities": {"option_a": 0.1, "option_b": 0.8, "option_c": 0.1},
            "confidence": 0.8,
        },
        "aggressiveness": {"type": "score", "score": 2.0, "probabilities": {}, "legend": {}},
        "already_priced": {"type": "noul", "noul": 0.2},
    }
    with pytest.raises(ValueError):
        Decision.from_answers(answers, schema=load_schema("mirror"))


def test_the_request_carries_the_requested_wording():
    for wording in WORDINGS:
        request = build_request(observation(), wording=wording)
        assert request.questions == load_schema(wording)["questions"]
        assert wording in request.schema_version


def test_the_two_wordings_never_collide_in_the_cache():
    """Same observation, different wording, must be two different calls."""
    a = build_request(observation(), wording="original")
    b = build_request(observation(), wording="mirror")
    assert a.cache_key != b.cache_key
