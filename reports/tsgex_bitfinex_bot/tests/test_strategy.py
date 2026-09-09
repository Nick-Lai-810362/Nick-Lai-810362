import dataclasses

from tsgex_bfx_bot.strategy import (
    best_rate_by_tenor,
    build_tranches_for_tenor,
    compute_spike_signal,
    decide_tenor_allocation,
)


def test_best_rate_by_tenor_picks_lowest_rate_per_bucket():
    book = [
        [0.0005, 2, 1, 100], [0.0003, 2, 1, 100], [0.0004, 2, 1, 100],
        [0.0010, 30, 1, 100],
    ]
    out = best_rate_by_tenor(book)
    assert out[2] == 0.0003
    assert out[30] == 0.0010


def test_best_rate_by_tenor_ignores_non_target_tenors():
    book = [[0.0005, 2, 1, 100], [0.0002, 5, 1, 100]]  # 5d isn't in TARGET_TENORS
    out = best_rate_by_tenor(book)
    assert 5 not in out
    assert out == {2: 0.0005}


def test_decide_tenor_allocation_stays_all_short_when_no_premium(cfg):
    tenor_rates = {2: 0.0002, 30: 0.0002}  # identical rate, no premium
    alloc = decide_tenor_allocation(tenor_rates, cfg)
    assert alloc == {2: 1.0}


def test_decide_tenor_allocation_shifts_to_long_when_premium_clears_threshold(cfg):
    # 2d = 5.475% gross, 30d = 14.6% gross -> well past cfg.term_premium_min_pp (2pp net)
    tenor_rates = {2: 0.00015, 30: 0.0004}
    alloc = decide_tenor_allocation(tenor_rates, cfg)
    assert 30 in alloc
    assert alloc[30] > 0
    assert sum(alloc.values()) == 1.0


def test_decide_tenor_allocation_excludes_120d_without_authorization(cfg):
    tenor_rates = {2: 0.0002, 120: 0.0010}
    alloc = decide_tenor_allocation(tenor_rates, cfg)
    assert 120 not in alloc


def test_decide_tenor_allocation_includes_120d_when_authorized(cfg):
    cfg2 = dataclasses.replace(cfg, authorize_extreme_tenor=True)
    tenor_rates = {2: 0.00015, 120: 0.0004}
    alloc = decide_tenor_allocation(tenor_rates, cfg2)
    assert 120 in alloc


def test_decide_tenor_allocation_empty_book_returns_empty():
    assert decide_tenor_allocation({}, None) == {}


def test_compute_spike_signal_false_before_window_fills(cfg):
    assert compute_spike_signal([0.1] * 5, cfg) is False  # < spike_slow_window (24)


def test_compute_spike_signal_true_on_upward_crossover(cfg):
    history = [0.05] * 20 + [0.20] * 6  # recent fast MA >> slow MA
    assert compute_spike_signal(history, cfg) is True


def test_compute_spike_signal_false_when_flat(cfg):
    history = [0.07] * 30
    assert compute_spike_signal(history, cfg) is False


def test_build_tranches_for_tenor_is_inverted_pyramid(cfg):
    tranches = build_tranches_for_tenor(10_000.0, 0.0002, 2, cfg)
    amounts = [a for a, r in tranches]
    rates = [r for a, r in tranches]
    assert amounts == sorted(amounts)  # size increases monotonically
    assert rates == sorted(rates)      # rate increases monotonically too
    assert sum(amounts) == 10_000.0 or abs(sum(amounts) - 10_000.0) < 1e-6


def test_build_tranches_for_tenor_respects_max_orders_cap(cfg):
    cfg2 = dataclasses.replace(cfg, max_orders_per_cycle=5)
    tranches = build_tranches_for_tenor(1_000_000.0, 0.0002, 2, cfg2)
    assert len(tranches) == 5


def test_build_tranches_for_tenor_single_tranche_for_small_capital(cfg):
    tranches = build_tranches_for_tenor(50.0, 0.0002, 2, cfg)
    assert len(tranches) == 1
    assert tranches[0][0] == 50.0
