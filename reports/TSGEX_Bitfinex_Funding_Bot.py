#!/usr/bin/env python3
"""
TSGEX Bitfinex USD Margin Funding Automation Bot (v5 -- pending/fill tracking + stale-order cancel-relist)
==============================================================================================================

WHAT CHANGED IN v5 AND WHY
-----------------------------
Two follow-up questions from the user drove this revision:

  6. PENDING VS FILLED, AND CANCEL+RELIST STALE ORDERS.
     Every prior version treated a submitted order as INSTANTLY earning
     interest from the moment it was placed. That's wrong: a real Bitfinex
     funding offer sits UNFILLED in the book until a borrower actually takes
     it (in whole or in part -- see v4 finding #4), which can take anywhere
     from seconds to... indefinitely, if the quoted rate isn't competitive.
     v5 splits the position lifecycle into pending -> active -> matured (or
     pending -> cancelled). A pending order is reconciled every cycle
     against the exchange's real open-offers list (client.get_active_
     funding_offers -- if the order is no longer there, it filled; the
     public API doesn't expose per-offer partial-fill amounts, so
     "disappeared from open offers" is the correct, and only available,
     fill signal). Two triggers cancel a still-pending order and
     IMMEDIATELY resubmit at the current rate (reconcile_pending_offers()):
       a. Waited too long: elapsed time since submission >=
          --max-wait-multiplier x a per-tenor default (DEFAULT_MAX_WAIT_HOURS
          = {2h:6, 7d:24, 30d:72, 120d:120}). These defaults are a DISCLOSED
          HEURISTIC, not measured data -- Bitfinex's REST API has no
          historical order-book endpoint, so actual fill-latency can't be
          measured retroactively the way the rate/tenor data could. They're
          set roughly proportional to tenor length and inversely to that
          bucket's real matching liquidity (2d/7d/30d volume shares of
          89.6%/4.5%/1.0% -- see v4 finding #1), i.e. a thinner market gets
          more patience before being called "stuck." Tune via
          --max-wait-multiplier once you have real fill-latency data from
          your own account's order history.
       b. Rate drifted: the live net-APR at that position's tenor has moved
          away from its own quoted rate by >= --rate-drift-threshold-pp
          (default 1 percentage point) in EITHER direction -- if the market
          moved up, the stale order is now underpriced (leaving return on
          the table); if the market moved down, the stale order was
          probably too aggressive to begin with (which is likely WHY it
          hasn't filled) and should be repriced to the current competitive
          rate to actually get matched.
     Pending capital is deducted from the idle pool at SUBMISSION time (not
     fill time) since that's when it's actually committed/locked in the
     funding wallet, matching real account behavior.
     Live-mode caveat: the exact response shape of Bitfinex's authenticated
     write endpoints (needed to extract the new offer's ID for later
     cancellation) has NOT been verified against a real API call in this
     sandbox (outbound network access to Bitfinex is blocked here -- see
     the collector script's docs for the same limitation). extract_offer_id()
     tries the documented notification-envelope shape defensively; if it's
     wrong, that specific position's offer_id stays None and it falls back
     to maturity-only tracking (safe, just not stale-cancellable) until you
     verify the real shape against your own key and adjust if needed.

  7. TRANCHE SIZE RECALIBRATED FROM MEDIAN TO P75 REAL TRADE SIZE.
     User asked directly: given no order-count limit exists and partial
     fills are supported, wouldn't ONE giant order be better? Answer: no --
     a single order commits 100% of that capital to one rate guess (either
     a large enough counterparty appears soon, which the real data shows is
     rare -- only one $1.18M trade in the ~10,000-row recent sample, vs a
     $500 median -- or it sits earning nothing while it waits), whereas the
     inverted-pyramid ladder diversifies EXECUTION/rate risk the same way
     it always did; that logic doesn't depend on any order-count ceiling.
     But going the other way -- v4's default of the per-tenor MEDIAN real
     trade size ($700/2d, 227 tranches on a NT$5M/~USD158,730 position) --
     is also not obviously optimal now that pending orders need per-cycle
     monitoring and can trigger cancel+relist churn: more, smaller tranches
     mean more entities to track, more chances to hit a stale-order cancel,
     and (in --live) more submitted/cancelled API calls. v5 moves the
     default to each tenor's P75 real trade size instead ($825/2d, $574/7d,
     $491/30d -- still comfortably below the thin P90/P99 tail, so fill
     probability isn't meaningfully worse than the median target), cutting
     the NT$5M/2d-bucket case from 227 tranches to ~192 -- a modest,
     defensible reduction in operational overhead without reintroducing the
     "too few, too large" problem the v4 calibration fixed in the first
     place. See TENOR_TYPICAL_ORDER_SIZE.

WHAT v4 CHANGED (kept from the prior revision; see git history for the full
detailed writeup): real-data-grounded TARGET_TENORS=(2,7,30) replacing a
static ladder, decide_tenor_allocation() reading the LIVE book every cycle
instead of a fixed lookup table, the principal/profit ledger (BotState/
Position) with the tag propagating through re-lending, --export-csv.

WHAT IS STILL NOT REPRODUCED
-------------------------------
Fuly's actual FBRR forecasting MODEL remains undisclosed and unreproduced
(only the documented reserve-capital BEHAVIOR is approximated, via the same
disclosed spike-proxy heuristic as before). All empirical numbers above are
dated point-in-time reads of the market (2026-09) -- refresh periodically
via TSGEX_Bitfinex_Funding_History_Collector.py, don't treat as permanent.

SAFETY DEFAULTS (unchanged)
------------------------------
- dry-run by default; --live requires real credentials via env vars
- refuses to run live if the API key has withdrawal/transfer scope
- --mock mode: synthetic funding book AND a simulated pending-offer/fill
  lifecycle (per-tenor fill probability each cycle), so the new cancel+
  relist logic can be exercised meaningfully with zero network access

SETTING UP A REAL API KEY
---------------------------
1. Bitfinex -> API Keys -> Create New Key.
2. Enable ONLY "Margin Funding" (read + write/orders). Do NOT enable
   "Withdraw" or "Transfer" under any circumstance.
3. Move the capital you want to lend into your Bitfinex FUNDING wallet
   (not the Exchange wallet) -- this bot only sees/acts on funding balance.
4. If Bitfinex's own built-in "Lending Pro" auto-lending is on, turn it OFF
   first -- running two auto-lenders against the same balance causes
   duplicate/conflicting offers.
5. Optionally IP-restrict the key.
6. Export credentials as env vars (never pass them on the CLI):
     export BFX_API_KEY=...
     export BFX_API_SECRET=...

USAGE EXAMPLES
--------------
  # First-time setup: contribute principal, then run a demo with the clock
  # fast-forwarded so positions actually fill/mature within a short test
  python tsgex_bitfinex_lending_bot.py --mock --contribute 158730 --mode dave_high \\
      --cycles 10 --mock-days-per-cycle 3

  # Real dry-run against live market data (places no orders), needs network
  python tsgex_bitfinex_lending_bot.py --contribute 158730 --mode barbell

  # Export the full position history (principal/profit split) to CSV
  python tsgex_bitfinex_lending_bot.py --export-csv history.csv --export-tenor 30 \\
      --export-start 2026-01-01 --export-end 2026-12-31

  # Actually place live orders (only after reviewing dry-run output)
  python tsgex_bitfinex_lending_bot.py --live --mode dave_high

SOURCES
--------
  Real data: TSGEX_Bitfinex_Funding_History_Collector.py output (user-collected,
    2026-09-07: funding_candles_fUSD_p2/p30/p120.csv, funding_trades_fUSD.csv)
  https://docs.bitfinex.com/docs/requirements-and-limitations
  https://docs.bitfinex.com/reference/rest-auth-submit-funding-offer
  https://docs.bitfinex.com/reference/rest-auth-funding-offers
  https://support.bitfinex.com/hc/en-us/articles/213918949-What-is-the-minimum-offer-for-Funding
  https://support.bitfinex.com/hc/en-us/articles/214441185-What-is-Margin-Funding
  https://medium.com/@altinvestbot/how-bitfinex-matches-lending-funds-behind-the-scenes-of-the-p2p-funding-market-531e081fc34b
  https://blog.bitfinex.com/products/how-to-earn-with-margin-lending-on-bitfinex/
  (plus all v3 Fuly.ai sources -- see git history for the full list)
"""
import argparse
import hashlib
import hmac
import json
import logging
import math
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("tsgex_bot")

