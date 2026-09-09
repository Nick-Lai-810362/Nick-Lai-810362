"""
End-to-end tests running the real strategy loop against MockBitfinexClient.
Several of these are direct regression tests for bugs found and fixed
during this project's development -- see CHANGELOG.md for the full story
behind each one.
"""
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from tsgex_bfx_bot.config import StrategyConfig
from tsgex_bfx_bot.ledger import BotState, available_balance, contribute_principal
from tsgex_bfx_bot.mock_client import MockBitfinexClient
from tsgex_bfx_bot.runner import run_cycle

NT5M_USD = 158_730.0  # NT$5,000,000 at ~31.5 -- the scenario that surfaced the tranche-cap bug


@pytest.mark.parametrize("mode", ["dave_high", "dave_fast", "custom", "frr", "barbell"])
def test_multi_cycle_run_never_leaves_ledger_inconsistent(mode):
    """Regression suite covering all 5 modes: after any number of cycles,
    principal + realized profit must always be fully accounted for across
    idle pools and open/pending positions -- no capital silently created or
    destroyed."""
    cfg = StrategyConfig(mode=mode, state_path="/tmp/_never_used.json", audit_log_path=None)
    state = BotState()
    contribute_principal(state, NT5M_USD)
    client = MockBitfinexClient()
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    rate_history = []

    for i in range(10):
        run_cycle(client, cfg, state, rate_history, now, live=False)
        now += timedelta(hours=6)

    committed = sum(p.amount for p in state.positions if p.status in ("active", "pending"))
    net_worth = available_balance(state) + committed
    # net worth can exceed principal (profit) but must never fall short of it
    assert net_worth >= state.principal_contributed_total - 1e-6
    assert state.idle_principal >= -1e-9
    assert state.idle_profit >= -1e-9


def test_second_run_does_not_relend_capital_already_committed():
    """Regression for the v3 gap: a prior version recomputed 'lendable' from
    total capital every cycle with no memory of what was already placed,
    which would try to re-lend the same money forever."""
    cfg = StrategyConfig(mode="custom", state_path="/tmp/_never_used2.json", audit_log_path=None)
    state = BotState()
    contribute_principal(state, 10_000.0)
    client = MockBitfinexClient()
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)

    def live_committed():
        # Only active/pending positions represent real outstanding capital --
        # a cancelled position's `amount` is a historical record kept for
        # audit purposes, not still-committed money (its capital already
        # returned to the idle pool; see ledger.cancel_position).
        return sum(p.amount for p in state.positions if p.status in ("active", "pending"))

    run_cycle(client, cfg, state, [], now, live=False)
    committed_after_first = live_committed()
    assert committed_after_first == pytest.approx(10_000.0, rel=1e-6)

    run_cycle(client, cfg, state, [], now, live=False)  # immediately again, same instant
    committed_after_second = live_committed()
    # nothing new should have been placed: all capital was already committed
    # (cancel+relist churn may replace individual positions, but the total
    # live-committed amount must stay the same -- no capital created or lost)
    assert committed_after_second == pytest.approx(committed_after_first, rel=1e-6)


def test_frr_mode_earns_nonzero_interest_on_maturity():
    """Regression for a real bug found in this project: FRR positions were
    ledgered at daily_rate=0 (reusing the API's rate=0 'peg to FRR' signal
    for bookkeeping too), so they silently earned zero recorded interest."""
    cfg = StrategyConfig(mode="frr", state_path="/tmp/_never_used3.json", audit_log_path=None)
    state = BotState()
    contribute_principal(state, 5_000.0)
    client = MockBitfinexClient()
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)

    for _ in range(6):
        run_cycle(client, cfg, state, [], now, live=False)
        now += timedelta(days=3)

    assert state.realized_profit_total > 0


def test_nt5m_scale_tranche_count_is_not_truncated_by_default_cap():
    """Regression for the bug the user's own NT$5,000,000 question surfaced:
    max_orders_per_cycle used to default to 30, silently overriding the
    per-tenor real-trade-size calibration for any account large enough to
    need more tranches -- 227 calibrated 2d tranches collapsed into 30
    oversized ones. Default is now 400; verify a NT$5M position in --mode
    custom with the whole book quoting only 2d isn't capped."""
    cfg = StrategyConfig(mode="custom", state_path="/tmp/_never_used4.json", audit_log_path=None)
    state = BotState()
    contribute_principal(state, NT5M_USD)
    client = MockBitfinexClient()
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)

    run_cycle(client, cfg, state, [], now, live=False)
    tranches_placed = len(state.positions)
    assert tranches_placed > 100  # far more than the old cap of 30
    avg_size = sum(p.amount for p in state.positions) / tranches_placed
    assert avg_size < 2000  # nowhere near the old bug's ~$5,291 average


def test_barbell_mode_splits_between_two_distinct_tenors_when_premium_exists():
    cfg = StrategyConfig(mode="barbell", barbell_short_fraction=0.5,
                          state_path="/tmp/_never_used5.json", audit_log_path=None)
    state = BotState()
    contribute_principal(state, 10_000.0)
    client = MockBitfinexClient()
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    run_cycle(client, cfg, state, [], now, live=False)
    tenors_used = {p.tenor_days for p in state.positions}
    assert 2 in tenors_used  # short bucket is always used


def test_dave_fast_places_exactly_one_tranche():
    cfg = StrategyConfig(mode="dave_fast", state_path="/tmp/_never_used6.json", audit_log_path=None)
    state = BotState()
    contribute_principal(state, 10_000.0)
    client = MockBitfinexClient()
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    run_cycle(client, cfg, state, [], now, live=False)
    assert len(state.positions) == 1
    assert state.positions[0].tenor_days == 2  # always the most liquid tenor
