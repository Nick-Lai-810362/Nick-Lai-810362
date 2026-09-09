import dataclasses

from tsgex_bfx_bot.constants import BFX_MIN_ORDER_USD
from tsgex_bfx_bot.strategy import (
    best_rate_by_tenor,
    build_tranches_for_tenor,
    compute_spike_signal,
    decide_tenor_allocation,
    depth_by_tenor,
)


def test_best_rate_by_tenor_picks_lowest_rate_per_bucket():
    book = [
        [0.0005, 2, 1, 100], [0.0003, 2, 1, 100], [0.0004, 2, 1, 100],
        [0.0010, 30, 1, 100],
    ]
    out = best_rate_by_tenor(book)
    assert out[2] == 0.0003
    assert out[30] == 0.0010


def test_best_rate_by_tenor_includes_every_period_quoted():
    """v5.2: no longer filtered to a fixed 2/7/30 shortlist -- every period
    actually present in the live book comes through here. Tradeability
    (thin-liquidity filtering) is a separate concern handled by depth_by_tenor
    + cfg.min_period_depth_usd inside decide_tenor_allocation, not here."""
    book = [[0.0005, 2, 1, 100], [0.0002, 5, 1, 100], [0.0009, 17, 1, 50]]
    out = best_rate_by_tenor(book)
    assert out == {2: 0.0005, 5: 0.0002, 17: 0.0009}


def test_depth_by_tenor_sums_amount_per_period():
    book = [[0.0005, 2, 1, 100], [0.0004, 2, 1, 250], [0.0002, 5, -1, 60]]
    out = depth_by_tenor(book)
    assert out[2] == 350
    assert out[5] == 60  # abs() applied -- book amounts can be signed (bid vs offer)


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


def test_decide_tenor_allocation_generalizes_beyond_2_7_30(cfg):
    """v5.2: the live book can quote any period, not just 2/7/30d -- a period
    that clears the premium threshold should get an allocation regardless of
    which specific day-count it is."""
    tenor_rates = {2: 0.00015, 5: 0.00016, 17: 0.0004}
    depth = {2: 10_000.0, 5: 10_000.0, 17: 10_000.0}
    alloc = decide_tenor_allocation(tenor_rates, cfg, depth=depth)
    assert 17 in alloc
    assert alloc[17] > 0
    assert sum(alloc.values()) == 1.0


def test_decide_tenor_allocation_filters_out_thin_depth_periods(cfg):
    """A period with an attractive rate but depth below cfg.min_period_depth_usd
    must be skipped entirely -- a rate quoted by one thin order isn't
    something a real tranche can reliably fill against (v4 finding #1)."""
    tenor_rates = {2: 0.00015, 30: 0.0004}
    depth = {2: 10_000.0, 30: 50.0}  # 30d well below the default min_period_depth_usd
    alloc = decide_tenor_allocation(tenor_rates, cfg, depth=depth)
    assert 30 not in alloc
    assert alloc == {2: 1.0}


def test_decide_tenor_allocation_respects_max_total_shift_from_short(cfg):
    """Even with several longer tenors all clearing the premium bar, the
    short (most liquid) bucket must never be shifted below
    (1 - cfg.max_total_shift_from_short)."""
    cfg2 = dataclasses.replace(cfg, max_total_shift_from_short=0.3, term_premium_min_pp=0.0)
    tenor_rates = {2: 0.0001, 10: 0.001, 20: 0.002, 29: 0.003}
    depth = {t: 10_000.0 for t in tenor_rates}
    alloc = decide_tenor_allocation(tenor_rates, cfg2, depth=depth)
    assert alloc[2] >= 0.7 - 1e-9
    assert sum(alloc.values()) == 1.0


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


def test_build_tranches_fixed_count_splits_evenly(cfg):
    cfg2 = dataclasses.replace(cfg, tranche_sizing_mode="fixed_count", max_concurrent_orders=8)
    tranches = build_tranches_for_tenor(8_000.0, 0.0002, 2, cfg2)
    amounts = [a for a, r in tranches]
    assert len(tranches) == 8
    assert all(abs(a - 1_000.0) < 1e-6 for a in amounts)  # evenly split, not weighted
    assert sum(amounts) == 8_000.0 or abs(sum(amounts) - 8_000.0) < 1e-6


def test_build_tranches_fixed_count_respects_max_concurrent_orders(cfg):
    cfg2 = dataclasses.replace(cfg, tranche_sizing_mode="fixed_count", max_concurrent_orders=50)
    tranches = build_tranches_for_tenor(100_000.0, 0.0002, 2, cfg2)
    assert len(tranches) == 50


def test_build_tranches_fixed_count_shrinks_below_min_order_size(cfg):
    """Requesting more concurrent orders than the capital can support at
    Bitfinex's $150 minimum order size must reduce the count, not place
    orders below the exchange's own minimum."""
    cfg2 = dataclasses.replace(cfg, tranche_sizing_mode="fixed_count", max_concurrent_orders=20)
    tranches = build_tranches_for_tenor(1_000.0, 0.0002, 2, cfg2)
    assert len(tranches) == 6  # floor(1000/150) = 6, not the requested 20
    assert all(a >= BFX_MIN_ORDER_USD - 1e-6 for a, r in tranches)
