"""The three pre-declared primary outcomes, each pinned to a hand-worked case."""

import math

import pytest

from jevmarket.metrics import (
    confidently_wrong_rate,
    expected_calibration_error,
    post_jump_rmse,
    reliability_curve,
    rmse_vs_fundamental,
)


# --- pricing error ----------------------------------------------------------


def test_rmse_is_zero_when_price_tracks_the_fundamental():
    assert rmse_vs_fundamental([100.0, 101.0], [100.0, 101.0]) == 0.0


def test_rmse_matches_a_hand_computed_value():
    # errors of 3 and 4 -> sqrt((9 + 16) / 2) = 3.5355...
    assert rmse_vs_fundamental([103.0, 96.0], [100.0, 100.0]) == pytest.approx(
        math.sqrt(12.5)
    )


def test_periods_with_no_trade_are_skipped_not_treated_as_zero():
    assert rmse_vs_fundamental([None, 103.0], [100.0, 100.0]) == pytest.approx(3.0)


def test_rmse_is_nan_when_nothing_traded():
    assert math.isnan(rmse_vs_fundamental([None, None], [100.0, 100.0]))


def test_post_jump_rmse_only_scores_the_window_after_each_jump():
    prices = [100.0, 100.0, 90.0, 95.0, 100.0]
    fundamental = [100.0, 100.0, 100.0, 100.0, 100.0]
    # jump at t=2, window 2 -> periods 2 and 3, errors 10 and 5
    assert post_jump_rmse(prices, fundamental, [2], window=2) == pytest.approx(
        math.sqrt(62.5)
    )


def test_post_jump_rmse_ignores_periods_before_the_jump():
    prices = [1.0, 100.0, 100.0]
    fundamental = [100.0, 100.0, 100.0]
    assert post_jump_rmse(prices, fundamental, [1], window=2) == 0.0


def test_post_jump_window_is_clipped_at_the_end_of_the_run():
    assert post_jump_rmse([100.0, 90.0], [100.0, 100.0], [1], window=50) == pytest.approx(
        10.0
    )


def test_post_jump_rmse_is_nan_with_no_jumps():
    assert math.isnan(post_jump_rmse([100.0], [100.0], []))


# --- calibration ------------------------------------------------------------


def test_perfectly_calibrated_confidence_has_zero_ece():
    # 10 calls at 0.9 confidence, 9 of them correct
    confidences = [0.9] * 10
    correct = [True] * 9 + [False]
    assert expected_calibration_error(confidences, correct) == pytest.approx(0.0)


def test_always_confident_always_wrong_has_ece_of_one():
    assert expected_calibration_error([1.0] * 20, [False] * 20) == pytest.approx(1.0)


def test_ece_weights_bins_by_how_many_calls_they_hold():
    # 9 calls at 0.5 perfectly calibrated, 1 call at 1.0 that was wrong
    confidences = [0.5] * 8 + [0.5] * 2 + [1.0]
    correct = [True] * 5 + [False] * 5 + [False]
    ece = expected_calibration_error(confidences, correct)
    assert ece == pytest.approx((1 / 11) * 1.0)


def test_ece_is_nan_with_no_calls():
    assert math.isnan(expected_calibration_error([], []))


def test_confidently_wrong_rate_counts_only_loud_calls():
    confidences = [0.9, 0.9, 0.3]
    correct = [True, False, False]
    assert confidently_wrong_rate(confidences, correct, threshold=0.8) == pytest.approx(
        0.5
    )


def test_confidently_wrong_rate_is_nan_when_nothing_was_loud():
    assert math.isnan(confidently_wrong_rate([0.4, 0.5], [True, False], threshold=0.8))


def test_zero_five_confidence_never_counts_as_loud():
    assert math.isnan(confidently_wrong_rate([0.5] * 50, [False] * 50))


def test_reliability_curve_reports_accuracy_and_count_per_bin():
    curve = reliability_curve([0.05, 0.95, 0.95], [False, True, False], n_bins=10)
    first, last = curve[0], curve[-1]
    assert first[1] == pytest.approx(0.0) and first[2] == 1
    assert last[1] == pytest.approx(0.5) and last[2] == 2
    assert sum(b[2] for b in curve) == 3


def test_empty_bins_report_nan_accuracy_and_zero_count():
    curve = reliability_curve([0.95], [True], n_bins=10)
    assert curve[0][2] == 0 and math.isnan(curve[0][1])
