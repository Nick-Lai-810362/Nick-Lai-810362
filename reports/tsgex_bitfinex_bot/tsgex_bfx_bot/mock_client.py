"""
Mock Bitfinex client -- synthetic funding book shaped to match the REAL
observed liquidity concentration (mostly 2d, some 7d, thin 30d/120d) and a
term premium that varies cycle to cycle, PLUS a simulated pending-offer fill
lifecycle: each cycle, every still-open mock offer independently rolls a
per-tenor fill chance (shorter/more liquid tenors fill faster), simulating
real partial-fill-over-time behavior with zero network access.
"""
import random
import time

from .client import BitfinexClient
from .constants import EXTREME_TENOR


class MockBitfinexClient(BitfinexClient):
    FILL_PROB_PER_CYCLE = {2: 0.55, 7: 0.35, 30: 0.15, EXTREME_TENOR: 0.05}

    def __init__(self, seed: int = 42):
        super().__init__()
        self._rng = random.Random(seed)
        self._base_daily_rate_2d = 0.07 / 365  # ~7% APR, matches the real 2026-09-07 snapshot median
        self._offers = []
        self._next_offer_id = 1000

    def get_funding_book(self, symbol: str, precision: str = "P0", length: int = 100):
        self._base_daily_rate_2d = max(0.00003, self._base_daily_rate_2d + self._rng.uniform(-0.000015, 0.000015))
        premium_pp = self._rng.choice([0.0, 0.01, 0.02, 0.04])  # sometimes flat, sometimes a real premium
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
