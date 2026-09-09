"""
Module-level constants -- all the real-data-derived numbers the strategy is
calibrated against, in one place with their sourcing disclosed.

See README.md / CHANGELOG.md for the research these came from. Every value
here is a dated, point-in-time read of the market (collected 2026-09) or a
disclosed heuristic where no real data was available -- refresh periodically
by re-running TSGEX_Bitfinex_Funding_History_Collector.py, don't treat these
as permanent constants.
"""

BFX_API_URL = "https://api.bitfinex.com"
BFX_MIN_ORDER_USD = 150.0  # Bitfinex's own documented funding-offer minimum

# Real, liquid tenor buckets per Bitfinex's own documentation ("the most
# common periods are 2, 7, or 30 days") and real trade-volume evidence
# (period=2 was 89.6% of trade count / 96%+ of volume in the ~10,000-row
# recent trades sample; period=30 ~1.0%, period=120 just 0.11%).
TARGET_TENORS = (2, 7, 30)
EXTREME_TENOR = 120  # excluded from TARGET_TENORS: measured no rate premium
# over 30d across 5 years of real p30/p120 candle data (median spread +0.04pp,
# positive only 55.4% of the time) while having ~8x less liquidity than the
# already-thin 30d market -- strictly dominated. Opt-in only via
# StrategyConfig.authorize_extreme_tenor, e.g. for a deliberate large block trade.

# Point-in-time (2026-09-07) empirical per-tenor typical order size: the P75
# trade size for that tenor bucket, from the real fUSD trades sample. P75
# (not median) was chosen so pending-order monitoring/cancel-relist overhead
# stays reasonable at large capital scale, while staying comfortably below
# the thin P90 tail so fill probability isn't meaningfully worse than the
# median target (see CHANGELOG.md "v5" for the full NT$5,000,000 worked
# example that motivated this choice).
TENOR_TYPICAL_ORDER_SIZE = {2: 825.0, 7: 574.0, 30: 491.0, EXTREME_TENOR: 491.0}

SUBMIT_PACING_SEC = 1.0  # live-mode only; 1/sec = 60/min, safely inside
# Bitfinex's documented request-rate limit of 10-90 req/min (varies by endpoint).

# Disclosed heuristic (NOT measured -- Bitfinex's REST API has no historical
# order-book endpoint, so real fill-latency can't be measured retroactively
# the way the rate/tenor data could be). Hours before a still-unfilled
# pending order is considered stale and cancelled+relisted at the current
# rate. Scaled roughly proportional to tenor length and inversely to that
# bucket's real matching liquidity (thinner market = more patience).
DEFAULT_MAX_WAIT_HOURS = {2: 6.0, 7: 24.0, 30: 72.0, EXTREME_TENOR: 120.0}

# Bitfinex charges a platform fee on funding INTEREST EARNED (not principal):
# 15% on standard visible offers, 18% on hidden offers.
PLATFORM_FEE_STANDARD = 0.15
PLATFORM_FEE_HIDDEN = 0.18