BFX_API_URL = "https://api.bitfinex.com"
BFX_MIN_ORDER_USD = 150.0

# Real, liquid tenor buckets per Bitfinex's own documentation and the real
# trade-size/volume evidence (see v4 docstring history). 120d excluded by default.
TARGET_TENORS = (2, 7, 30)
EXTREME_TENOR = 120

# Point-in-time (2026-09-07) empirical per-tenor typical order size, from the
# real fUSD trades sample: the P75 trade size for that tenor bucket (see v5
# finding #7 for why P75 rather than median). Disclosed as dated evidence,
# not a constant -- refresh by re-analyzing a fresh pull from the collector.
TENOR_TYPICAL_ORDER_SIZE = {2: 825.0, 7: 574.0, 30: 491.0, EXTREME_TENOR: 491.0}

SUBMIT_PACING_SEC = 1.0  # live-mode only; 1/sec = 60/min, safely inside Bitfinex's documented 10-90/min

# Disclosed heuristic (NOT measured -- see v5 finding #6), hours before a
# still-unfilled pending order is considered stale and cancelled+relisted.
DEFAULT_MAX_WAIT_HOURS = {2: 6.0, 7: 24.0, 30: 72.0, EXTREME_TENOR: 120.0}


# ---------------------------------------------------------------------------
# Strategy config
# ---------------------------------------------------------------------------
@dataclass
class StrategyConfig:
    symbol: str = "fUSD"
    mode: str = "dave_high"  # "dave_high" | "dave_fast" | "custom" | "frr" | "barbell"

    platform_fee_standard: float = 0.15
    platform_fee_hidden: float = 0.18
    order_visibility: str = "standard"  # "standard" | "hidden"

    floor_rate: float = 0.05          # net-of-fee APR floor; below this, hold and place nothing
    reserved_amount: float = 0.0      # capital always kept unlent

    term_premium_min_pp: float = 0.02
    authorize_extreme_tenor: bool = False
    barbell_short_fraction: float = 0.5

    # Safety bound on tranche count, NOT a Bitfinex-imposed limit (none is
    # published). High enough that a NT$5,000,000-scale account (~USD
    # 158,730) at the P75 calibration (~192 tranches @2d) is not truncated.
    max_orders_per_cycle: int = 400
    tranche_rate_step_apr: float = 0.01
    tranche_weight_base: float = 0.8
    tranche_weight_step: float = 0.2

    # Stale pending-order cancel+relist (v5 finding #6)
    max_wait_hours: dict = field(default_factory=lambda: dict(DEFAULT_MAX_WAIT_HOURS))
    max_wait_multiplier: float = 1.0
    rate_drift_threshold_pp: float = 0.01

    # FBRR / Dave-High reserve behavior: disclosed proxy signal, not Fuly's real model
    spike_fast_window: int = 6
    spike_slow_window: int = 24
    fbrr_reserve_fraction: float = 0.15

    state_path: str = "bfx_bot_state.json"
    audit_log_path: Optional[str] = "bfx_bot_audit_log.jsonl"
    poll_interval_sec: int = 300


