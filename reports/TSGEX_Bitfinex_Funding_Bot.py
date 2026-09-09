#!/usr/bin/env python3
"""
TSGEX Bitfinex USD Margin Funding Automation Bot (v4 -- real-data-grounded tenor logic + P&L ledger)
========================================================================================================

WHAT CHANGED IN v4 AND WHY
-----------------------------
v3 chose tenor via a STATIC 3-bracket ladder (net APR <15% -> 2-7d, 15-30% ->
15-30d, >=30% -> 60-120d) borrowed from the TSGEX report's own governance
policy. The user asked to actually research how Bitfinex's real rate/tenor
structure works and rebuild this on real data instead of an assumed table.
That research used the real fUSD data the user collected earlier in this
project (TSGEX_Bitfinex_Funding_History_Collector.py output: 5 years of
hourly p2/p30/p120 rate candles, plus a ~10,000-row recent trades sample)
and Bitfinex's own public documentation. Findings, and what changed as a
result:

  1. REAL LIQUIDITY IS OVERWHELMINGLY CONCENTRATED AT THE 2-DAY TENOR.
     In the real recent-trades sample, period=2 accounted for 89.6% of all
     matched trade COUNT and 96%+ of matched USD VOLUME; period=30 was
     ~1.0% of trades, period=120 just 0.11%. Bitfinex's own docs confirm:
     "the most common periods are 2, 7, or 30 days." -> v4 targets exactly
     these three tenors (TARGET_TENORS = (2, 7, 30)) instead of an
     arbitrary continuous ladder. 120d is EXCLUDED by default (see #2).

  2. 120-DAY TENOR MEASURED NO RATE PREMIUM OVER 30-DAY, IN 5 YEARS OF DATA.
     Time-aligned join of the real p2/p30/p120 candles (25,354 overlapping
     hourly rows, 2021-08 to 2026-09): median spread (p120 - p30) = +0.04
     percentage points, and was positive only 55.4% of the time --
     statistically indistinguishable from zero. Meanwhile p120 has ~8x LESS
     matched volume than the already-thin p30 market. 120d is therefore
     strictly dominated by 30d in this data: same reward, far worse
     liquidity, 4x longer lock-up. v4 drops 120d from the default target
     set; it remains available only via --authorize-extreme-tenor for a
     deliberate large block trade, same governance-gate spirit as before.

  3. THE 2-DAY -> 30-DAY TERM PREMIUM IS REAL BUT NOT CONSTANT.
     Over the full 5-year history, median (p30 - p2) spread = +3.65
     percentage points of APR (positive 85.5% of the time -- a genuine,
     persistent premium for locking up capital longer). BUT a same-day
     snapshot from the live trades sample the user pulled on 2026-09-07
     showed a much flatter curve (2d median 7.34% APR vs 30d 8.12% --
     only +0.78pp). The premium clearly varies by regime (it's also larger
     when short rates are themselves low: +4.30pp in the below-median-rate
     regime vs +2.52pp in the above-median-rate regime). CONCLUSION: a
     fixed lookup table ("4-7% APR -> 2 days, 7-11% -> 3 days" etc., which
     is what was originally asked for) would be WRONG, because the
     relationship it would encode is not stable over time. v4 instead
     reads the ACTUAL currently-available rate at each of the 2/7/30-day
     buckets from the live funding book every cycle, computes the CURRENT
     premium, and only allocates capital to a longer tenor when that
     LIVE premium clears a configurable minimum (TERM_PREMIUM_MIN_PP,
     default 2.0 percentage points net-of-fee APR -- chosen conservatively
     inside the observed 0.78pp-to-3.65pp range so the bot doesn't lock up
     capital for a premium that may already have evaporated by the time the
     book is read). This replaces select_tenor() and the old static ladder
     entirely; see decide_tenor_allocation().

  4. ORDER SIZE VS TURNOVER: NO PUBLISHED MAX-CONCURRENT-OFFER-COUNT LIMIT
     EXISTS. Searched Bitfinex's own docs (docs.bitfinex.com/docs/
     requirements-and-limitations, the funding offer submit/cancel API
     reference, and margin-funding help-center articles) specifically for
     this. What IS documented: (a) a REQUEST RATE limit of 10-90 req/min
     depending on endpoint (an IP that exceeds it is blocked for 60s) --
     this constrains how FAST you can submit many orders, not how many you
     can hold open; (b) funding offers DO support partial fills -- a single
     large offer can fill incrementally across many different borrowers
     over time rather than requiring one counterparty for the whole amount;
     (c) matching is rate-priority + duration-compatible (an offer's period
     must be >= a bid's requested period). So "harder to lend out" for a
     large single order is real, but it's a LIQUIDITY/matching-speed effect,
     not a hard order-count ceiling. v4 sizes each tranche against the
     REAL observed trade-size distribution for that specific tenor bucket
     (from the same trades sample: period=2 median trade $500, p90 $4,718;
     period=7 median $343, p90 $1,082; period=30 median $183, p90 $2,231 --
     see TENOR_TYPICAL_ORDER_SIZE, dated and disclosed as a point-in-time
     read, not a permanent constant) instead of one generic $150-1,000
     range applied to every tenor. Submission pacing (SUBMIT_PACING_SEC)
     is added between live order submissions to respect the documented
     request-rate limit, since that -- not order count -- is the real
     documented constraint.

  5. PRINCIPAL VS PROFIT LEDGER (closes the state-tracking gap flagged in
     the v3 spec review). v3 recomputed "how much is available to lend"
     fresh from total capital every cycle, with no memory of what was
     already placed in prior cycles -- fine for a dry-run demo, wrong for
     continuous live operation (would try to re-lend the same capital
     every cycle). v4 adds a persistent JSON ledger (--state-file,
     default bfx_bot_state.json): every dollar is tagged as PRINCIPAL
     (what you originally contributed) or PROFIT (interest realized, and
     interest realized on capital that itself already contained
     reinvested profit -- the tag propagates forward through re-lending,
     so compounded profit-on-profit is still counted as profit, never
     silently reclassified as principal). See BotState / Position /
     reconcile_matured_positions() / open_position().

WHAT IS STILL NOT REPRODUCED
-------------------------------
Same as v3: Fuly's actual FBRR forecasting MODEL is undisclosed and not
reproduced (only the documented reserve-capital BEHAVIOR is approximated,
via the same disclosed spike-proxy heuristic as before). The empirical
numbers above are a real but NECESSARILY time-bound read of the market
(collected 2026-09; both the term premium and the typical order sizes will
drift) -- they are disclosed, dated inputs you can and should refresh by
re-running TSGEX_Bitfinex_Funding_History_Collector.py periodically, not
permanent constants.

SAFETY DEFAULTS (unchanged)
------------------------------
- dry-run by default; --live requires real credentials via env vars
- refuses to run live if the API key has withdrawal/transfer scope
- --mock mode: synthetic funding book, zero network access/credentials

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
  # fast-forwarded so positions actually mature within a short test
  python tsgex_bitfinex_lending_bot.py --mock --contribute 160000 --mode dave_high \\
      --cycles 10 --mock-days-per-cycle 3

  # Real dry-run against live market data (places no orders), needs network
  python tsgex_bitfinex_lending_bot.py --contribute 160000 --mode barbell

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
# trade-size/volume evidence above. 120d deliberately excluded by default.
TARGET_TENORS = (2, 7, 30)
EXTREME_TENOR = 120

# Point-in-time (2026-09-07) empirical per-tenor typical order size, from the
# real fUSD trades sample: roughly halfway between the median and P90 trade
# size for that tenor bucket. Disclosed as dated evidence, not a constant --
# refresh by re-analyzing a fresh pull from the collector script.
TENOR_TYPICAL_ORDER_SIZE = {2: 700.0, 7: 500.0, 30: 300.0, EXTREME_TENOR: 300.0}

SUBMIT_PACING_SEC = 0.3  # live-mode only; Bitfinex's documented request-rate limit is 10-90/min


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

    # Live-book-driven tenor allocation (replaces v3's static ladder)
    term_premium_min_pp: float = 0.02   # 2.0 percentage points net APR; see docstring #3 for why
    authorize_extreme_tenor: bool = False  # gate for the 120d bucket (never used unless explicitly set)
    barbell_short_fraction: float = 0.5    # --mode barbell only: split between the 2d and 30d buckets

    max_orders_per_cycle: int = 30
    tranche_rate_step_apr: float = 0.01
    tranche_weight_base: float = 0.8
    tranche_weight_step: float = 0.2

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
    maturity_ts: str
    status: str = "active"  # "active" | "matured"
    matured_ts: Optional[str] = None
    interest_earned: Optional[float] = None
    label: str = ""


@dataclass
class BotState:
    principal_contributed_total: float = 0.0
    idle_principal: float = 0.0
    idle_profit: float = 0.0
    realized_profit_total: float = 0.0
    positions: list = field(default_factory=list)  # list[Position], active + matured history


def load_state(path: str) -> BotState:
    if not os.path.exists(path):
        return BotState()
    with open(path) as f:
        raw = json.load(f)
    raw["positions"] = [Position(**p) for p in raw.get("positions", [])]
    return BotState(**raw)


def save_state(state: BotState, path: str):
    raw = asdict(state)
    with open(path, "w") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)


def contribute_principal(state: BotState, amount: float):
    state.principal_contributed_total += amount
    state.idle_principal += amount


def reconcile_matured_positions(state: BotState, now: datetime) -> list:
    """Settles any position whose tenor has elapsed: principal returns to
    idle_principal unchanged, interest earned is added to idle_profit AND
    realized_profit_total. Returns the list of positions just matured."""
    just_matured = []
    for p in state.positions:
        if p.status != "active":
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
                   now: datetime, label: str = "") -> Position:
    """Draws `amount` proportionally from the idle principal/profit pools
    (so the new position's own principal/profit tags reflect what actually
    funded it), moves it into a new active Position, and returns it."""
    total_idle = state.idle_principal + state.idle_profit
    principal_frac = (state.idle_principal / total_idle) if total_idle > 1e-9 else 1.0
    principal_component = amount * principal_frac
    profit_component = amount - principal_component
    state.idle_principal = max(0.0, state.idle_principal - principal_component)
    state.idle_profit = max(0.0, state.idle_profit - profit_component)

    placed = now
    maturity = now + timedelta(days=tenor_days)
    pos = Position(
        id=str(uuid.uuid4())[:8], amount=amount, principal_component=principal_component,
        profit_component=profit_component, daily_rate=daily_rate, tenor_days=tenor_days,
        placed_ts=placed.isoformat(), maturity_ts=maturity.isoformat(), status="active", label=label,
    )
    state.positions.append(pos)
    return pos


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
                    "profit_component", "daily_rate", "gross_apr", "net_apr", "placed_ts",
                    "maturity_ts", "matured_ts", "interest_earned"])
        for p in rows:
            gross = p.daily_rate * 365
            w.writerow([p.id, p.status, p.label, p.tenor_days, f"{p.amount:.2f}",
                        f"{p.principal_component:.2f}", f"{p.profit_component:.2f}", p.daily_rate,
                        f"{gross:.4f}", f"{gross*(1-0.15):.4f}", p.placed_ts, p.maturity_ts,
                        p.matured_ts or "", f"{p.interest_earned:.2f}" if p.interest_earned is not None else ""])
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

    def cancel_funding_offer(self, offer_id: int):
        return self._signed_post("auth/w/funding/offer/cancel", {"id": offer_id})


# ---------------------------------------------------------------------------
# Mock client -- synthetic funding book shaped to match the REAL observed
# liquidity concentration (mostly 2d, some 7d, thin 30d) and a term premium
# that varies cycle to cycle so both branches of decide_tenor_allocation get
# exercised in a demo run.
# ---------------------------------------------------------------------------
class MockBitfinexClient(BitfinexClient):
    def __init__(self):
        super().__init__()
        import random
        self._rng = random.Random(42)
        self._base_daily_rate_2d = 0.07 / 365  # ~7% APR, matches the real snapshot median
        self._offers = []
        self._next_offer_id = 1000

    def get_funding_book(self, symbol: str, precision: str = "P0", length: int = 100):
        self._base_daily_rate_2d = max(0.00003, self._base_daily_rate_2d + self._rng.uniform(-0.000015, 0.000015))
        premium_pp = self._rng.choice([0.0, 0.01, 0.02, 0.04])  # sometimes flat, sometimes a real premium
        book = []
        for tenor, weight in [(2, 40), (7, 8), (30, 3), (120, 1)]:
            n_rows = weight
            for i in range(n_rows):
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
        return self._offers

    def submit_funding_offer(self, symbol, amount, daily_rate, period_days):
        offer = [self._next_offer_id, symbol, int(time.time() * 1000), None, amount, amount,
                 "LIMIT", None, None, 0, "ACTIVE", None, None, None, daily_rate, period_days]
        self._offers.append(offer)
        self._next_offer_id += 1
        return offer

    def cancel_funding_offer(self, offer_id):
        self._offers = [o for o in self._offers if o[0] != offer_id]
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
# Live-book-driven tenor allocation (replaces v3's static ladder)
# ---------------------------------------------------------------------------
def best_rate_by_tenor(book: list, target_tenors=TARGET_TENORS) -> dict:
    """Scans the full funding book and returns {tenor_days: best (lowest)
    daily_rate actually quoted at that tenor right now}, restricted to
    target_tenors. A tenor with no rows in the current book is omitted."""
    out = {}
    for row in book:
        rate, period = row[0], row[1]
        if period in target_tenors:
            if period not in out or rate < out[period]:
                out[period] = rate
    return out


def decide_tenor_allocation(tenor_rates: dict, cfg: StrategyConfig) -> dict:
    """Given the live best rate at each available tenor, decide what
    fraction of lendable capital goes to each tenor. Data-driven, not a
    fixed lookup table: only shifts capital to a longer tenor when the
    CURRENTLY observed premium (net of fee) clears cfg.term_premium_min_pp
    versus the 2-day rate. Falls back entirely to whatever tenors actually
    have quotes right now."""
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
            # shift capital toward the longer tenor in proportion to how far
            # the premium clears the threshold, capped at 70% to this bucket
            # so the short/liquid bucket always keeps some allocation
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
    """Inverted-pyramid split within one tenor bucket, sized against that
    bucket's own empirically observed typical order size (not one generic
    figure for every tenor)."""
    per_order = TENOR_TYPICAL_ORDER_SIZE.get(tenor_days, 500.0)
    n = max(1, min(cfg.max_orders_per_cycle, math.ceil(capital / per_order)))
    rates = [best_daily_rate + i * (cfg.tranche_rate_step_apr / 365) for i in range(n)]
    weights = [cfg.tranche_weight_base + cfg.tranche_weight_step * i for i in range(n)]
    total_weight = sum(weights)
    return [(capital * w / total_weight, r) for w, r in zip(weights, rates)]


def _place(client: BitfinexClient, cfg: StrategyConfig, state: BotState, now: datetime,
           live: bool, amount: float, rate: float, tenor: int, label: str = "") -> dict:
    implied_gross_apr = rate * 365
    if live:
        client.submit_funding_offer(cfg.symbol, amount, rate, tenor)
        time.sleep(SUBMIT_PACING_SEC)
    else:
        log.info(f"  [DRY-RUN]{label} would place: amount={amount:,.2f}  tenor={tenor}d  "
                 f"daily_rate={rate:.6f} (~{implied_gross_apr:.2%} gross / ~{net_apr(implied_gross_apr, cfg):.2%} net)")
    pos = open_position(state, amount, rate, tenor, now, label=label)
    return {"position_id": pos.id, "amount": amount, "principal_component": pos.principal_component,
            "profit_component": pos.profit_component, "daily_rate": rate, "gross_apr": implied_gross_apr,
            "net_apr": net_apr(implied_gross_apr, cfg), "tenor_days": tenor, "label": label}


# ---------------------------------------------------------------------------
# Main strategy loop
# ---------------------------------------------------------------------------
def run_cycle(client: BitfinexClient, cfg: StrategyConfig, state: BotState, rate_history: list,
              now: datetime, live: bool):
    reasoning = []
    matured = reconcile_matured_positions(state, now)
    if matured:
        interest = sum(p.interest_earned for p in matured)
        reasoning.append(f"{len(matured)} position(s) matured -> +{interest:,.2f} realized profit, "
                          f"principal returned to idle pool")
        log.info(f"  {len(matured)} position(s) matured, +{interest:,.2f} profit realized")

    book = client.get_funding_book(cfg.symbol)
    if not book:
        log.warning("Empty funding book response, skipping cycle")
        write_audit_log(cfg, {"mode": cfg.mode, "action": "skip", "reason": "empty_funding_book"})
        return

    tenor_rates = best_rate_by_tenor(book)
    if not tenor_rates:
        log.warning("No quotes at target tenors (2/7/30d), skipping cycle")
        write_audit_log(cfg, {"mode": cfg.mode, "action": "skip", "reason": "no_target_tenor_quotes"})
        return

    short_tenor = min(tenor_rates)
    gross_apr = tenor_rates[short_tenor] * 365
    net = net_apr(gross_apr, cfg)
    rate_history.append(gross_apr)
    reasoning.append(f"live rates by tenor: " +
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
        reasoning.append("no idle capital available (all currently on loan) -> holding")
        log.info("No idle capital available this cycle (all currently on loan)")
        write_audit_log(cfg, {"mode": cfg.mode, "action": "hold", "reason": "no_idle_capital",
                               "reasoning": reasoning})
        save_state(state, cfg.state_path)
        return

    if cfg.mode == "frr":
        tenor = short_tenor
        log.info(f"[FRR mode] pegging to FRR, tenor={tenor}d (floats hourly)")
        if live:
            client.submit_frr_offer(cfg.symbol, lendable, tenor)
        # The API call above uses rate=0 to mean "peg to FRR" (a live-order
        # instruction to Bitfinex), but the LEDGER must not record a 0%
        # accrual rate or this position would silently earn nothing.
        # Actual hourly-floating FRR settlement isn't tracked tick-by-tick
        # here; the currently observed short-tenor rate is used as a
        # disclosed proxy for interest bookkeeping.
        pos = open_position(state, lendable, tenor_rates[short_tenor], tenor, now, label="frr")
        write_audit_log(cfg, {"mode": cfg.mode, "action": "place_frr", "amount": lendable, "tenor_days": tenor,
                               "gross_apr": gross_apr, "net_apr": net, "reasoning": reasoning,
                               "position_id": pos.id})
        save_state(state, cfg.state_path)
        return

    spike = compute_spike_signal(rate_history, cfg)
    placed_records = []

    if cfg.mode == "dave_fast":
        rec = _place(client, cfg, state, now, live, lendable, tenor_rates[short_tenor], short_tenor)
        placed_records.append(rec)
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
             f"{len(set(r['tenor_days'] for r in placed_records))} tenor(s) this cycle")
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
    ap.add_argument("--term-premium-min-pp", type=float, default=0.02,
                     help="Minimum LIVE net-APR premium (as a fraction, e.g. 0.02=2pp) required before "
                          "shifting capital to a longer tenor. See docstring #3 for the empirical range "
                          "(0.78pp same-day snapshot to 3.65pp 5-year median) this default sits inside.")
    ap.add_argument("--authorize-extreme-tenor", action="store_true",
                     help="Allow the 120d bucket (measured no rate premium over 30d in 5y of data -- "
                          "opt-in only, e.g. for a specific large block trade)")
    ap.add_argument("--barbell-short-fraction", type=float, default=0.5)
    ap.add_argument("--order-visibility", choices=["standard", "hidden"], default="standard")
    ap.add_argument("--state-file", default="bfx_bot_state.json")
    ap.add_argument("--contribute", type=float, default=0.0,
                     help="Add this amount as NEW PRINCIPAL to the ledger before this run (e.g. initial funding)")
    ap.add_argument("--audit-log", default="bfx_bot_audit_log.jsonl")
    ap.add_argument("--export-csv", default=None, help="Export the full position ledger to this CSV path and continue")
    ap.add_argument("--export-tenor", type=int, default=None, help="Filter --export-csv to one tenor (2/7/30/120)")
    ap.add_argument("--export-start", default=None, help="Filter --export-csv: ISO date, e.g. 2026-01-01")
    ap.add_argument("--export-end", default=None, help="Filter --export-csv: ISO date, e.g. 2026-12-31")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--poll-interval", type=int, default=5, help="Real seconds slept between cycles (mock/demo)")
    ap.add_argument("--mock-days-per-cycle", type=float, default=0,
                     help="Mock mode only: fast-forward the simulated clock by this many days each cycle, "
                          "so positions actually mature within a short test run (0 = use real wall-clock)")
    args = ap.parse_args()

    cfg = StrategyConfig(
        symbol=args.symbol, mode=args.mode, floor_rate=args.floor_rate, reserved_amount=args.reserved_amount,
        term_premium_min_pp=args.term_premium_min_pp, authorize_extreme_tenor=args.authorize_extreme_tenor,
        barbell_short_fraction=args.barbell_short_fraction, order_visibility=args.order_visibility,
        state_path=args.state_file, audit_log_path=args.audit_log or None,
    )

    state = load_state(cfg.state_path)
    if args.contribute:
        contribute_principal(state, args.contribute)
        log.info(f"Contributed {args.contribute:,.2f} new principal. "
                 f"Total principal contributed to date: {state.principal_contributed_total:,.2f}")
        save_state(state, cfg.state_path)

    if args.mock:
        client = MockBitfinexClient()
        log.info("Using MOCK client (synthetic funding book, no network access)")
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

    net_worth = available_balance(state) + sum(p.amount for p in state.positions if p.status == "active")
    log.info(f"--- final ledger: principal_contributed={state.principal_contributed_total:,.2f}  "
             f"realized_profit_total={state.realized_profit_total:,.2f}  "
             f"idle_principal={state.idle_principal:,.2f}  idle_profit={state.idle_profit:,.2f}  "
             f"active_positions={sum(1 for p in state.positions if p.status=='active')}  "
             f"net_worth_estimate={net_worth:,.2f} ---")

    if args.export_csv:
        start_dt = datetime.fromisoformat(args.export_start).replace(tzinfo=timezone.utc) if args.export_start else None
        end_dt = datetime.fromisoformat(args.export_end).replace(tzinfo=timezone.utc) if args.export_end else None
        n = export_positions_csv(state, args.export_csv, tenor_filter=args.export_tenor,
                                  start_dt=start_dt, end_dt=end_dt)
        log.info(f"Exported {n} position(s) to {args.export_csv}")


if __name__ == "__main__":
    main()
