#!/usr/bin/env python3
"""
TSGEX Bitfinex USD Margin Funding Automation Bot
==================================================

WHAT THIS IS AND ISN'T
-----------------------
This is NOT a copy of Fuly.ai's code or proprietary FBRR model -- that model
is undisclosed and I have no access to it. This is an independently-written
bot that implements the general, PUBLICLY-DESCRIBED strategy techniques
(rate-driven tenor laddering, grid/inverse-pyramid order splitting, a
transparent rate-momentum heuristic) using the exact tenor ladder your own
TSGEX report already specified in Section 3.3:

    APR < 15%   -> 2-7 day tenor, auto-renew
    15% <= APR < 30% -> 15-30 day tenor
    APR >= 30%  -> up to 60-120 days, REQUIRES explicit project authorization
                   (see AUTHORIZE_EXTREME_TENOR below -- off by default)

The "rate momentum signal" here is a plain, disclosed EMA-crossover heuristic
-- not a claim to replicate FBRR's actual (undisclosed) forecasting model.
Treat it as a starting point to tune or replace, not a proven predictive edge.

SAFETY DEFAULTS
----------------
- Runs in --dry-run mode by default. No live orders are placed unless you
  pass --live AND supply real API credentials.
- Before placing any live order, checks the API key's permissions via
  Bitfinex's /v2/auth/r/permissions endpoint and REFUSES to run if the key
  has withdrawal permission -- enforcing the minimal-permission governance
  rule from the TSGEX report (funding read/write only, no withdrawal).
- Includes a --mock mode with a synthetic funding book so you can see the
  strategy logic run end-to-end without any network access or real keys.

SETTING UP A REAL API KEY (when you're ready to go live)
-----------------------------------------------------------
1. Bitfinex account -> API Keys -> Create New Key
2. Enable ONLY: "Margin Funding" (read + write / orders). Do NOT enable
   "Withdraw" or "Transfer" under any circumstance.
3. Optionally restrict the key to your server's IP address (recommended).
4. Pass the key/secret via environment variables (never hardcode them):
     export BFX_API_KEY=...
     export BFX_API_SECRET=...
   python tsgex_bitfinex_lending_bot.py --live --capital 1000000 --symbol fUSD

USAGE EXAMPLES
--------------
  # See the strategy run against a synthetic funding book, no network needed
  python tsgex_bitfinex_lending_bot.py --mock --capital 1000000

  # Dry-run against REAL live market data (places no orders), needs network
  python tsgex_bitfinex_lending_bot.py --capital 1000000 --symbol fUSD

  # Actually place live orders (only after you've reviewed dry-run output)
  python tsgex_bitfinex_lending_bot.py --live --capital 1000000 --symbol fUSD
"""
import argparse
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("tsgex_bot")

BFX_API_URL = "https://api.bitfinex.com"


# ---------------------------------------------------------------------------
# Strategy config -- mirrors TSGEX report Section 3.3's tenor ladder exactly
# ---------------------------------------------------------------------------
@dataclass
class StrategyConfig:
    capital: float
    symbol: str = "fUSD"

    # Tenor ladder thresholds (annualized rate, as a fraction e.g. 0.15 = 15%)
    normal_apr_ceiling: float = 0.15
    elevated_apr_ceiling: float = 0.30
    normal_tenor_days: tuple = (2, 7)
    elevated_tenor_days: tuple = (15, 30)
    extreme_tenor_days: tuple = (60, 120)
    authorize_extreme_tenor: bool = False  # must be explicitly flipped on -- mirrors the report's
                                            # "須經風控主管專案簽核" requirement for the >=30% bracket

    # Order-splitting strategy: "grid" (equal size per rate tranche) or
    # "inverse_pyramid" (larger size at higher rates)
    split_style: str = "inverse_pyramid"
    num_tranches: int = 5
    tranche_rate_step: float = 0.0005  # 0.05% APR spacing between tranches, in daily-rate terms below

    # "Jump strategy": if current best rate is below this, prefer the
    # shortest tenor available to preserve capital velocity instead of
    # locking in a low rate for longer
    jump_strategy_floor_apr: float = 0.06

    # Momentum signal (disclosed heuristic, NOT a claim to replicate FBRR)
    momentum_fast_window: int = 6     # in units of "ticks" (poll cycles)
    momentum_slow_window: int = 24
    momentum_tenor_bias_days: int = 2  # extra days added to chosen tenor when momentum is rising

    poll_interval_sec: int = 300


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
                    quoted per day, not annualized -- annualized_rate ~= daily_rate * 365)
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

    def cancel_funding_offer(self, offer_id: int):
        return self._signed_post("auth/w/funding/offer/cancel", {"id": offer_id})


# ---------------------------------------------------------------------------
# Mock client -- synthetic funding book, for testing the strategy with no
# network access and no real credentials. Rates drift with a simple random
# walk so repeated polls show the momentum signal reacting to something.
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
        log.info(f"  [MOCK] placed offer id={offer[0]} amount={amount:.2f} "
                 f"daily_rate={daily_rate:.6f} (~{daily_rate*365:.2%} APR) period={period_days}d")
        return offer

    def cancel_funding_offer(self, offer_id):
        self._offers = [o for o in self._offers if o[0] != offer_id]
        return {"status": "cancelled", "id": offer_id}


