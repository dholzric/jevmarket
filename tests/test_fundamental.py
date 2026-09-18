"""The jumping fundamental and the information treatments built on it."""

import pytest

from jevmarket.fundamental import Fundamental, Signal


def test_same_seed_gives_identical_paths():
    a = Fundamental(initial=100.0, jump_prob=0.05, jump_sd=8.0, seed=7).path(500)
    b = Fundamental(initial=100.0, jump_prob=0.05, jump_sd=8.0, seed=7).path(500)
    assert a == b


def test_different_seeds_give_different_paths():
    a = Fundamental(initial=100.0, jump_prob=0.05, jump_sd=8.0, seed=1).path(500)
    b = Fundamental(initial=100.0, jump_prob=0.05, jump_sd=8.0, seed=2).path(500)
    assert a != b


def test_path_has_one_value_per_period():
    assert len(Fundamental(initial=100.0, seed=1).path(250)) == 250


def test_zero_jump_probability_leaves_the_fundamental_flat():
    path = Fundamental(initial=100.0, jump_prob=0.0, jump_sd=8.0, seed=3).path(200)
    assert set(path) == {100.0}


def test_certain_jumps_move_the_fundamental_every_period_after_the_first():
    f = Fundamental(initial=100.0, jump_prob=1.0, jump_sd=8.0, seed=3)
    path = f.path(50)
    assert path[0] == 100.0
    assert all(path[t] != path[t - 1] for t in range(1, 50))


def test_jump_times_are_recorded_for_post_jump_analysis():
    f = Fundamental(initial=100.0, jump_prob=0.1, jump_sd=8.0, seed=11)
    f.path(1_000)
    assert f.jump_times, "no jumps recorded in 1000 periods at p=0.1"
    assert all(0 < t < 1_000 for t in f.jump_times)


def test_fundamental_stays_positive():
    f = Fundamental(initial=100.0, jump_prob=0.5, jump_sd=40.0, seed=5, floor=1.0)
    assert min(f.path(2_000)) >= 1.0


# --- information treatments -------------------------------------------------


def test_full_information_signal_is_the_fundamental():
    path = [100.0, 104.0, 99.0]
    signal = Signal(delay=0, noise_sd=0.0, seed=1)
    assert [signal.observe(path, t) for t in range(3)] == path


def test_delayed_signal_reports_an_earlier_fundamental():
    path = [100.0, 104.0, 99.0, 97.0]
    signal = Signal(delay=2, noise_sd=0.0, seed=1)
    assert signal.observe(path, 3) == 104.0


def test_delayed_signal_clamps_at_the_start_of_the_path():
    path = [100.0, 104.0, 99.0]
    signal = Signal(delay=5, noise_sd=0.0, seed=1)
    assert signal.observe(path, 1) == 100.0


def test_noisy_signal_differs_from_the_fundamental_but_is_reproducible():
    path = [100.0] * 20
    a = [Signal(delay=0, noise_sd=3.0, seed=9).observe(path, t) for t in range(20)]
    b = [Signal(delay=0, noise_sd=3.0, seed=9).observe(path, t) for t in range(20)]
    assert a == b
    assert any(x != 100.0 for x in a)


def test_noise_draw_is_stable_for_a_given_period():
    signal = Signal(delay=0, noise_sd=3.0, seed=9)
    path = [100.0] * 5
    assert signal.observe(path, 3) == signal.observe(path, 3)


def test_rejects_negative_delay():
    with pytest.raises(ValueError):
        Signal(delay=-1, noise_sd=0.0, seed=1)


# --- matched-jump design ----------------------------------------------------


def test_matched_jumps_alternate_direction():
    from jevmarket.fundamental import MatchedJumpFundamental

    f = MatchedJumpFundamental(initial=100.0, jump_size=10.0, period_gap=20, seed=1)
    path = f.path(200)
    deltas = [path[t] - path[t - 1] for t in f.jump_times]
    signs = [1 if d > 0 else -1 for d in deltas]
    assert signs == [(-1) ** i * signs[0] for i in range(len(signs))]


def test_matched_jumps_have_identical_magnitude():
    from jevmarket.fundamental import MatchedJumpFundamental

    f = MatchedJumpFundamental(initial=100.0, jump_size=10.0, period_gap=20, seed=1)
    path = f.path(200)
    magnitudes = {abs(path[t] - path[t - 1]) for t in f.jump_times}
    assert magnitudes == {10.0}


def test_equal_numbers_of_up_and_down_jumps():
    from jevmarket.fundamental import MatchedJumpFundamental

    f = MatchedJumpFundamental(initial=100.0, jump_size=10.0, period_gap=20, seed=1)
    path = f.path(200)
    ups = sum(1 for t in f.jump_times if path[t] > path[t - 1])
    downs = sum(1 for t in f.jump_times if path[t] < path[t - 1])
    assert ups == downs


def test_the_path_returns_to_where_it_started():
    """Matched pairs mean no drift, so up and down windows see the same levels."""
    from jevmarket.fundamental import MatchedJumpFundamental

    f = MatchedJumpFundamental(initial=100.0, jump_size=10.0, period_gap=20, seed=1)
    path = f.path(200)
    assert path[-1] in (100.0, 110.0)


def test_jumps_are_evenly_spaced_so_every_window_is_the_same_length():
    from jevmarket.fundamental import MatchedJumpFundamental

    f = MatchedJumpFundamental(initial=100.0, jump_size=10.0, period_gap=25, seed=1)
    f.path(200)
    gaps = {b - a for a, b in zip(f.jump_times, f.jump_times[1:])}
    assert gaps == {25}


def test_the_starting_direction_is_seeded_not_fixed():
    from jevmarket.fundamental import MatchedJumpFundamental

    def first_sign(seed):
        f = MatchedJumpFundamental(initial=100.0, jump_size=10.0, period_gap=20, seed=seed)
        path = f.path(200)
        return 1 if path[f.jump_times[0]] > 100.0 else -1

    assert {first_sign(s) for s in range(10)} == {1, -1}
