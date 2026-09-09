"""
The main per-cycle strategy loop: reconcile ledger state against the
exchange, read the live book, decide an allocation for the configured mode,
place tranches, and persist everything.
"""
import logging
from datetime import datetime
from typing import List

from .client import BitfinexClient
from .config import StrategyConfig, net_apr
from .constants import BFX_MIN_ORDER_USD
from .execution import place_frr_tranche, place_tranche, reconcile_pending_offers
from .ledger import BotState, available_balance, reconcile_matured_positions, save_state
from .strategy import (
    best_rate_by_tenor,
    build_tranches_for_tenor,
    compute_spike_signal,
    decide_tenor_allocation,
)
from .audit import write_audit_log

log = logging.getLogger("tsgex_bot")


def run_cycle(client: BitfinexClient, cfg: StrategyConfig, state: BotState, rate_history: List[float],
              now: datetime, live: bool) -> None:
    reasoning = []
    matured = reconcile_matured_positions(state, now)
    if matured:
        interest = sum(p.interest_earned for p in matured)
        reasoning.append(f"{len(matured)} position(s) matured -> +{interest:,.2f} realized profit")
        log.info(f"  {len(matured)} position(s) matured, +{interest:,.2f} profit realized")

    book = client.get_funding_book(cfg.symbol)
    if not book:
        log.warning("Empty funding book response, skipping cycle")
        write_audit_log(cfg, {"mode": cfg.mode, "action": "skip", "reason": "empty_funding_book"})
        save_state(state, cfg.state_path)
        return

    tenor_rates = best_rate_by_tenor(book)
    if not tenor_rates:
        log.warning("No quotes at target tenors (2/7/30d), skipping cycle")
        write_audit_log(cfg, {"mode": cfg.mode, "action": "skip", "reason": "no_target_tenor_quotes"})
        save_state(state, cfg.state_path)
        return

    pending_events = reconcile_pending_offers(client, cfg, state, tenor_rates, now, live)
    if pending_events:
        filled_n = sum(1 for e in pending_events if e["event"] == "filled")
        cancelled_n = sum(1 for e in pending_events if e["event"] == "cancelled_stale")
        if filled_n:
            log.info(f"  {filled_n} pending order(s) filled")
        if cancelled_n:
            log.info(f"  {cancelled_n} stale pending order(s) cancelled and re-listed")
        write_audit_log(cfg, {"mode": cfg.mode, "action": "pending_reconcile", "events": pending_events})

    short_tenor = min(tenor_rates)
    gross_apr = tenor_rates[short_tenor] * 365
    net = net_apr(gross_apr, cfg)
    rate_history.append(gross_apr)
    reasoning.append("live rates by tenor: " +
                      ", ".join(f"{t}d={r*365*100:.2f}%gross/{net_apr(r*365,cfg)*100:.2f}%net" for t, r in sorted(tenor_rates.items())))

    lendable = max(0.0, available_balance(state) - cfg.reserved_amount)
    if net < cfg.floor_rate:
        reasoning.append(f"best net rate {net:.2%} below floor_rate {cfg.floor_rate:.2%} -> holding")
        log.info(f"Net rate {net:.2%} (gross {gross_apr:.2%}) below floor_rate {cfg.floor_rate:.2%} -- holding")
        write_audit_log(cfg, {"mode": cfg.mode, "action": "hold", "gross_apr": gross_apr, "net_apr": net,
                               "idle_principal": state.idle_principal, "idle_profit": state.idle_profit,
                               "reasoning": reasoning})
        save_state(state, cfg.state_path)
        return

    if lendable <= 0:
        reasoning.append("no idle capital available (all pending or on loan) -> holding")
        log.info("No idle capital available this cycle (all pending or on loan)")
        write_audit_log(cfg, {"mode": cfg.mode, "action": "hold", "reason": "no_idle_capital",
                               "reasoning": reasoning})
        save_state(state, cfg.state_path)
        return

    if cfg.mode == "frr":
        tenor = short_tenor
        log.info(f"[FRR mode] pegging to FRR, tenor={tenor}d (floats hourly)")
        rec = place_frr_tranche(client, cfg, state, now, live, lendable, tenor_rates[short_tenor], tenor)
        write_audit_log(cfg, {"mode": cfg.mode, "action": "place_frr", "amount": lendable, "tenor_days": tenor,
                               "gross_apr": gross_apr, "net_apr": net, "reasoning": reasoning,
                               "position_id": rec["position_id"]})
        save_state(state, cfg.state_path)
        return

    spike = compute_spike_signal(rate_history, cfg)
    placed_records = []

    if cfg.mode == "dave_fast":
        placed_records.append(place_tranche(client, cfg, state, now, live, lendable, tenor_rates[short_tenor], short_tenor))
        reasoning.append(f"Dave Fast: single tranche, most liquid tenor ({short_tenor}d)")
    elif cfg.mode == "barbell":
        long_tenor = max([t for t in tenor_rates if t != short_tenor and t <= 30], default=short_tenor)
        short_cap = lendable * cfg.barbell_short_fraction
        long_cap = lendable - short_cap
        reasoning.append(f"barbell: {cfg.barbell_short_fraction:.0%} @ {short_tenor}d / "
                          f"{1-cfg.barbell_short_fraction:.0%} @ {long_tenor}d")
        for amount, rate in build_tranches_for_tenor(short_cap, tenor_rates[short_tenor], short_tenor, cfg):
            placed_records.append(place_tranche(client, cfg, state, now, live, amount, rate, short_tenor, "[short]"))
        if long_tenor != short_tenor:
            for amount, rate in build_tranches_for_tenor(long_cap, tenor_rates[long_tenor], long_tenor, cfg):
                placed_records.append(place_tranche(client, cfg, state, now, live, amount, rate, long_tenor, "[long]"))
    else:  # custom / dave_high -- full adaptive multi-tenor allocation
        if cfg.mode == "dave_high" and spike:
            reserve_now = lendable * cfg.fbrr_reserve_fraction
            lendable -= reserve_now
            reasoning.append(f"spike-proxy fired -> reserving {reserve_now:,.2f} "
                              f"({cfg.fbrr_reserve_fraction:.0%}) for an anticipated rate increase")
        allocation = decide_tenor_allocation(tenor_rates, cfg)
        reasoning.append("tenor allocation: " + ", ".join(f"{t}d={w:.0%}" for t, w in sorted(allocation.items())))
        for tenor, weight in allocation.items():
            bucket_capital = lendable * weight
            if bucket_capital < BFX_MIN_ORDER_USD:
                continue
            for amount, rate in build_tranches_for_tenor(bucket_capital, tenor_rates[tenor], tenor, cfg):
                placed_records.append(place_tranche(client, cfg, state, now, live, amount, rate, tenor))

    log.info(f"Placed {len(placed_records)} tranche(s) across "
             f"{len(set(r['tenor_days'] for r in placed_records))} tenor(s) this cycle (status=pending until filled)")
    write_audit_log(cfg, {"mode": cfg.mode, "action": "place", "gross_apr": gross_apr, "net_apr": net,
                           "spike_signal": spike if cfg.mode != "dave_fast" else None,
                           "tranches": placed_records, "reasoning": reasoning,
                           "idle_principal_after": state.idle_principal, "idle_profit_after": state.idle_profit})
    save_state(state, cfg.state_path)
