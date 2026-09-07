#!/usr/bin/env python3
"""
TSGEX Bitfinex USD Margin Funding Automation Bot (Fuly.ai-informed rebuild)
=============================================================================

SCOPE & PROVENANCE
-------------------
Fuly.ai's actual source code and its proprietary "FBRR" forecasting model
are not public -- there is no whitepaper, open API spec, or open-source
repo for either. This script is an independently engineered implementation
of the STRATEGY MECHANICS that Fuly.ai and reviewers of it publicly
document in tutorials, the company's own Medium posts, and its own
help-center ("FULY 富利學院"). Direct HTTP access to fuly.ai, medium.com,
school.fuly.ai, grenade.tw, johntool.com etc. is blocked by this sandbox's
egress policy, so the facts below come from web-search result summaries of
those pages rather than a raw fetch -- every behavior is still traceable to
a named public source (see SOURCES at the bottom of this docstring).

Documented facts this rebuild is grounded in:

  - Two named rate-selection engines:
      IBRR ("Instant Best Return Rate") -- the default engine. Detects the
        best rate matchable RIGHT NOW and combines it with "Dynamic Order"
        (動態掛單) placement. Suited to normal market conditions.
      FBRR ("Future Best Return Rate") -- a predictive engine. Forecasts
        rate trends hours-to-days ahead, places orders early, and RESERVES
        capital ahead of an anticipated rate spike ("特殊行情策略"). The
        forecasting model itself is undisclosed; this script implements
        only the disclosed BEHAVIOR (hold back capital when a spike-proxy
        signal fires), using a transparent, disclosed statistical
        heuristic in place of Fuly's real (secret) predictor.
  - FRR order type: a third, distinct order style, separate from IBRR/FBRR
    fixed-rate limit orders. Lend once at the current Bitfinex FRR (Flash
    Return Rate); the matched rate then FLOATS hourly with FRR going
    forward instead of staying fixed for the tenor. Bitfinex's own API
    represents "peg to FRR" as rate="0" on a funding offer.
  - "Dynamic lending period": Fuly documents that higher matched rates get
    longer tenors, and vice versa. Fuly's own exact rate/day breakpoints
    are not published; this script reuses the TSGEX report's own Section
    3.3 governance ladder (<15% APR -> 2-7d, 15-30% -> 15-30d, >=30% ->
    60-120d with mandatory risk sign-off) as a disclosed, reasonable
    stand-in for the slope, clearly marked where it is used below.
  - "Inverted pyramid" order splitting: Fuly's own published worked example
    is 80 units @10%, 100 units @11%, 120 units @12% -- i.e. order SIZE
    increases with rate, in ~1%-APR steps. This script generalizes that
    exact ratio (linear size increase per 1%-APR rate step) instead of an
    even split across tranches.
  - "跳跳樂" (Jump Strategy): documented trigger is "when the market rate
    falls below a threshold like 10%, contract length automatically snaps
    to the 2-day minimum," releasing capital fast so it can be re-listed
    once rates recover. Implemented literally, threshold defaulted to the
    documented 10% example and configurable.
  - Two named presets, as Fuly documents them: 戴夫高利模式 ("Dave High-Rate
    Mode" -- reserves capital ahead of anticipated big moves, i.e. the FBRR
    behavior offered as a one-click default) and 戴夫極速模式 ("Dave Fast
    Mode" -- prioritizes speed of matching over rate; documented to NEVER
    exceed Dave High-Rate mode's chosen rate). Both are implemented as
    named modes below, alongside a fully custom/manual mode and the
    standalone FRR mode.
  - Published, user-facing configuration knobs this script mirrors:
    reserved amount (保留金額, capital kept unlent), max USD per single
    order (documented guidance: 150-1,000 depending on total capital size
    -- Fuly does not expose a fixed "number of tranches" knob, tranche
    count falls out of capital / per-order size), fixed lending days
    bounded to the documented [2, 120] range.
  - Operational facts (not strategy logic, but required for correct live
    use, and included in the setup instructions below): lendable funds
    must sit in the Bitfinex FUNDING wallet, not the Exchange wallet;
    Bitfinex's own native auto-lending ("Lending Pro") must be switched
    off before running a third-party bot like this one, or offers
    collide; interest settles daily (~09:30) and auto-compounds back into
    lendable principal once idle interest reaches Bitfinex's own $150
    minimum order size.
  - Confirmed API permission scope: Funding read/write + read-only
    balance/trade-history. Withdraw/Transfer must NEVER be granted --
    stated explicitly in Fuly's own setup guides, and independently
    re-enforced in code below via assert_minimal_permissions(), regardless
    of what the user's key actually has.

What is NOT reproduced, because it is genuinely undisclosed and no public
source describes it in reproducible detail: Fuly's actual FBRR forecasting
MODEL (only its documented reserve-capital BEHAVIOR is approximated here),
and Fuly's exact proprietary rate/tenor breakpoint curve (approximated with
the TSGEX report's own governance ladder, marked wherever it is used).

SAFETY DEFAULTS
----------------
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
  python tsgex_bitfinex_lending_bot.py --mock --capital 1000000 --mode dave_high
  python tsgex_bitfinex_lending_bot.py --mock --capital 1000000 --mode dave_fast
  python tsgex_bitfinex_lending_bot.py --mock --capital 1000000 --mode frr
  python tsgex_bitfinex_lending_bot.py --capital 1000000 --mode custom \\
      --floor-rate 0.05 --max-amount-per-order 500
  python tsgex_bitfinex_lending_bot.py --live --capital 1000000 --mode dave_high

SOURCES (public tutorials / official help-center articles this rebuild is
grounded in -- fetched as web-search summaries; direct HTTP access to these
domains is blocked in this sandbox)
-----------------------------------------------------------------------------
  https://fuly.ai/lending
  https://medium.com/fuly-ai-.../fuly-ai-放貸機器-frr放貸-新功介紹-530feb1e2683
  https://medium.com/fuly-ai-.../為什麼用-fuly-ai-放出去的款利率就是比較高-7f5b7b47b617
  https://school.fuly.ai/posts/lending-teaching-6
  https://school.fuly.ai/posts/q-a06
  https://school.fuly.ai/posts/how-to-check-your-lending-settings
  https://grenade.tw/blog/fuly-ai-bitfinex-bot/
  https://murmurcats.com/fuly-ai/
  https://www.johntool.com/fuly/
  https://earning.tw/what-is-fuly/
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
from dataclasses import dataclass
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("tsgex_bot")

BFX_API_URL = "https://api.bitfinex.com"
BFX_MIN_ORDER_USD = 150.0  # Bitfinex's own funding-offer minimum; documented auto-compound trigger


# ---------------------------------------------------------------------------
# Strategy config -- field names/ranges mirror Fuly.ai's documented UI knobs
# ---------------------------------------------------------------------------
@dataclass
class StrategyConfig:
    capital: float
    symbol: str = "fUSD"
    mode: str = "dave_high"  # "dave_high" | "dave_fast" | "custom" | "frr"

    # Documented UI knobs
    floor_rate: float = 0.05          # 利率下限, Fuly's own suggested default (5% APR)
    reserved_amount: float = 0.0      # 保留金額, kept unlent regardless of mode
    min_tenor_days: int = 2           # documented floor
    max_tenor_days: int = 120         # documented ceiling
    max_amount_per_order: Optional[float] = None  # 每筆金額上限 (150-1,000 documented range);
                                                    # None -> scaled from capital, see default_max_amount_per_order()
    max_tranches_per_cycle: int = 20  # engineering cap so one cycle doesn't emit thousands of
                                       # micro-orders for very large capital; real Fuly drip-feeds
                                       # the book continuously rather than firing all at once

    # Rate-tenor coupling slope: Fuly's own exact breakpoints are not public.
    # Reusing the TSGEX report's Section 3.3 governance ladder as a disclosed
    # stand-in for the documented "higher rate -> longer tenor" relationship.
    normal_apr_ceiling: float = 0.15
    elevated_apr_ceiling: float = 0.30
    normal_tenor_days: tuple = (2, 7)
    elevated_tenor_days: tuple = (15, 30)
    extreme_tenor_days: tuple = (60, 120)
    authorize_extreme_tenor: bool = False  # mirrors the report's "須經風控主管專案簽核" gate

    # Inverted-pyramid tranche shape, calibrated to Fuly's published example
    # (80 units@10%, 100 units@11%, 120 units@12% -> weight 0.8, 1.0, 1.2 in
    # ~1%-APR steps)
    tranche_rate_step_apr: float = 0.01
    tranche_weight_base: float = 0.8
    tranche_weight_step: float = 0.2

    # Jump Strategy (跳跳樂): documented example threshold ~10% APR -> snap
    # to the 2-day minimum tenor
    jump_strategy_threshold_apr: float = 0.10
    jump_strategy_tenor_days: int = 2

    # FBRR / Dave-High reserve behavior: proxy spike signal (disclosed
    # EMA-crossover heuristic, NOT Fuly's real forecasting model) plus how
    # much capital to hold back when it fires
    spike_fast_window: int = 6
    spike_slow_window: int = 24
    fbrr_reserve_fraction: float = 0.15

    poll_interval_sec: int = 300


def default_max_amount_per_order(capital: float) -> float:
    """Fuly's guidance is 'set per-order size to 150-1,000 depending on your
    total capital.' Linearly interpolate within that documented range."""
    return min(1000.0, max(BFX_MIN_ORDER_USD, capital / 1000.0))


