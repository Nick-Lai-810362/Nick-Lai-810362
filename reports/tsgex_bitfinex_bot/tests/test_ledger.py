from datetime import timedelta

from pytest import approx

from tsgex_bfx_bot.ledger import (
    BotState,
    cancel_position,
    contribute_principal,
    export_positions_csv,
    load_state,
    mark_filled,
    open_position,
    reconcile_matured_positions,
    save_state,
)


def test_contribute_principal_increases_both_totals(state):
    contribute_principal(state, 1000.0)
    assert state.principal_contributed_total == 1000.0
    assert state.idle_principal == 1000.0


def test_open_position_first_draw_is_pure_principal(funded_state, now):
    pos = open_position(funded_state, 500.0, 0.0002, 2, now)
    assert pos.principal_component == 500.0
    assert pos.profit_component == 0.0
    assert pos.status == "pending"
    assert pos.maturity_ts is None  # not filled yet
    assert funded_state.idle_principal == 100_000.0 - 500.0


def test_open_position_draws_proportionally_once_profit_exists(funded_state, now):
    # simulate some realized profit sitting idle alongside principal
    funded_state.idle_profit = 10_000.0  # 10% of the 100k+10k pool
    pos = open_position(funded_state, 1000.0, 0.0002, 2, now)
    assert pos.principal_component == approx(1000.0 * 100_000 / 110_000)
    assert pos.profit_component == approx(1000.0 * 10_000 / 110_000)


def test_mark_filled_starts_maturity_clock_from_fill_time_not_placement_time(funded_state, now):
    pos = open_position(funded_state, 500.0, 0.0002, 7, now)
    later = now + timedelta(hours=5)
    mark_filled(pos, later)
    assert pos.status == "active"
    assert pos.filled_ts == later.isoformat()
    assert pos.maturity_ts == (later + timedelta(days=7)).isoformat()


def test_reconcile_matured_positions_computes_simple_interest(funded_state, now):
    pos = open_position(funded_state, 1000.0, 0.0002, 2, now)
    mark_filled(pos, now)
    matured = reconcile_matured_positions(funded_state, now + timedelta(days=2))
    assert len(matured) == 1
    expected_interest = 1000.0 * 0.0002 * 2
    assert matured[0].interest_earned == approx(expected_interest)
    assert funded_state.idle_principal == approx(100_000.0 - 1000.0 + 1000.0)
    assert funded_state.idle_profit == approx(expected_interest)
    assert funded_state.realized_profit_total == approx(expected_interest)


def test_reconcile_matured_positions_ignores_positions_not_yet_due(funded_state, now):
    pos = open_position(funded_state, 1000.0, 0.0002, 30, now)
    mark_filled(pos, now)
    matured = reconcile_matured_positions(funded_state, now + timedelta(days=1))
    assert matured == []
    assert pos.status == "active"


def test_reconcile_matured_positions_ignores_pending_positions(funded_state, now):
    open_position(funded_state, 1000.0, 0.0002, 2, now)  # never filled
    matured = reconcile_matured_positions(funded_state, now + timedelta(days=30))
    assert matured == []


def test_cancel_position_returns_full_capital_with_zero_interest(funded_state, now):
    funded_state.idle_profit = 5000.0
    pos = open_position(funded_state, 1000.0, 0.0002, 2, now)
    idle_before = funded_state.idle_principal + funded_state.idle_profit
    cancel_position(funded_state, pos, now + timedelta(hours=6))
    assert pos.status == "cancelled"
    assert pos.interest_earned == 0.0
    assert funded_state.idle_principal + funded_state.idle_profit == approx(idle_before + 1000.0)


def test_profit_tag_propagates_through_relending(funded_state, now):
    """A position opened from a pool that's already partly profit should
    itself carry that profit tag forward -- and interest earned on it
    (however funded) is always new profit, never reclassified as principal."""
    pos1 = open_position(funded_state, 10_000.0, 0.001, 2, now)  # all principal
    mark_filled(pos1, now)
    reconcile_matured_positions(funded_state, now + timedelta(days=2))
    assert funded_state.idle_profit > 0

    # relend everything idle into one new position: it should carry BOTH tags
    total_idle = funded_state.idle_principal + funded_state.idle_profit
    pos2 = open_position(funded_state, total_idle, 0.001, 2, now)
    assert pos2.principal_component > 0
    assert pos2.profit_component > 0
    mark_filled(pos2, now)
    matured2 = reconcile_matured_positions(funded_state, now + timedelta(days=2))
    # interest on pos2 (funded partly by profit) is still counted as new profit
    assert matured2[0].interest_earned > 0
    assert funded_state.realized_profit_total > matured2[0].interest_earned  # includes pos1's interest too


def test_save_load_state_roundtrip(funded_state, now, tmp_path):
    pos = open_position(funded_state, 500.0, 0.0002, 2, now)
    mark_filled(pos, now)
    path = str(tmp_path / "state.json")
    save_state(funded_state, path)
    loaded = load_state(path)
    assert loaded.principal_contributed_total == funded_state.principal_contributed_total
    assert len(loaded.positions) == 1
    assert loaded.positions[0].status == "active"


def test_load_state_missing_file_returns_fresh_state(tmp_path):
    s = load_state(str(tmp_path / "does_not_exist.json"))
    assert s == BotState()


def test_export_positions_csv_filters_by_tenor(funded_state, now, tmp_path):
    open_position(funded_state, 100.0, 0.0002, 2, now)
    open_position(funded_state, 100.0, 0.0002, 30, now)
    path = str(tmp_path / "out.csv")
    n = export_positions_csv(funded_state, path, tenor_filter=2)
    assert n == 1


def test_export_positions_csv_filters_by_date_range(funded_state, now, tmp_path):
    open_position(funded_state, 100.0, 0.0002, 2, now - timedelta(days=10))
    open_position(funded_state, 100.0, 0.0002, 2, now)
    path = str(tmp_path / "out.csv")
    n = export_positions_csv(funded_state, path, start_dt=now - timedelta(days=1))
    assert n == 1


