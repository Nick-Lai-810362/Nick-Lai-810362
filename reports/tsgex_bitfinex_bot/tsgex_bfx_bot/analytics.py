"""
Pure, backend-agnostic analytics over a BotState ledger -- asset overview,
open-offer detail, filterable lending history, earnings, and APR. No network
or filesystem access here: everything is a function of state (+ now for
time-dependent metrics), so these are unit-tested directly and reused as-is
by webapp.py's JSON API.

Position.daily_rate is always the GROSS quoted rate (what execution.py sends
to Bitfinex -- see place_tranche); net-of-platform-fee figures here are
therefore an ESTIMATE using a single `platform_fee` passed in (a bot run
normally uses one consistent --order-visibility for its whole run, so one
fee rate is representative, but this module has no per-position record of
which visibility placed which order).
"""
from datetime import datetime
from typing import Dict, List, Optional

from .constants import PLATFORM_FEE_STANDARD
from .ledger import BotState


def overview(state: BotState) -> dict:
    open_positions = [p for p in state.positions if p.status in ("active", "pending")]
    active_amount = sum(p.amount for p in open_positions if p.status == "active")
    pending_amount = sum(p.amount for p in open_positions if p.status == "pending")
    idle_total = state.idle_principal + state.idle_profit
    return {
        "principal_contributed_total": state.principal_contributed_total,
        "idle_principal": state.idle_principal,
        "idle_profit": state.idle_profit,
        "idle_total": idle_total,
        "committed_active": active_amount,
        "committed_pending": pending_amount,
        "committed_total": active_amount + pending_amount,
        "realized_profit_total": state.realized_profit_total,
        "net_worth_estimate": idle_total + active_amount + pending_amount,
        "position_count_total": len(state.positions),
        "position_count_open": len(open_positions),
    }


def open_offers(state: BotState, platform_fee: float = PLATFORM_FEE_STANDARD) -> List[dict]:
    """Currently outstanding orders (pending = submitted, not yet matched;
    active = filled, tenor clock running), most recently placed first."""
    rows = sorted((p for p in state.positions if p.status in ("pending", "active")),
                  key=lambda p: p.placed_ts, reverse=True)
    return [{
        "id": p.id, "offer_id": p.offer_id, "status": p.status, "label": p.label,
        "tenor_days": p.tenor_days, "amount": p.amount,
        "daily_rate": p.daily_rate, "gross_apr": p.daily_rate * 365,
        "net_apr": p.daily_rate * 365 * (1 - platform_fee),
        "placed_ts": p.placed_ts, "filled_ts": p.filled_ts, "maturity_ts": p.maturity_ts,
    } for p in rows]


def history(state: BotState, tenor: Optional[int] = None, status: Optional[str] = None,
            start: Optional[datetime] = None, end: Optional[datetime] = None,
            platform_fee: float = PLATFORM_FEE_STANDARD) -> List[dict]:
    """Full position history (every status), filtered -- the exhaustive
    lending-history table backing the dashboard's 出借歷史紀錄 view."""
    rows = state.positions
    if tenor is not None:
        rows = [p for p in rows if p.tenor_days == tenor]
    if status is not None:
        rows = [p for p in rows if p.status == status]
    if start is not None:
        rows = [p for p in rows if datetime.fromisoformat(p.placed_ts) >= start]
    if end is not None:
        rows = [p for p in rows if datetime.fromisoformat(p.placed_ts) <= end]
    rows = sorted(rows, key=lambda p: p.placed_ts, reverse=True)
    return [{
        "id": p.id, "status": p.status, "label": p.label, "tenor_days": p.tenor_days,
        "amount": p.amount, "principal_component": p.principal_component,
        "profit_component": p.profit_component, "daily_rate": p.daily_rate,
        "gross_apr": p.daily_rate * 365, "net_apr": p.daily_rate * 365 * (1 - platform_fee),
        "placed_ts": p.placed_ts, "filled_ts": p.filled_ts, "maturity_ts": p.maturity_ts,
        "matured_ts": p.matured_ts, "interest_earned": p.interest_earned,
    } for p in rows]


def earnings(state: BotState) -> dict:
    matured = sorted((p for p in state.positions if p.status == "matured" and p.matured_ts),
                      key=lambda p: p.matured_ts)
    cumulative = []
    running = 0.0
    for p in matured:
        running += p.interest_earned or 0.0
        cumulative.append({"matured_ts": p.matured_ts, "cumulative_profit": running})

    by_tenor: Dict[int, float] = {}
    for p in matured:
        by_tenor[p.tenor_days] = by_tenor.get(p.tenor_days, 0.0) + (p.interest_earned or 0.0)

    return {
        "realized_profit_total": state.realized_profit_total,
        "matured_position_count": len(matured),
        "cancelled_stale_count": sum(1 for p in state.positions if p.status == "cancelled"),
        "cumulative_by_maturity": cumulative,
        "profit_by_tenor": by_tenor,
    }


def apr(state: BotState, now: datetime, platform_fee: float = PLATFORM_FEE_STANDARD) -> dict:
    """Two different, both-legitimate APR readings:

    - `current_weighted_gross_apr`/`net_apr`: right now, amount-weighted over
      ACTIVE (already filled, earning) capital -- "if nothing changes, what
      am I earning on deployed capital today". Pending capital isn't earning
      yet so it's excluded, matching how the bot itself treats it.
    - `realized_apr`: the account's actual track record -- realized_profit_
      total annualized against total contributed principal over the time
      elapsed since the earliest recorded position. This UNDERSTATES true
      capital-efficiency (principal wasn't necessarily all deployed from day
      one) but is a conservative, hard-to-game "what did I actually get from
      what I put in" number. None if there's no history yet to measure.

    CAVEAT (found via manual smoke-testing against a real ledger, not just
    unit fixtures): `now` and every Position's `placed_ts` are assumed to
    share one clock. Live/dry-run cycles satisfy this (both come from real
    wall-clock time). A ledger produced with `--mock-days-per-cycle` does
    NOT -- its position timestamps are simulated dates that can sit weeks
    ahead of the real wall-clock `now` this function is called with (e.g.
    from webapp.py), which inflates `elapsed_days` toward ~0 and
    `realized_apr` toward a meaningless huge number. Only relevant to fast-
    forwarded mock demos, not real trading.
    """
    active = [p for p in state.positions if p.status == "active"]
    active_amount = sum(p.amount for p in active)
    weighted_gross = (sum(p.amount * p.daily_rate * 365 for p in active) / active_amount
                       if active_amount > 1e-9 else None)
    weighted_net = weighted_gross * (1 - platform_fee) if weighted_gross is not None else None

    realized_apr = None
    elapsed_days = None
    if state.positions and state.principal_contributed_total > 1e-9:
        earliest = min(datetime.fromisoformat(p.placed_ts) for p in state.positions)
        elapsed_days = (now - earliest).total_seconds() / 86400.0
        if elapsed_days > 0:
            realized_apr = (state.realized_profit_total / state.principal_contributed_total) * (365.0 / elapsed_days)

    return {
        "current_weighted_gross_apr": weighted_gross,
        "current_weighted_net_apr": weighted_net,
        "current_active_capital": active_amount,
        "realized_apr": realized_apr,
        "realized_profit_total": state.realized_profit_total,
        "elapsed_days": elapsed_days,
    }
