"""The frozen Jev contract, in TypeSafe System One primitives.

Jev answers three typed questions and nothing else: direction (choice),
urgency (score), and whether the signal is already priced (noul). Prices,
sizes, budgets and matching stay in code.

The freeze here is the *question wording*, hash-locked. Reword an instruction
and `test_the_question_wording_is_hash_locked` fails. That is the defence
against prompt-of-the-week.
"""

import hashlib
import json
import pathlib

import pytest

from jevmarket.decision import (
    SCHEMA_PATH,
    SCHEMA_VERSION,
    Action,
    Decision,
    load_schema,
    normalise_score,
)

QUESTION_NAMES = {"action", "aggressiveness", "already_priced"}


def jev_answers(choice="buy", probabilities=None, score=2.0, noul=0.3):
    return {
        "action": {
            "type": "choice",
            "choice": choice,
            "probabilities": probabilities or {"buy": 0.7, "sell": 0.2, "pass": 0.1},
            "confidence": 0.66,
        },
        "aggressiveness": {
            "type": "score",
            "score": score,
            "legend": {"0": "none", "4": "max"},
            "probabilities": {"0": 0.1, "1": 0.2, "2": 0.4, "3": 0.2, "4": 0.1},
            "confidence": 0.4,
        },
        "already_priced": {"type": "noul", "noul": noul},
    }


# --- the freeze -------------------------------------------------------------


def test_schema_file_declares_its_version_and_endpoint():
    schema = load_schema()
    assert schema["title"] == f"jev_questions_{SCHEMA_VERSION}"
    assert schema["endpoint"] == "https://api.typesafe.ai/v1/systemone"
    assert schema["model"] == "jev-latest"


def test_exactly_three_questions_of_the_expected_primitive_types():
    questions = load_schema()["questions"]
    assert set(questions) == QUESTION_NAMES
    assert questions["action"]["type"] == "choice"
    assert questions["aggressiveness"]["type"] == "score"
    assert questions["already_priced"]["type"] == "noul"


def test_action_criteria_are_exactly_buy_sell_pass():
    assert set(load_schema()["questions"]["action"]["criteria"]) == {
        "buy",
        "sell",
        "pass",
    }
    assert [a.value for a in Action] == ["buy", "sell", "pass"]


def test_score_has_the_declared_number_of_ordered_levels():
    schema = load_schema()
    assert schema["score_levels"] == 5
    assert len(schema["questions"]["aggressiveness"]["criteria"]) == 5


def test_the_question_wording_is_hash_locked():
    """Reword any instruction or criterion and this fails. That is the point."""
    schema = load_schema()
    locked = {
        name: {
            "instructions": q["instructions"],
            "criteria": q.get("criteria"),
        }
        for name, q in schema["questions"].items()
    }
    blob = json.dumps(locked, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert hashlib.sha256(blob.encode("utf-8")).hexdigest() == schema[
        "instructions_sha256"
    ]


def test_the_schema_file_is_where_the_code_thinks_it_is():
    assert pathlib.Path(SCHEMA_PATH).is_file()


def test_rationale_is_gone_because_jev_emits_no_text():
    schema = json.dumps(load_schema())
    assert "rationale" not in schema
    assert not hasattr(Decision("buy", 0.5, 0.1, {"buy": 1.0, "sell": 0.0, "pass": 0.0}), "rationale")


# --- score normalisation ----------------------------------------------------


def test_the_lowest_level_maps_to_zero():
    assert normalise_score(0.0, levels=5, base=0) == 0.0


def test_the_highest_level_maps_to_one():
    assert normalise_score(4.0, levels=5, base=0) == 1.0


def test_the_middle_level_maps_to_a_half():
    assert normalise_score(2.0, levels=5, base=0) == pytest.approx(0.5)


def test_a_fractional_score_maps_proportionally():
    assert normalise_score(1.035, levels=5, base=0) == pytest.approx(0.25875)


def test_a_one_indexed_scale_is_handled():
    assert normalise_score(1.0, levels=5, base=1) == 0.0
    assert normalise_score(5.0, levels=5, base=1) == 1.0


def test_out_of_range_scores_are_clamped_not_rejected():
    assert normalise_score(-3.0, levels=5, base=0) == 0.0
    assert normalise_score(99.0, levels=5, base=0) == 1.0


# --- parsing a Jev answer set ----------------------------------------------


def test_a_valid_answer_set_becomes_a_decision():
    decision = Decision.from_answers(jev_answers())
    assert decision.action is Action.BUY
    assert decision.aggressiveness == pytest.approx(0.5)
    assert decision.already_priced == pytest.approx(0.3)


def test_confidence_is_the_probability_of_the_chosen_action():
    decision = Decision.from_answers(jev_answers(choice="sell"))
    assert decision.confidence == pytest.approx(0.2)


def test_the_models_own_confidence_scalar_is_kept_as_a_secondary_field():
    assert Decision.from_answers(jev_answers()).model_confidence == pytest.approx(0.66)


def test_already_priced_stays_a_probability_and_is_not_thresholded():
    decision = Decision.from_answers(jev_answers(noul=0.51))
    assert decision.already_priced == pytest.approx(0.51)
    assert not isinstance(decision.already_priced, bool)


def test_probabilities_are_carried_through_for_the_sampling_arm():
    decision = Decision.from_answers(jev_answers())
    assert decision.action_probabilities == {"buy": 0.7, "sell": 0.2, "pass": 0.1}


def test_rejects_an_unknown_choice():
    with pytest.raises(ValueError):
        Decision.from_answers(jev_answers(choice="hodl"))


def test_rejects_probabilities_that_do_not_sum_to_one():
    with pytest.raises(ValueError):
        Decision.from_answers(
            jev_answers(probabilities={"buy": 0.7, "sell": 0.7, "pass": 0.7})
        )


def test_rejects_probabilities_missing_an_action():
    with pytest.raises(ValueError):
        Decision.from_answers(jev_answers(probabilities={"buy": 0.6, "sell": 0.4}))


def test_rejects_a_noul_outside_zero_to_one():
    with pytest.raises(ValueError):
        Decision.from_answers(jev_answers(noul=1.7))


def test_rejects_a_missing_question():
    answers = jev_answers()
    del answers["aggressiveness"]
    with pytest.raises(ValueError):
        Decision.from_answers(answers)


def test_rejects_an_answer_of_the_wrong_primitive_type():
    answers = jev_answers()
    answers["action"]["type"] = "noul"
    with pytest.raises(ValueError):
        Decision.from_answers(answers)


# --- the arm-agnostic constructor used by ZI and NBR ------------------------


def test_any_arm_can_build_a_decision_from_a_distribution():
    decision = Decision.create(
        action="sell", aggressiveness=0.25, already_priced=0.4,
        action_probabilities={"buy": 0.3, "sell": 0.5, "pass": 0.2},
    )
    assert decision.action is Action.SELL
    assert decision.confidence == pytest.approx(0.5)
    assert decision.model_confidence is None


def test_create_rejects_an_aggressiveness_outside_the_unit_interval():
    with pytest.raises(ValueError):
        Decision.create(
            action="buy", aggressiveness=1.4, already_priced=0.0,
            action_probabilities={"buy": 1.0, "sell": 0.0, "pass": 0.0},
        )
