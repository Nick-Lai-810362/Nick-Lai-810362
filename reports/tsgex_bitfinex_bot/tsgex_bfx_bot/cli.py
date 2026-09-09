"""
Command-line entry point. See the top-level tsgex_bitfinex_lending_bot.py
script and README.md for usage examples.
"""
import argparse
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from .client import BitfinexClient
from .config import StrategyConfig
from .constants import DEFAULT_MAX_WAIT_HOURS
from .governance import assert_minimal_permissions
from .ledger import (
    available_balance,
    contribute_principal,
    export_positions_csv,
    load_state,
    reconcile_matured_positions,
    save_state,
)
from .mock_client import MockBitfinexClient
from .runner import run_cycle

log = logging.getLogger("tsgex_bot")

MODE_CHOICES = ["dave_high", "dave_fast", "custom", "frr", "barbell"]


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__ or "TSGEX Bitfinex USD Margin Funding Automation Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--symbol", default="fUSD")
    ap.add_argument("--mode", choices=MODE_CHOICES, default="dave_high")
    ap.add_argument("--floor-rate", type=float, default=0.05)
    ap.add_argument("--reserved-amount", type=float, default=0.0)
    ap.add_argument("--term-premium-min-pp", type=float, default=0.02)
    ap.add_argument("--authorize-extreme-tenor", action="store_true")
    ap.add_argument("--barbell-short-fraction", type=float, default=0.5)
    ap.add_argument("--max-orders-per-cycle", type=int, default=400)
    ap.add_argument("--max-wait-multiplier", type=float, default=1.0,
                     help=f"Scales the default per-tenor max-wait-before-cancel thresholds "
                          f"({DEFAULT_MAX_WAIT_HOURS} hours) -- a disclosed heuristic, not measured "
                          f"queue-time data. >1 = more patient, <1 = more aggressive relisting.")
    ap.add_argument("--rate-drift-threshold-pp", type=float, default=0.01,
                     help="Cancel+relist a pending order if the live net-APR at its tenor has moved "
                          "away from its quoted rate by at least this much (0.01=1pp).")
    ap.add_argument("--order-visibility", choices=["standard", "hidden"], default="standard")
    ap.add_argument("--state-file", default="bfx_bot_state.json")
    ap.add_argument("--contribute", type=float, default=0.0)
    ap.add_argument("--audit-log", default="bfx_bot_audit_log.jsonl")
    ap.add_argument("--export-csv", default=None)
    ap.add_argument("--export-tenor", type=int, default=None)
    ap.add_argument("--export-start", default=None)
    ap.add_argument("--export-end", default=None)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--poll-interval", type=int, default=5)
    ap.add_argument("--mock-days-per-cycle", type=float, default=0)
    return ap


def config_from_args(args: argparse.Namespace) -> StrategyConfig:
    return StrategyConfig(
        symbol=args.symbol, mode=args.mode, floor_rate=args.floor_rate, reserved_amount=args.reserved_amount,
        term_premium_min_pp=args.term_premium_min_pp, authorize_extreme_tenor=args.authorize_extreme_tenor,
        barbell_short_fraction=args.barbell_short_fraction, max_orders_per_cycle=args.max_orders_per_cycle,
        max_wait_multiplier=args.max_wait_multiplier, rate_drift_threshold_pp=args.rate_drift_threshold_pp,
        order_visibility=args.order_visibility, state_path=args.state_file, audit_log_path=args.audit_log or None,
    )


def main(argv=None) -> None:
    args = build_arg_parser().parse_args(argv)
    cfg = config_from_args(args)

    state = load_state(cfg.state_path)
    if args.contribute:
        contribute_principal(state, args.contribute)
        log.info(f"Contributed {args.contribute:,.2f} new principal. "
                 f"Total principal contributed to date: {state.principal_contributed_total:,.2f}")
        save_state(state, cfg.state_path)

    if args.mock:
        client = MockBitfinexClient()
        log.info("Using MOCK client (synthetic funding book + simulated pending/fill lifecycle)")
    else:
        api_key = os.environ.get("BFX_API_KEY")
        api_secret = os.environ.get("BFX_API_SECRET")
        if args.live and not (api_key and api_secret):
            raise SystemExit("--live requires BFX_API_KEY and BFX_API_SECRET environment variables")
        client = BitfinexClient(api_key, api_secret)

    if args.live:
        assert_minimal_permissions(client)
        log.warning("LIVE MODE: real orders will be placed on Bitfinex.")
        log.warning("Reminder: capital must be in your Bitfinex FUNDING wallet, and Bitfinex's own "
                     "'Lending Pro' auto-lending must be OFF, or offers will collide.")
    else:
        log.info("DRY-RUN mode: no real orders will be placed.")

    log.info(f"mode={cfg.mode}  principal_contributed_total={state.principal_contributed_total:,.2f}  "
             f"idle_principal={state.idle_principal:,.2f}  idle_profit={state.idle_profit:,.2f}  "
             f"realized_profit_total={state.realized_profit_total:,.2f}")

    rate_history = []
    sim_now = datetime.now(timezone.utc)
    for i in range(args.cycles):
        log.info(f"--- cycle {i+1}/{args.cycles}  (clock: {sim_now.isoformat()}) ---")
        run_cycle(client, cfg, state, rate_history, sim_now, live=args.live)
        if i < args.cycles - 1:
            if args.mock_days_per_cycle:
                sim_now = sim_now + timedelta(days=args.mock_days_per_cycle)
            else:
                time.sleep(args.poll_interval)
                sim_now = datetime.now(timezone.utc)

    reconcile_matured_positions(state, sim_now)
    save_state(state, cfg.state_path)

    pending_n = sum(1 for p in state.positions if p.status == "pending")
    active_n = sum(1 for p in state.positions if p.status == "active")
    cancelled_n = sum(1 for p in state.positions if p.status == "cancelled")
    net_worth = available_balance(state) + sum(p.amount for p in state.positions if p.status in ("active", "pending"))
    log.info(f"--- final ledger: principal_contributed={state.principal_contributed_total:,.2f}  "
             f"realized_profit_total={state.realized_profit_total:,.2f}  "
             f"idle_principal={state.idle_principal:,.2f}  idle_profit={state.idle_profit:,.2f}  "
             f"pending={pending_n}  active={active_n}  cancelled_stale={cancelled_n}  "
             f"net_worth_estimate={net_worth:,.2f} ---")

    if args.export_csv:
        start_dt = datetime.fromisoformat(args.export_start).replace(tzinfo=timezone.utc) if args.export_start else None
        end_dt = datetime.fromisoformat(args.export_end).replace(tzinfo=timezone.utc) if args.export_end else None
        fee = cfg.platform_fee_hidden if cfg.order_visibility == "hidden" else cfg.platform_fee_standard
        n = export_positions_csv(state, args.export_csv, tenor_filter=args.export_tenor,
                                  start_dt=start_dt, end_dt=end_dt, platform_fee_for_display=fee)
        log.info(f"Exported {n} position(s) to {args.export_csv}")
