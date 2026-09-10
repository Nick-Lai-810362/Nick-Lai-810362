"""
Bitfinex REST client -- public market data + authenticated funding endpoints.
"""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from typing import Optional

from .constants import BFX_API_URL


class BitfinexClient:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret

    # ---- public endpoints (no auth) ----
    def get_funding_book(self, symbol: str, precision: str = "P0", length: int = 100):
        url = f"{BFX_API_URL}/v2/book/{symbol}/{precision}?len={length}"
        return self._get(url)

    def get_ticker(self, symbol: str):
        return self._get(f"{BFX_API_URL}/v2/ticker/{symbol}")

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
        sig = hmac.new(self.api_secret.encode(), f"{path}{nonce}{body_json}".encode(), hashlib.sha384).hexdigest()
        headers = {"Content-Type": "application/json", "bfx-nonce": nonce,
                   "bfx-apikey": self.api_key, "bfx-signature": sig}
        req = urllib.request.Request(f"{BFX_API_URL}{path}", data=body_json.encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def get_permissions(self):
        """Used to enforce the no-withdrawal governance rule (see governance.py)."""
        return self._signed_post("auth/r/permissions", {})

    def get_active_funding_offers(self, symbol: str):
        return self._signed_post(f"auth/r/funding/offers/{symbol}", {})

    def get_wallet_balances(self):
        """[[WALLET_TYPE, CURRENCY, BALANCE, UNSETTLED_INTEREST, BALANCE_AVAILABLE, ...], ...]
        per docs.bitfinex.com/reference/rest-auth-wallets. Only needs read scope on
        "wallets" -- governance.assert_minimal_permissions already only blocks WRITE
        scope on that permission, so this is safe under the funding-only key policy.
        NOT verified against a live call (network egress to Bitfinex is blocked in the
        sandbox this bot was developed in) -- cross-check the parsed values against the
        Bitfinex UI before relying on them, same caveat as extract_offer_id()."""
        return self._signed_post("auth/r/wallets", {})

    def get_funding_loans_history(self, symbol: str, limit: int = 200):
        """Exchange-side record of past funding loans (offers that were taken and have
        since closed) for `symbol`, per docs.bitfinex.com/reference/rest-auth-funding-loans-hist.
        Used as an optional live cross-check against this bot's own local ledger, which
        remains the authoritative record for principal/profit accounting -- this bot may
        not be the only thing lending on the account. NOT verified against a live call,
        same caveat as get_wallet_balances()."""
        return self._signed_post(f"auth/r/funding/loans/{symbol}/hist", {"limit": limit})

    def submit_funding_offer(self, symbol: str, amount: float, daily_rate: float, period_days: int):
        """
        daily_rate: the DAILY interest rate (annualized_rate ~= daily_rate * 365).
                    Pass 0 to peg the offer to Bitfinex's own FRR (documented
                    "FRR Lending" order type -- rate then floats hourly).
        """
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
    against a live call (network egress to Bitfinex is blocked in the
    sandbox this bot was developed in); if the real shape differs, this
    returns None and that position's offer_id stays unset (safe fallback:
    maturity-only tracking, just not stale-cancellable) -- verify against
    your own key before relying on this for live cancel+relist."""
    try:
        if isinstance(resp, list) and len(resp) > 0:
            # Check the MORE SPECIFIC live-envelope shape first: its index 0
            # is MTS (an int), so checking "is resp[0] a list?" first would
            # always misfire into the mock-shape branch below and silently
            # return the wrong value (a real bug caught by this function's
            # own unit tests -- see tests/test_client.py).
            if len(resp) >= 5 and isinstance(resp[4], list) and len(resp[4]) > 0:
                return resp[4][0]  # live: notification envelope
            if not isinstance(resp[0], list):
                return resp[0]  # mock: raw offer list, ID first
    except Exception:
        pass
    return None
