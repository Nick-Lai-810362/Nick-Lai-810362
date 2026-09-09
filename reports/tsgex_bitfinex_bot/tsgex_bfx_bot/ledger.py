"""
Principal / profit ledger -- persistent across runs. Every dollar is tagged
PRINCIPAL (what was originally contributed) or PROFIT (interest realized,
including interest realized on capital that itself already contained
reinvested profit -- the tag propagates forward through re-lending, so
compounded profit-on-profit is still counted as profit, never silently
reclassified as principal).

Position lifecycle: pending (submitted, capital committed, not yet earning)
-> active (filled, tenor clock running) -> matured (settled) -- or
pending -> cancelled (stale order pulled, capital returned, zero interest;
see execution.reconcile_pending_offers).
"""
import csv
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


@dataclass
class Position:
    id: str
    amount: float
    principal_component: float
    profit_component: float
    daily_rate: float
    tenor_days: int
    placed_ts: str
    offer_id: Optional[str] = None
    filled_ts: Optional[str] = None
    maturity_ts: Optional[str] = None
    status: str = "pending"  # "pending" | "active" | "matured" | "cancelled"
    matured_ts: Optional[str] = None
    interest_earned: Optional[float] = None
    label: str = ""


@dataclass
class BotState:
    principal_contributed_total: float = 0.0
    idle_principal: float = 0.0
    idle_profit: float = 0.0
    realized_profit_total: float = 0.0
    positions: List[Position] = field(default_factory=list)  # full history


def load_state(path: str) -> BotState:
    if not os.path.exists(path):
        return BotState()
    with open(path) as f:
        raw = json.load(f)
    raw["positions"] = [Position(**p) for p in raw.get("positions", [])]
    return BotState(**raw)


def save_state(state: BotState, path: str) -> None:
    with open(path, "w") as f:
        json.dump(asdict(state), f, ensure_ascii=False, indent=2)


def contribute_principal(state: BotState, amount: float) -> None:
    state.principal_contributed_total += amount
    state.idle_principal += amount


def available_balance(state: BotState) -> float:
    return max(0.0, state.idle_principal + state.idle_profit)


def reconcile_matured_positions(state: BotState, now: datetime) -> List[Position]:
    """Settles any ACTIVE (filled) position whose tenor has elapsed:
    principal returns to idle_principal unchanged, interest earned is added
    to idle_profit AND realized_profit_total."""
    just_matured = []
    for p in state.positions:
        if p.status != "active" or p.maturity_ts is None:
            continue
        if datetime.fromisoformat(p.maturity_ts) > now:
            continue
        interest = p.amount * p.daily_rate * p.tenor_days
        state.idle_principal += p.principal_component
        state.idle_profit += p.profit_component + interest
        state.realized_profit_total += interest
        p.status = "matured"
        p.matured_ts = now.isoformat()
        p.interest_earned = interest
        just_matured.append(p)
    return just_matured


def open_position(state: BotState, amount: float, daily_rate: float, tenor_days: int,
                   now: datetime, label: str = "", offer_id=None) -> Position:
    """Draws `amount` proportionally from the idle principal/profit pools at
    SUBMISSION time (capital is committed the moment an offer is placed,
    even before it's matched -- matches real Bitfinex account behavior) and
    creates a new PENDING position."""
    total_idle = state.idle_principal + state.idle_profit
    principal_frac = (state.idle_principal / total_idle) if total_idle > 1e-9 else 1.0
    principal_component = amount * principal_frac
    profit_component = amount - principal_component
    state.idle_principal = max(0.0, state.idle_principal - principal_component)
    state.idle_profit = max(0.0, state.idle_profit - profit_component)

    pos = Position(
        id=str(uuid.uuid4())[:8], amount=amount, principal_component=principal_component,
        profit_component=profit_component, daily_rate=daily_rate, tenor_days=tenor_days,
        placed_ts=now.isoformat(), offer_id=str(offer_id) if offer_id is not None else None,
        status="pending", label=label,
    )
    state.positions.append(pos)
    return pos


def mark_filled(position: Position, now: datetime) -> None:
    position.status = "active"
    position.filled_ts = now.isoformat()
    position.maturity_ts = (now + timedelta(days=position.tenor_days)).isoformat()


def cancel_position(state: BotState, position: Position, now: datetime) -> None:
    """Stale/unfilled order pulled: capital returns to the idle pools
    unchanged (zero interest -- it never earned anything)."""
    state.idle_principal += position.principal_component
    state.idle_profit += position.profit_component
    position.status = "cancelled"
    position.matured_ts = now.isoformat()
    position.interest_earned = 0.0


CSV_COLUMNS = ["id", "status", "label", "tenor_days", "amount", "principal_component",
               "profit_component", "daily_rate", "gross_apr", "net_apr", "placed_ts", "filled_ts",
               "maturity_ts", "matured_ts", "interest_earned"]


def export_positions_csv(state: BotState, path: str, tenor_filter: Optional[int] = None,
                          start_dt: Optional[datetime] = None, end_dt: Optional[datetime] = None,
                          platform_fee_for_display: float = 0.15) -> int:
    rows = state.positions
    if tenor_filter is not None:
        rows = [p for p in rows if p.tenor_days == tenor_filter]
    if start_dt is not None:
        rows = [p for p in rows if datetime.fromisoformat(p.placed_ts) >= start_dt]
    if end_dt is not None:
        rows = [p for p in rows if datetime.fromisoformat(p.placed_ts) <= end_dt]
    rows = sorted(rows, key=lambda p: p.placed_ts)

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for p in rows:
            gross = p.daily_rate * 365
            w.writerow([p.id, p.status, p.label, p.tenor_days, f"{p.amount:.2f}",
                        f"{p.principal_component:.2f}", f"{p.profit_component:.2f}", p.daily_rate,
                        f"{gross:.4f}", f"{gross*(1-platform_fee_for_display):.4f}", p.placed_ts,
                        p.filled_ts or "", p.maturity_ts or "", p.matured_ts or "",
                        f"{p.interest_earned:.2f}" if p.interest_earned is not None else ""])
    return len(rows)
