from datetime import timedelta

from pytest import approx

from tsgex_bfx_bot.analytics import apr, earnings, history, open_offers, overview
from tsgex_bfx_bot.ledger import cancel_position, mark_filled, open_position, reconcile_matured_positions


def test_overview_reflects_idle_and_committed_capital(funded_state, now):
    open_position(funded_state, 1000.0, 0.0002, 2, now)  # pending
    o = overview(funded_state)
    assert o["principal_contributed_total"] == 100_000.0
    assert o["committed_pending"] == 1000.0
    assert o["committed_active"] == 0.0
    assert o["idle_principal"] == 100_000.0 - 1000.0
    assert o["net_worth_estimate"] == approx(100_000.0)  # nothing earned yet, capital just moved buckets
    assert o["position_count_open"] == 1


def test_overview_separates_active_from_pending(funded_state, now):
    p1 = open_position(funded_state, 500.0, 0.0002, 2, now)
    mark_filled(p1, now)
    open_position(funded_state, 300.0, 0.0002, 7, now)  # still pending
    o = overview(funded_state)
    assert o["committed_active"] == 500.0
    assert o["committed_pending"] == 300.0
    assert o["committed_total"] == 800.0


def test_open_offers_only_includes_pending_and_active(funded_state, now):
    p1 = open_position(funded_state, 500.0, 0.0002, 2, now)
    mark_filled(p1, now)
    p2 = open_position(funded_state, 300.0, 0.0002, 7, now)
    cancel_position(funded_state, p2, now)
    p3 = open_position(funded_state, 200.0, 0.0002, 30, now)  # pending
    rows = open_offers(funded_state)
    statuses = {r["status"] for r in rows}
    assert statuses == {"active", "pending"}
    assert len(rows) == 2


def test_open_offers_computes_gross_and_net_apr(funded_state, now):
    open_position(funded_state, 1000.0, 0.0002, 2, now)
    row = open_offers(funded_state, platform_fee=0.15)[0]
    assert row["gross_apr"] == approx(0.0002 * 365)
    assert row["net_apr"] == approx(0.0002 * 365 * 0.85)


def test_history_filters_by_status(funded_state, now):
    p1 = open_position(funded_state, 500.0, 0.0002, 2, now)
    mark_filled(p1, now)
    open_position(funded_state, 300.0, 0.0002, 7, now)
    rows = history(funded_state, status="pending")
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


def test_history_filters_by_tenor_and_date_range(funded_state, now):
    open_position(funded_state, 100.0, 0.0002, 2, now - timedelta(days=10))
    open_position(funded_state, 100.0, 0.0002, 2, now)
    open_position(funded_state, 100.0, 0.0002, 30, now)
    rows = history(funded_state, tenor=2, start=now - timedelta(days=1))
    assert len(rows) == 1
    assert rows[0]["tenor_days"] == 2


def test_history_includes_every_status_when_unfiltered(funded_state, now):
    p1 = open_position(funded_state, 500.0, 0.0002, 2, now)
    mark_filled(p1, now)
    reconcile_matured_positions(funded_state, now + timedelta(days=2))
    p2 = open_position(funded_state, 300.0, 0.0002, 7, now)
    cancel_position(funded_state, p2, now)
    open_position(funded_state, 200.0, 0.0002, 30, now)  # pending
    rows = history(funded_state)
    assert {r["status"] for r in rows} == {"matured", "cancelled", "pending"}


def test_earnings_sums_realized_profit_by_tenor(funded_state, now):
    p1 = open_position(funded_state, 1000.0, 0.0002, 2, now)
    mark_filled(p1, now)
    reconcile_matured_positions(funded_state, now + timedelta(days=2))
    e = earnings(funded_state)
    assert e["realized_profit_total"] > 0
    assert e["matured_position_count"] == 1
    assert 2 in e["profit_by_tenor"]
    assert e["profit_by_tenor"][2] == approx(e["realized_profit_total"])


def test_earnings_cumulative_series_is_monotonically_increasing(funded_state, now):
    for i in range(3):
        p = open_position(funded_state, 1000.0, 0.0002, 2, now)
        mark_filled(p, now)
    reconcile_matured_positions(funded_state, now + timedelta(days=2))
    e = earnings(funded_state)
    cum = [pt["cumulative_profit"] for pt in e["cumulative_by_maturity"]]
    assert cum == sorted(cum)
    assert len(cum) == 3


def test_earnings_empty_when_nothing_matured(funded_state):
    e = earnings(funded_state)
    assert e["cumulative_by_maturity"] == []
    assert e["profit_by_tenor"] == {}


def test_apr_current_weighted_ignores_pending_capital(funded_state, now):
    p1 = open_position(funded_state, 1000.0, 0.0001, 2, now)   # ~3.65% gross, active
    mark_filled(p1, now)
    open_position(funded_state, 5000.0, 0.001, 30, now)         # ~36.5% gross, still pending -- excluded
    a = apr(funded_state, now)
    assert a["current_active_capital"] == 1000.0
    assert a["current_weighted_gross_apr"] == approx(0.0001 * 365)


def test_apr_realized_apr_none_without_history(state, now):
    a = apr(state, now)
    assert a["realized_apr"] is None
    assert a["current_weighted_gross_apr"] is None


def test_apr_realized_apr_annualizes_against_contributed_principal(funded_state, now):
    p1 = open_position(funded_state, 10_000.0, 0.001, 2, now)  # 36.5% gross
    mark_filled(p1, now)
    reconcile_matured_positions(funded_state, now + timedelta(days=2))
    later = now + timedelta(days=2)
    a = apr(funded_state, later)
    assert a["realized_apr"] is not None
    assert a["realized_apr"] > 0
    assert a["elapsed_days"] == approx(2.0)
