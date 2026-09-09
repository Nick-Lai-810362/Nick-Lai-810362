"""
Order placement and pending-order reconciliation (fill detection + stale
cancel+relist). This is the layer that turns a strategy decision (place N
USD at rate R, tenor T) into an actual exchange call (or dry-run log line)
and a ledger Position, and that keeps pending positions honest against the
exchange's real state every cycle.
"""
import logging
import time
from datetime import datetime
from typing import List

from .client import BitfinexClient, extract_offer_id
from .config import StrategyConfig, net_apr
from .constants import SUBMIT_PACING_SEC
from .ledger import BotState, cancel_position, mark_filled, open_position
from .mock_client import MockBitfinexClient

log = logging.getLogger("tsgex_bot")


def place_tranche(client: BitfinexClient, cfg: StrategyConfig, state: BotState, now: datetime,
                   live: bool, amount: float, rate: float, tenor: int, label: str = "") -> dict:
    """Places (live or --mock) or logs (plain dry-run) one tranche, and
    always records a PENDING Position -- see ledger.open_position."""
    implied_gross_apr = rate * 365
    is_mock = isinstance(client, MockBitfinexClient)
    offer_id = None
    if live or is_mock:
        resp = client.submit_funding_offer(cfg.symbol, amount, rate, tenor)
        offer_id = extract_offer_id(resp)
        if live:
            time.sleep(SUBMIT_PACING_SEC)
    if not live:
        log.info(f"  [DRY-RUN]{label} would place: amount={amount:,.2f}  tenor={tenor}d  "
                 f"daily_rate={rate:.6f} (~{implied_gross_apr:.2%} gross / ~{net_apr(implied_gross_apr, cfg):.2%} net)")
    pos = open_position(state, amount, rate, tenor, now, label=label, offer_id=offer_id)
    return {"position_id": pos.id, "amount": amount, "principal_component": pos.principal_component,
            "profit_component": pos.profit_component, "daily_rate": rate, "gross_apr": implied_gross_apr,
            "net_apr": net_apr(implied_gross_apr, cfg), "tenor_days": tenor, "label": label}


def place_frr_tranche(client: BitfinexClient, cfg: StrategyConfig, state: BotState, now: datetime,
                       live: bool, amount: float, quoted_rate: float, tenor: int) -> dict:
    """FRR mode: the live API call uses rate=0 to mean 'peg to FRR', but the
    LEDGER must not record a 0% accrual rate or this position would silently
    earn nothing. Actual hourly-floating FRR settlement isn't tracked tick-
    by-tick; `quoted_rate` (the currently observed short-tenor rate) is used
    as a disclosed proxy for interest bookkeeping, decoupled from the rate=0
    parameter sent to the exchange."""
    is_mock = isinstance(client, MockBitfinexClient)
    offer_id = None
    if live or is_mock:
        resp = client.submit_frr_offer(cfg.symbol, amount, tenor)
        offer_id = extract_offer_id(resp)
        if live:
            time.sleep(SUBMIT_PACING_SEC)
    if not live:
        log.info(f"  [DRY-RUN] would place FRR-pegged offer: amount={amount:,.2f}  period={tenor}d")
    pos = open_position(state, amount, quoted_rate, tenor, now, label="frr", offer_id=offer_id)
    return {"position_id": pos.id, "amount": amount, "tenor_days": tenor}


def reconcile_pending_offers(client: BitfinexClient, cfg: StrategyConfig, state: BotState,
                              tenor_rates: dict, now: datetime, live: bool) -> List[dict]:
    """Checks every still-pending position against the exchange's real open-
    offers list (fill signal: it's no longer there -- the public API has no
    per-offer partial-fill amount, so this is the correct and only available
    signal). Still-open positions are cancelled + immediately re-listed at
    the current rate if they've waited too long or the market has drifted
    away from their quoted rate."""
    is_mock = isinstance(client, MockBitfinexClient)
    if not (live or is_mock):
        return []  # plain dry-run against the real client: nothing was ever really submitted

    open_ids = {str(o[0]) for o in client.get_active_funding_offers(cfg.symbol)}
    events: List[dict] = []
    for p in list(state.positions):
        if p.status != "pending":
            continue
        if p.offer_id is None or p.offer_id not in open_ids:
            mark_filled(p, now)
            events.append({"event": "filled", "position_id": p.id, "tenor_days": p.tenor_days})
            continue

        placed_dt = datetime.fromisoformat(p.placed_ts)
        wait_hours = (now - placed_dt).total_seconds() / 3600
        max_wait = cfg.max_wait_hours.get(p.tenor_days, 24.0) * cfg.max_wait_multiplier
        current_rate = tenor_rates.get(p.tenor_days)
        drift_pp = abs(net_apr(current_rate * 365, cfg) - net_apr(p.daily_rate * 365, cfg)) if current_rate else None

        stale_reason = None
        if wait_hours >= max_wait:
            stale_reason = f"waited {wait_hours:.1f}h >= max {max_wait:.1f}h"
        elif drift_pp is not None and drift_pp >= cfg.rate_drift_threshold_pp:
            stale_reason = f"rate drifted {drift_pp:.2%} >= threshold {cfg.rate_drift_threshold_pp:.2%}"

        if stale_reason:
            try:
                client.cancel_funding_offer(p.offer_id)
            except Exception as e:
                log.warning(f"  cancel failed for position {p.id}: {e}")
            cancel_position(state, p, now)
            events.append({"event": "cancelled_stale", "position_id": p.id, "tenor_days": p.tenor_days,
                            "reason": stale_reason})
            log.info(f"  cancelled stale {p.tenor_days}d position {p.id} ({stale_reason}) -> re-listing")
            if current_rate is not None:
                new_rec = place_tranche(client, cfg, state, now, live, p.amount, current_rate, p.tenor_days,
                                         label=(p.label + "+relist"))
                events.append({"event": "relisted", **new_rec})
    return events