# ---------------------------------------------------------------------------
# Governance guard: refuse to run live if the key can withdraw/transfer.
# Mirrors the TSGEX report's "最小授權架構" requirement.
# ---------------------------------------------------------------------------
def assert_minimal_permissions(client: BitfinexClient):
    perms = client.get_permissions()
    perm_map = {row[0]: row for row in perms}
    withdraw_perm = perm_map.get("wallets") or perm_map.get("withdraw")
    if withdraw_perm and len(withdraw_perm) >= 4 and int(withdraw_perm[3]) == 1:
        raise RuntimeError(
            "REFUSING TO RUN: this API key has withdrawal/transfer permission. "
            "Per TSGEX governance policy, funding-bot keys must be funding-only "
            "with withdrawal explicitly disabled. Create a new restricted key."
        )
    log.info("Permission check passed: key has no withdrawal/transfer scope.")


# ---------------------------------------------------------------------------
# Strategy: tenor selection (TSGEX Section 3.3 ladder)
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
    return round((lo + hi) / 2)


def apply_momentum_bias(tenor_days: int, momentum_rising: bool, cfg: StrategyConfig) -> int:
    """Disclosed heuristic: if recent rates are trending up, lean slightly
    longer to lock in the improving rate before it moves further; if flat/
    falling, leave tenor as-is (favors the 'jump strategy' short end instead).
    This is NOT a reproduction of Fuly.ai's undisclosed FBRR model."""
    if momentum_rising:
        return tenor_days + cfg.momentum_tenor_bias_days
    return tenor_days


def compute_momentum(rate_history: list, cfg: StrategyConfig) -> bool:
    if len(rate_history) < cfg.momentum_slow_window:
        return False
    fast = sum(rate_history[-cfg.momentum_fast_window:]) / cfg.momentum_fast_window
    slow = sum(rate_history[-cfg.momentum_slow_window:]) / cfg.momentum_slow_window
    return fast > slow


# ---------------------------------------------------------------------------
# Strategy: order splitting (grid vs inverse-pyramid), mirrors the two
# publicly-described Fuly.ai tranche styles
# ---------------------------------------------------------------------------
def build_tranches(capital: float, best_daily_rate: float, cfg: StrategyConfig):
    """Returns list of (amount, daily_rate) tranches."""
    n = cfg.num_tranches
    rates = [best_daily_rate + i * cfg.tranche_rate_step / 365 for i in range(n)]

    if cfg.split_style == "grid":
        weights = [1.0] * n
    elif cfg.split_style == "inverse_pyramid":
        # larger weight at higher rate tranches, e.g. for n=3: 0.8, 1.0, 1.2
        weights = [0.8 + 0.2 * i for i in range(n)]
    else:
        raise ValueError(f"unknown split_style: {cfg.split_style}")

    total_weight = sum(weights)
    tranches = [(capital * w / total_weight, r) for w, r in zip(weights, rates)]
    return tranches


def apply_jump_strategy(apr: float, tenor_days: int, cfg: StrategyConfig) -> int:
    """If the best available rate is below the floor, prefer the shortest
    tenor to preserve capital velocity rather than locking in a low rate."""
    if apr < cfg.jump_strategy_floor_apr:
        log.info(f"  Rate {apr:.1%} below jump-strategy floor {cfg.jump_strategy_floor_apr:.1%} "
                 f"-> shortening tenor to preserve capital velocity")
        return cfg.normal_tenor_days[0]
    return tenor_days


# ---------------------------------------------------------------------------
# Main strategy loop
# ---------------------------------------------------------------------------
def run_cycle(client: BitfinexClient, cfg: StrategyConfig, rate_history: list, live: bool):
    book = client.get_funding_book(cfg.symbol)
    if not book:
        log.warning("Empty funding book response, skipping cycle")
        return
    best_daily_rate = book[0][0]
    apr = best_daily_rate * 365
    rate_history.append(apr)

    momentum_rising = compute_momentum(rate_history, cfg)
    tenor = select_tenor(apr, cfg)
    tenor = apply_momentum_bias(tenor, momentum_rising, cfg)
    tenor = apply_jump_strategy(apr, tenor, cfg)

    log.info(f"Best rate: {apr:.2%} APR (daily={best_daily_rate:.6f})  "
             f"momentum_rising={momentum_rising}  chosen_tenor={tenor}d")

    tranches = build_tranches(cfg.capital, best_daily_rate, cfg)
    log.info(f"Split style: {cfg.split_style}  ({len(tranches)} tranches)")
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
    ap.add_argument("--split-style", choices=["grid", "inverse_pyramid"], default="inverse_pyramid")
    ap.add_argument("--tranches", type=int, default=5)
    ap.add_argument("--authorize-extreme-tenor", action="store_true",
                     help="Allow 60-120 day tenor at APR>=30%% (requires risk-officer sign-off per governance policy)")
    ap.add_argument("--live", action="store_true", help="Actually place orders (default: dry-run)")
    ap.add_argument("--mock", action="store_true", help="Use synthetic funding book, no network/credentials needed")
    ap.add_argument("--cycles", type=int, default=1, help="Number of poll cycles to run (mock/demo use)")
    ap.add_argument("--poll-interval", type=int, default=5, help="Seconds between cycles (mock/demo use)")
    args = ap.parse_args()

    cfg = StrategyConfig(
        capital=args.capital,
        symbol=args.symbol,
        split_style=args.split_style,
        num_tranches=args.tranches,
        authorize_extreme_tenor=args.authorize_extreme_tenor,
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
    else:
        log.info("DRY-RUN mode: no real orders will be placed.")

    rate_history = []
    for i in range(args.cycles):
        log.info(f"--- cycle {i+1}/{args.cycles} ---")
        run_cycle(client, cfg, rate_history, live=args.live)
        if i < args.cycles - 1:
            time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