def platform_fee(cfg: "StrategyConfig") -> float:
    return cfg.platform_fee_hidden if cfg.order_visibility == "hidden" else cfg.platform_fee_standard


def net_apr(gross_apr: float, cfg: "StrategyConfig") -> float:
    return gross_apr * (1 - platform_fee(cfg))


def write_audit_log(cfg: "StrategyConfig", record: dict):
    if not cfg.audit_log_path:
        return
    record = {"ts_utc": datetime.now(timezone.utc).isoformat(), **record}
    with open(cfg.audit_log_path, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Principal / profit ledger -- persistent across runs. Every dollar is
# tagged principal or profit; the tag propagates forward through re-lending
# so compounded profit-on-profit is still counted as profit.
#
# Position lifecycle: pending (submitted, capital committed, not yet
# earning) -> active (filled, tenor clock running) -> matured (settled) --
# or pending -> cancelled (stale order pulled, capital returned, zero
# interest, see reconcile_pending_offers()).
# ---------------------------------------------------------------------------
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
    positions: list = field(default_factory=list)  # list[Position], full history


def load_state(path: str) -> BotState:
    if not os.path.exists(path):
        return BotState()
    with open(path) as f:
        raw = json.load(f)
    raw["positions"] = [Position(**p) for p in raw.get("positions", [])]
    return BotState(**raw)


def save_state(state: BotState, path: str):
    with open(path, "w") as f:
        json.dump(asdict(state), f, ensure_ascii=False, indent=2)


def contribute_principal(state: BotState, amount: float):
    state.principal_contributed_total += amount
    state.idle_principal += amount


def reconcile_matured_positions(state: BotState, now: datetime) -> list:
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


def available_balance(state: BotState) -> float:
    return max(0.0, state.idle_principal + state.idle_profit)


def open_position(state: BotState, amount: float, daily_rate: float, tenor_days: int,
                   now: datetime, label: str = "", offer_id=None) -> Position:
    """Draws `amount` proportionally from the idle principal/profit pools at
    SUBMISSION time (capital is committed the moment an offer is placed,
    even before it's matched) and creates a new PENDING position."""
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


def mark_filled(position: Position, now: datetime):
    position.status = "active"
    position.filled_ts = now.isoformat()
    position.maturity_ts = (now + timedelta(days=position.tenor_days)).isoformat()


def cancel_position(state: BotState, position: Position, now: datetime):
    """Stale/unfilled order pulled: capital returns to the idle pools
    unchanged (zero interest -- it never earned anything)."""
    state.idle_principal += position.principal_component
    state.idle_profit += position.profit_component
    position.status = "cancelled"
    position.matured_ts = now.isoformat()
    position.interest_earned = 0.0


def export_positions_csv(state: BotState, path: str, tenor_filter: Optional[int] = None,
                          start_dt: Optional[datetime] = None, end_dt: Optional[datetime] = None):
    import csv
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
        w.writerow(["id", "status", "label", "tenor_days", "amount", "principal_component",
                    "profit_component", "daily_rate", "gross_apr", "net_apr", "placed_ts", "filled_ts",
                    "maturity_ts", "matured_ts", "interest_earned"])
        for p in rows:
            gross = p.daily_rate * 365
            w.writerow([p.id, p.status, p.label, p.tenor_days, f"{p.amount:.2f}",
                        f"{p.principal_component:.2f}", f"{p.profit_component:.2f}", p.daily_rate,
                        f"{gross:.4f}", f"{gross*0.85:.4f}", p.placed_ts, p.filled_ts or "",
                        p.maturity_ts or "", p.matured_ts or "",
                        f"{p.interest_earned:.2f}" if p.interest_earned is not None else ""])
    return len(rows)


# ---------------------------------------------------------------------------
# Bitfinex REST client
# ---------------------------------------------------------------------------
class BitfinexClient:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret

    def get_funding_book(self, symbol: str, precision: str = "P0", length: int = 100):
        url = f"{BFX_API_URL}/v2/book/{symbol}/{precision}?len={length}"
        return self._get(url)

    def get_ticker(self, symbol: str):
        return self._get(f"{BFX_API_URL}/v2/ticker/{symbol}")

    def _get(self, url: str):
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def _signed_post(self, endpoint: str, body: dict):
        if not self.api_key or not self.api_secret:
            raise RuntimeError("API key/secret required for authenticated endpoints")
        nonce = str(int(time.time() * 1_000_000))
        path = f"/api/v2/{endpoint}"
        body_json = json.dumps(body)
        sig = hmac.new(self.api_secret.encode(), f"{path}{nonce}{body_json}".encode(), hashlib.sha384).hexdigest()
        headers = {"Content-Type": "application/json", "bfx-nonce": nonce,
                   "bfx-apikey": self.api_key, "bfx-signature": sig}
        req = urllib.request.Request(f"{BFX_API_URL}{path}", data=body_json.encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def get_permissions(self):
        return self._signed_post("auth/r/permissions", {})

    def get_active_funding_offers(self, symbol: str):
        return self._signed_post(f"auth/r/funding/offers/{symbol}", {})

    def submit_funding_offer(self, symbol: str, amount: float, daily_rate: float, period_days: int):
        body = {"type": "LIMIT", "symbol": symbol, "amount": str(amount), "rate": str(daily_rate),
                "period": period_days, "flags": 0}
        return self._signed_post("auth/w/funding/offer/submit", body)

    def submit_frr_offer(self, symbol: str, amount: float, period_days: int):
        return self.submit_funding_offer(symbol, amount, 0, period_days)

    def cancel_funding_offer(self, offer_id):
        return self._signed_post("auth/w/funding/offer/cancel", {"id": offer_id})


def extract_offer_id(resp):
    """Best-effort extraction of a new offer's ID from a submit response.
    Mock client returns the raw offer list ([ID, ...]) directly. Real
    Bitfinex wraps write-endpoint responses in a notification envelope
    ([MTS, TYPE, MESSAGE_ID, null, [offer_data...], CODE, STATUS, TEXT]) per
    its documented convention -- offer_data[0] is the ID. NOT verified
    against a live call in this sandbox (network egress to Bitfinex is
    blocked here); if the real shape differs, this returns None and that
    position's offer_id stays unset (safe fallback: maturity-only tracking,
    just not stale-cancellable) -- verify against your own key before
    relying on this for live cancel+relist."""
    try:
        if isinstance(resp, list) and len(resp) > 0:
            if not isinstance(resp[0], list):
                return resp[0]  # mock: raw offer list, ID first
            if len(resp) >= 5 and isinstance(resp[4], list) and len(resp[4]) > 0:
                return resp[4][0]  # live: notification envelope
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Mock client -- synthetic funding book shaped to match the REAL observed
# liquidity concentration, PLUS a simulated pending-offer fill lifecycle so
# --mock can meaningfully exercise reconcile_pending_offers(): each cycle,
# every still-open mock offer independently rolls a per-tenor fill chance
# (shorter/more liquid tenors fill faster), simulating real partial-fill-
# over-time behavior without needing live network access.
# ---------------------------------------------------------------------------
class MockBitfinexClient(BitfinexClient):
    FILL_PROB_PER_CYCLE = {2: 0.55, 7: 0.35, 30: 0.15, EXTREME_TENOR: 0.05}

    def __init__(self):
        super().__init__()
        import random
        self._rng = random.Random(42)
        self._base_daily_rate_2d = 0.07 / 365
        self._offers = []
        self._next_offer_id = 1000

    def get_funding_book(self, symbol: str, precision: str = "P0", length: int = 100):
        self._base_daily_rate_2d = max(0.00003, self._base_daily_rate_2d + self._rng.uniform(-0.000015, 0.000015))
        premium_pp = self._rng.choice([0.0, 0.01, 0.02, 0.04])
        book = []
        for tenor, weight in [(2, 40), (7, 8), (30, 3), (120, 1)]:
            for i in range(weight):
                if tenor == 2:
                    rate = self._base_daily_rate_2d * (1 + i * 0.01)
                else:
                    extra = (premium_pp if tenor in (30, 120) else premium_pp * 0.4) / 365
                    rate = self._base_daily_rate_2d + extra + self._base_daily_rate_2d * i * 0.01
                amount = round(self._rng.uniform(150, 5000), 2)
                book.append([rate, tenor, 1, amount])
        return book

    def get_permissions(self):
        return [["funding", 0, 1, 1], ["orders", 0, 1, 1], ["wallets", 0, 1, 0]]

    def get_active_funding_offers(self, symbol: str):
        """Simulates fills: each still-open offer independently rolls a
        per-tenor probability of having been matched since the last check."""
        still_open = []
        for o in self._offers:
            period = o[15]
            prob = self.FILL_PROB_PER_CYCLE.get(period, 0.10)
            if self._rng.random() < prob:
                continue  # simulated fill
            still_open.append(o)
        self._offers = still_open
        return still_open

    def submit_funding_offer(self, symbol, amount, daily_rate, period_days):
        offer = [self._next_offer_id, symbol, int(time.time() * 1000), None, amount, amount,
                 "LIMIT", None, None, 0, "ACTIVE", None, None, None, daily_rate, period_days]
        self._offers.append(offer)
        self._next_offer_id += 1
        return offer

    def cancel_funding_offer(self, offer_id):
        self._offers = [o for o in self._offers if str(o[0]) != str(offer_id)]
        return {"status": "cancelled", "id": offer_id}


# ---------------------------------------------------------------------------
# Governance guard
# ---------------------------------------------------------------------------
def assert_minimal_permissions(client: BitfinexClient):
    perms = client.get_permissions()
    perm_map = {row[0]: row for row in perms}
    withdraw_perm = perm_map.get("wallets") or perm_map.get("withdraw")
    if withdraw_perm and len(withdraw_perm) >= 4 and int(withdraw_perm[3]) == 1:
        raise RuntimeError(
            "REFUSING TO RUN: this API key has withdrawal/transfer permission. "
            "Both Fuly.ai's own setup guides and TSGEX governance policy require "
            "funding-only keys with withdrawal explicitly disabled. Create a new restricted key."
        )
    log.info("Permission check passed: key has no withdrawal/transfer scope.")


# ---------------------------------------------------------------------------
# Live-book-driven tenor allocation
# ---------------------------------------------------------------------------
def best_rate_by_tenor(book: list, target_tenors=TARGET_TENORS) -> dict:
    out = {}
    for row in book:
        rate, period = row[0], row[1]
        if period in target_tenors:
            if period not in out or rate < out[period]:
                out[period] = rate
    return out


def decide_tenor_allocation(tenor_rates: dict, cfg: StrategyConfig) -> dict:
    available = sorted(t for t in tenor_rates if t in TARGET_TENORS or
                        (t == EXTREME_TENOR and cfg.authorize_extreme_tenor))
    if not available:
        return {}
    short = min(available)
    short_net = net_apr(tenor_rates[short] * 365, cfg)

    alloc = {short: 1.0}
    for t in available:
        if t == short:
            continue
        t_net = net_apr(tenor_rates[t] * 365, cfg)
        premium_pp = t_net - short_net
        if premium_pp >= cfg.term_premium_min_pp:
            shift = min(0.7, 0.25 + (premium_pp - cfg.term_premium_min_pp) * 10)
            alloc[short] -= shift
            alloc[t] = alloc.get(t, 0.0) + shift
    alloc[short] = max(0.0, alloc[short])
    total = sum(alloc.values())
    return {t: w / total for t, w in alloc.items() if w > 1e-9}


def compute_spike_signal(rate_history: list, cfg: StrategyConfig) -> bool:
    if len(rate_history) < cfg.spike_slow_window:
        return False
    fast = sum(rate_history[-cfg.spike_fast_window:]) / cfg.spike_fast_window
    slow = sum(rate_history[-cfg.spike_slow_window:]) / cfg.spike_slow_window
    return fast > slow


def build_tranches_for_tenor(capital: float, best_daily_rate: float, tenor_days: int, cfg: StrategyConfig):
    per_order = TENOR_TYPICAL_ORDER_SIZE.get(tenor_days, 500.0)
    n = max(1, min(cfg.max_orders_per_cycle, math.ceil(capital / per_order)))
    rates = [best_daily_rate + i * (cfg.tranche_rate_step_apr / 365) for i in range(n)]
    weights = [cfg.tranche_weight_base + cfg.tranche_weight_step * i for i in range(n)]
    total_weight = sum(weights)
    return [(capital * w / total_weight, r) for w, r in zip(weights, rates)]


def _place(client: BitfinexClient, cfg: StrategyConfig, state: BotState, now: datetime,
           live: bool, amount: float, rate: float, tenor: int, label: str = "") -> dict:
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


def reconcile_pending_offers(client: BitfinexClient, cfg: StrategyConfig, state: BotState,
                              tenor_rates: dict, now: datetime, live: bool) -> list:
    """Checks every still-pending position against the exchange's real open-
    offers list (fill signal: it's no longer there -- the public API has no
    per-offer partial-fill amount, so this is the correct and only available
    signal). Still-open positions are cancelled + immediately re-listed at
    the current rate if they've waited too long or the market has drifted
    away from their quoted rate (see docstring finding #6)."""
    is_mock = isinstance(client, MockBitfinexClient)
    if not (live or is_mock):
        return []  # plain dry-run against the real client: nothing was ever really submitted

    open_ids = {str(o[0]) for o in client.get_active_funding_offers(cfg.symbol)}
    events = []
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
                new_rec = _place(client, cfg, state, now, live, p.amount, current_rate, p.tenor_days,
                                  label=(p.label + "+relist"))
                events.append({"event": "relisted", **new_rec})
    return events


# ---------------------------------------------------------------------------
# Main strategy loop
# ---------------------------------------------------------------------------
def run_cycle(client: BitfinexClient, cfg: StrategyConfig, state: BotState, rate_history: list,
              now: datetime, live: bool):
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
        is_mock = isinstance(client, MockBitfinexClient)
        offer_id = None
        if live or is_mock:
            resp = client.submit_frr_offer(cfg.symbol, lendable, tenor)
            offer_id = extract_offer_id(resp)
            if live:
                time.sleep(SUBMIT_PACING_SEC)
        if not live:
            log.info(f"  [DRY-RUN] would place FRR-pegged offer: amount={lendable:,.2f}  period={tenor}d")
        # rate=0 is the live API's "peg to FRR" instruction; the ledger must
        # not record 0% accrual or this position would earn nothing, so it's
        # booked against the observed short-tenor rate as a disclosed proxy.
        pos = open_position(state, lendable, tenor_rates[short_tenor], tenor, now, label="frr", offer_id=offer_id)
        write_audit_log(cfg, {"mode": cfg.mode, "action": "place_frr", "amount": lendable, "tenor_days": tenor,
                               "gross_apr": gross_apr, "net_apr": net, "reasoning": reasoning,
                               "position_id": pos.id})
        save_state(state, cfg.state_path)
        return

    spike = compute_spike_signal(rate_history, cfg)
    placed_records = []

    if cfg.mode == "dave_fast":
        placed_records.append(_place(client, cfg, state, now, live, lendable, tenor_rates[short_tenor], short_tenor))
        reasoning.append(f"Dave Fast: single tranche, most liquid tenor ({short_tenor}d)")
    elif cfg.mode == "barbell":
        long_tenor = max([t for t in tenor_rates if t != short_tenor and t <= 30], default=short_tenor)
        short_cap = lendable * cfg.barbell_short_fraction
        long_cap = lendable - short_cap
        reasoning.append(f"barbell: {cfg.barbell_short_fraction:.0%} @ {short_tenor}d / "
                          f"{1-cfg.barbell_short_fraction:.0%} @ {long_tenor}d")
        for amount, rate in build_tranches_for_tenor(short_cap, tenor_rates[short_tenor], short_tenor, cfg):
            placed_records.append(_place(client, cfg, state, now, live, amount, rate, short_tenor, "[short]"))
        if long_tenor != short_tenor:
            for amount, rate in build_tranches_for_tenor(long_cap, tenor_rates[long_tenor], long_tenor, cfg):
                placed_records.append(_place(client, cfg, state, now, live, amount, rate, long_tenor, "[long]"))
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
                placed_records.append(_place(client, cfg, state, now, live, amount, rate, tenor))

    log.info(f"Placed {len(placed_records)} tranche(s) across "
             f"{len(set(r['tenor_days'] for r in placed_records))} tenor(s) this cycle (status=pending until filled)")
    write_audit_log(cfg, {"mode": cfg.mode, "action": "place", "gross_apr": gross_apr, "net_apr": net,
                           "spike_signal": spike if cfg.mode != "dave_fast" else None,
                           "tranches": placed_records, "reasoning": reasoning,
                           "idle_principal_after": state.idle_principal, "idle_profit_after": state.idle_profit})
    save_state(state, cfg.state_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="fUSD")
    ap.add_argument("--mode", choices=["dave_high", "dave_fast", "custom", "frr", "barbell"], default="dave_high")
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
    args = ap.parse_args()

    cfg = StrategyConfig(
        symbol=args.symbol, mode=args.mode, floor_rate=args.floor_rate, reserved_amount=args.reserved_amount,
        term_premium_min_pp=args.term_premium_min_pp, authorize_extreme_tenor=args.authorize_extreme_tenor,
        barbell_short_fraction=args.barbell_short_fraction, max_orders_per_cycle=args.max_orders_per_cycle,
        max_wait_multiplier=args.max_wait_multiplier, rate_drift_threshold_pp=args.rate_drift_threshold_pp,
        order_visibility=args.order_visibility, state_path=args.state_file, audit_log_path=args.audit_log or None,
    )

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
        n = export_positions_csv(state, args.export_csv, tenor_filter=args.export_tenor,
                                  start_dt=start_dt, end_dt=end_dt)
        log.info(f"Exported {n} position(s) to {args.export_csv}")


if __name__ == "__main__":
    main()