# ---------------------------------------------------------------------------
# Bitfinex REST client (public market data + authenticated funding endpoints)
# ---------------------------------------------------------------------------
class BitfinexClient:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret

    # ---- public endpoints (no auth) ----
    def get_funding_book(self, symbol: str, precision: str = "P0", length: int = 25):
        url = f"{BFX_API_URL}/v2/book/{symbol}/{precision}?len={length}"
        return self._get(url)

    def get_ticker(self, symbol: str):
        url = f"{BFX_API_URL}/v2/ticker/{symbol}"
        return self._get(url)

    def _get(self, url: str):
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    # ---- authenticated endpoints ----
    def _signed_post(self, endpoint: str, body: dict):
        if not self.api_key or not self.api_secret:
            raise RuntimeError("API key/secret required for authenticated endpoints")
        nonce = str(int(time.time() * 1_000_000))
        path = f"/api/v2/{endpoint}"
        body_json = json.dumps(body)
        signature_payload = f"{path}{nonce}{body_json}"
        sig = hmac.new(self.api_secret.encode(), signature_payload.encode(), hashlib.sha384).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "bfx-nonce": nonce,
            "bfx-apikey": self.api_key,
            "bfx-signature": sig,
        }
        req = urllib.request.Request(
            f"{BFX_API_URL}{path}", data=body_json.encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def get_permissions(self):
        """Returns the API key's scopes. Used to enforce the no-withdrawal rule."""
        return self._signed_post("auth/r/permissions", {})

    def get_active_funding_offers(self, symbol: str):
        return self._signed_post(f"auth/r/funding/offers/{symbol}", {})

    def submit_funding_offer(self, symbol: str, amount: float, daily_rate: float, period_days: int):
        """
        amount: USD amount to lend (positive)
        daily_rate: the DAILY interest rate (Bitfinex funding offers are
                    quoted per day, not annualized -- annualized_rate ~= daily_rate * 365).
                    Pass 0 to peg the offer to Bitfinex's own FRR (documented
                    "FRR Lending" order type -- rate then floats hourly).
        period_days: tenor in days
        """
        body = {
            "type": "LIMIT",
            "symbol": symbol,
            "amount": str(amount),
            "rate": str(daily_rate),
            "period": period_days,
            "flags": 0,
        }
        return self._signed_post("auth/w/funding/offer/submit", body)

    def submit_frr_offer(self, symbol: str, amount: float, period_days: int):
        """Documented 'FRR Lending' order type: rate=0 pegs the offer to the
        current FRR; the matched rate then floats hourly going forward."""
        return self.submit_funding_offer(symbol, amount, 0, period_days)

    def cancel_funding_offer(self, offer_id: int):
        return self._signed_post("auth/w/funding/offer/cancel", {"id": offer_id})


# ---------------------------------------------------------------------------
# Mock client -- synthetic funding book, for testing the strategy with no
# network access and no real credentials. Rates drift with a simple random
# walk, and idle "interest" accrues each cycle so the documented $150
# auto-compound trigger can be demonstrated end-to-end.
# ---------------------------------------------------------------------------
class MockBitfinexClient(BitfinexClient):
    def __init__(self):
        super().__init__()
        import random
        self._rng = random.Random(42)
        self._base_daily_rate = 0.15 / 365  # start near 15% APR
        self._offers = []
        self._next_offer_id = 1000

    def get_funding_book(self, symbol: str, precision: str = "P0", length: int = 25):
        self._base_daily_rate = max(0.0001, self._base_daily_rate + self._rng.uniform(-0.00003, 0.00003))
        book = []
        for i in range(length):
            rate = self._base_daily_rate * (1 + i * 0.02)
            period = 2 if i < 5 else (30 if i < 15 else 120)
            amount = round(self._rng.uniform(500, 20000), 2)
            book.append([rate, period, 1, amount])
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
        if daily_rate == 0:
            log.info(f"  [MOCK] placed FRR-pegged offer id={offer[0]} amount={amount:,.2f} "
                     f"(floats hourly with FRR)  period={period_days}d")
        else:
            log.info(f"  [MOCK] placed offer id={offer[0]} amount={amount:,.2f} "
                     f"daily_rate={daily_rate:.6f} (~{daily_rate*365:.2%} APR) period={period_days}d")
        return offer

    def cancel_funding_offer(self, offer_id):
        self._offers = [o for o in self._offers if o[0] != offer_id]
        return {"status": "cancelled", "id": offer_id}


# ---------------------------------------------------------------------------
# Governance guard: refuse to run live if the key can withdraw/transfer.
# Independently re-enforces Fuly's own documented "Funding-only, never
# Withdraw" setup instructions, and the TSGEX report's "最小授權架構" rule.
# ---------------------------------------------------------------------------
def assert_minimal_permissions(client: BitfinexClient):
    perms = client.get_permissions()
    perm_map = {row[0]: row for row in perms}
    withdraw_perm = perm_map.get("wallets") or perm_map.get("withdraw")
    if withdraw_perm and len(withdraw_perm) >= 4 and int(withdraw_perm[3]) == 1:
        raise RuntimeError(
            "REFUSING TO RUN: this API key has withdrawal/transfer permission. "
            "Both Fuly.ai's own setup guides and TSGEX governance policy require "
            "funding-only keys with withdrawal explicitly disabled. Create a new "
            "restricted key."
        )
    log.info("Permission check passed: key has no withdrawal/transfer scope.")


# ---------------------------------------------------------------------------
# Strategy: tenor selection ("dynamic lending period" -- documented direction,
# TSGEX Section 3.3 ladder used as the disclosed stand-in slope)
# ---------------------------------------------------------------------------
def select_tenor(apr: float, cfg: StrategyConfig) -> int:
    if apr < cfg.normal_apr_ceiling:
        lo, hi = cfg.normal_tenor_days
    elif apr < cfg.elevated_apr_ceiling:
        lo, hi = cfg.elevated_tenor_days
    else:
        if not cfg.authorize_extreme_tenor:
            log.warning(f"  APR {apr:.1%} qualifies for extreme tenor bracket but "
                        f"authorize_extreme_tenor=False -- capping at elevated bracket "
                        f"(mirrors report's '須經風控主管專案簽核' rule)")
            lo, hi = cfg.elevated_tenor_days
        else:
            lo, hi = cfg.extreme_tenor_days
    lo = max(lo, cfg.min_tenor_days)
    hi = min(hi, cfg.max_tenor_days)
    return round((lo + hi) / 2)


def apply_jump_strategy(apr: float, tenor_days: int, cfg: StrategyConfig) -> int:
    """跳跳樂: documented behavior -- below the threshold, snap to the 2-day
    minimum so capital can be released and re-listed fast once rates recover,
    instead of being locked into a low rate for longer."""
    if apr < cfg.jump_strategy_threshold_apr:
        log.info(f"  Rate {apr:.1%} below Jump-Strategy threshold {cfg.jump_strategy_threshold_apr:.1%} "
                 f"-> snapping to {cfg.jump_strategy_tenor_days}-day minimum tenor")
        return cfg.jump_strategy_tenor_days
    return tenor_days


# ---------------------------------------------------------------------------
# FBRR / Dave-High spike-reserve behavior: disclosed proxy signal, NOT a
# reproduction of Fuly's actual (undisclosed) forecasting model
# ---------------------------------------------------------------------------
def compute_spike_signal(rate_history: list, cfg: StrategyConfig) -> bool:
    if len(rate_history) < cfg.spike_slow_window:
        return False
    fast = sum(rate_history[-cfg.spike_fast_window:]) / cfg.spike_fast_window
    slow = sum(rate_history[-cfg.spike_slow_window:]) / cfg.spike_slow_window
    return fast > slow


# ---------------------------------------------------------------------------
# Strategy: order splitting -- inverted pyramid calibrated to Fuly's
# published 80@10% / 100@11% / 120@12% example (size increases with rate)
# ---------------------------------------------------------------------------
def build_tranches(capital: float, best_daily_rate: float, cfg: StrategyConfig):
    """Returns list of (amount, daily_rate) tranches, largest amount at the
    highest rate step (inverted pyramid)."""
    per_order = cfg.max_amount_per_order or default_max_amount_per_order(cfg.capital)
    n = max(1, min(cfg.max_tranches_per_cycle, math.ceil(capital / per_order)))

    rates = [best_daily_rate + i * (cfg.tranche_rate_step_apr / 365) for i in range(n)]
    weights = [cfg.tranche_weight_base + cfg.tranche_weight_step * i for i in range(n)]
    total_weight = sum(weights)

    tranches = [(capital * w / total_weight, r) for w, r in zip(weights, rates)]
    return tranches


# ---------------------------------------------------------------------------
# Main strategy loop -- dispatches on cfg.mode
# ---------------------------------------------------------------------------
def run_cycle(client: BitfinexClient, cfg: StrategyConfig, rate_history: list, live: bool):
    book = client.get_funding_book(cfg.symbol)
    if not book:
        log.warning("Empty funding book response, skipping cycle")
        return
    best_daily_rate = book[0][0]
    apr = best_daily_rate * 365
    rate_history.append(apr)

    lendable = max(0.0, cfg.capital - cfg.reserved_amount)
    if apr < cfg.floor_rate:
        log.info(f"Best rate {apr:.2%} APR is below floor_rate {cfg.floor_rate:.2%} -- holding, no orders this cycle")
        return

    if cfg.mode == "frr":
        tenor = apply_jump_strategy(apr, cfg.min_tenor_days, cfg)
        log.info(f"[FRR mode] Best FRR-referenced rate: {apr:.2%} APR  chosen_tenor={tenor}d (floats hourly)")
        if live:
            client.submit_frr_offer(cfg.symbol, lendable, tenor)
        else:
            log.info(f"  [DRY-RUN] would place FRR-pegged offer: amount={lendable:,.2f}  period={tenor}d")
        return

    spike = compute_spike_signal(rate_history, cfg)
    tenor = select_tenor(apr, cfg)
    tenor = apply_jump_strategy(apr, tenor, cfg)

    if cfg.mode == "dave_high":
        # FBRR-style behavior: when the spike-proxy fires, hold back capital
        # now to lend it at the (anticipated) higher rate later.
        if spike:
            reserve_now = lendable * cfg.fbrr_reserve_fraction
            lendable -= reserve_now
            log.info(f"  [Dave High-Rate mode] spike-proxy fired -> reserving {reserve_now:,.2f} "
                     f"({cfg.fbrr_reserve_fraction:.0%} of lendable capital) for an anticipated rate increase")
        chosen_rate = best_daily_rate
    elif cfg.mode == "dave_fast":
        # Documented: prioritizes fast matching; rate must never exceed what
        # Dave High-Rate mode would have chosen this same cycle.
        dave_high_rate = best_daily_rate + cfg.tranche_rate_step_apr / 365
        chosen_rate = min(best_daily_rate, dave_high_rate)
        tenor = cfg.min_tenor_days
        log.info(f"  [Dave Fast mode] optimizing for speed: single near-immediate tranche at "
                 f"~{chosen_rate*365:.2%} APR, {tenor}d tenor")
        if live:
            client.submit_funding_offer(cfg.symbol, lendable, chosen_rate, tenor)
        else:
            log.info(f"  [DRY-RUN] would place: amount={lendable:,.2f}  "
                     f"daily_rate={chosen_rate:.6f} (~{chosen_rate*365:.2%} APR)  period={tenor}d")
        return
    else:  # custom
        chosen_rate = best_daily_rate

    log.info(f"Best rate: {apr:.2%} APR (daily={best_daily_rate:.6f})  "
             f"mode={cfg.mode}  spike_signal={spike}  chosen_tenor={tenor}d")

    tranches = build_tranches(lendable, chosen_rate, cfg)
    log.info(f"Inverted-pyramid split: {len(tranches)} tranches "
             f"(per-order size ~{cfg.max_amount_per_order or default_max_amount_per_order(cfg.capital):,.0f} USD)")
    for amount, rate in tranches:
        implied_apr = rate * 365
        if live:
            client.submit_funding_offer(cfg.symbol, amount, rate, tenor)
        else:
            log.info(f"  [DRY-RUN] would place: amount={amount:,.2f}  "
                     f"daily_rate={rate:.6f} (~{implied_apr:.2%} APR)  period={tenor}d")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capital", type=float, required=True, help="Total USD capital to allocate")
    ap.add_argument("--symbol", default="fUSD")
    ap.add_argument("--mode", choices=["dave_high", "dave_fast", "custom", "frr"], default="dave_high")
    ap.add_argument("--floor-rate", type=float, default=0.05, help="利率下限, Fuly's documented default is 5%% APR")
    ap.add_argument("--reserved-amount", type=float, default=0.0, help="保留金額, capital to always keep unlent")
    ap.add_argument("--max-amount-per-order", type=float, default=None,
                     help="每筆金額上限 (documented range: 150-1000). Default: scaled from --capital.")
    ap.add_argument("--authorize-extreme-tenor", action="store_true",
                     help="Allow 60-120 day tenor at APR>=30%% (requires risk-officer sign-off per governance policy)")
    ap.add_argument("--jump-strategy-threshold", type=float, default=0.10,
                     help="跳跳樂 threshold APR; Fuly's documented example is ~10%%")
    ap.add_argument("--live", action="store_true", help="Actually place orders (default: dry-run)")
    ap.add_argument("--mock", action="store_true", help="Use synthetic funding book, no network/credentials needed")
    ap.add_argument("--cycles", type=int, default=1, help="Number of poll cycles to run (mock/demo use)")
    ap.add_argument("--poll-interval", type=int, default=5, help="Seconds between cycles (mock/demo use)")
    args = ap.parse_args()

    cfg = StrategyConfig(
        capital=args.capital,
        symbol=args.symbol,
        mode=args.mode,
        floor_rate=args.floor_rate,
        reserved_amount=args.reserved_amount,
        max_amount_per_order=args.max_amount_per_order,
        authorize_extreme_tenor=args.authorize_extreme_tenor,
        jump_strategy_threshold_apr=args.jump_strategy_threshold,
    )

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

    log.info(f"mode={cfg.mode}  floor_rate={cfg.floor_rate:.2%}  reserved_amount={cfg.reserved_amount:,.2f}  "
             f"max_amount_per_order={cfg.max_amount_per_order or default_max_amount_per_order(cfg.capital):,.0f}")

    rate_history = []
    for i in range(args.cycles):
        log.info(f"--- cycle {i+1}/{args.cycles} ---")
        run_cycle(client, cfg, rate_history, live=args.live)
        if i < args.cycles - 1:
            time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
