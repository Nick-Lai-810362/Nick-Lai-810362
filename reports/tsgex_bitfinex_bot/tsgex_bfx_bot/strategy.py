"""
Live-book-driven tenor allocation and tranche construction.

decide_tenor_allocation() reads the ACTUAL currently-available rate at EVERY
tenor quoted in the live funding book (not a fixed 2/7/30 shortlist -- see
v5.2) and only shifts capital to a longer tenor when the CURRENTLY observed
premium clears a configurable minimum -- NOT a fixed rate->tenor lookup
table. See CHANGELOG.md ("v4" finding #3) for why a fixed table was tried
and rejected: the real 2d->30d term premium varies from ~0.78pp (a
same-day snapshot) to ~3.65pp (5-year median), so a static table would be
wrong on a random day.
"""
import math
from typing import Dict, List, Tuple

from .config import StrategyConfig, net_apr
from .constants import TENOR_TYPICAL_ORDER_SIZE


def best_rate_by_tenor(book: list) -> Dict[int, float]:
    """Scans the full funding book and returns {tenor_days: best (lowest)
    daily_rate actually quoted at that tenor right now} for EVERY period
    present -- not filtered to a fixed shortlist. Depth filtering (avoiding
    thin/illiquid periods) happens separately in decide_tenor_allocation via
    depth_by_tenor(), since "is this rate real" and "is this rate tradeable"
    are different questions."""
    out: Dict[int, float] = {}
    for row in book:
        rate, period = row[0], row[1]
        if period not in out or rate < out[period]:
            out[period] = rate
    return out


def depth_by_tenor(book: list) -> Dict[int, float]:
    """Total quoted USD amount at each period in the current book -- used to
    filter out periods with only a token quote or two (see v5.2:
    cfg.min_period_depth_usd)."""
    out: Dict[int, float] = {}
    for row in book:
        period, amount = row[1], abs(row[3])
        out[period] = out.get(period, 0.0) + amount
    return out


def decide_tenor_allocation(tenor_rates: Dict[int, float], cfg: StrategyConfig,
                             depth: Dict[int, float] = None) -> Dict[int, float]:
    """Given the live best rate at every available tenor, decide what
    fraction of lendable capital goes to each. Generalizes to however many
    distinct periods the live book actually quotes right now (previously
    hardcoded to exactly 2/7/30d -- see CHANGELOG.md "v5.2"): the shortest
    available tenor is the anchor/base allocation, then each longer tenor
    (ascending) is considered in turn and gets a share shifted from the
    anchor only if its live net-APR premium over the anchor clears
    cfg.term_premium_min_pp. A period beyond 30 days is only considered at
    all with cfg.authorize_extreme_tenor set (same governance-gate spirit as
    before, now applied to "any long lock-up" rather than exactly 120d). A
    period is skipped entirely if its current book depth is below
    cfg.min_period_depth_usd -- a rate quoted by a single thin order isn't
    something a real tranche can reliably fill against (see v4 finding #1:
    liquidity is 89.6% concentrated at 2d; most other periods are only ever
    quoted by a handful of participants).
    """
    available = sorted(
        t for t in tenor_rates
        if (t <= 30 or cfg.authorize_extreme_tenor)
        and (depth is None or depth.get(t, 0.0) >= cfg.min_period_depth_usd)
    )
    if not available:
        return {}
    short = available[0]
    short_net = net_apr(tenor_rates[short] * 365, cfg)

    alloc = {short: 1.0}
    shift_budget = cfg.max_total_shift_from_short  # short bucket always keeps at least this much
    for t in available[1:]:
        if shift_budget <= 1e-9:
            break
        t_net = net_apr(tenor_rates[t] * 365, cfg)
        premium_pp = t_net - short_net
        if premium_pp >= cfg.term_premium_min_pp:
            shift = min(shift_budget, 0.25 + (premium_pp - cfg.term_premium_min_pp) * 10)
            alloc[short] -= shift
            alloc[t] = alloc.get(t, 0.0) + shift
            shift_budget -= shift
    alloc[short] = max(0.0, alloc[short])
    total = sum(alloc.values())
    return {t: w / total for t, w in alloc.items() if w > 1e-9}


def compute_spike_signal(rate_history: List[float], cfg: StrategyConfig) -> bool:
    """Disclosed EMA-crossover proxy for Fuly's undisclosed FBRR forecasting
    model -- NOT a reproduction of it, just a transparent stand-in behavior.
    A real backtest found its assumed direction is empirically backwards
    (see CHANGELOG.md "v5.1"), which is why enable_spike_reserve defaults
    False regardless of what this function returns."""
    if len(rate_history) < cfg.spike_slow_window:
        return False
    fast = sum(rate_history[-cfg.spike_fast_window:]) / cfg.spike_fast_window
    slow = sum(rate_history[-cfg.spike_slow_window:]) / cfg.spike_slow_window
    return fast > slow


def build_tranches_for_tenor(capital: float, best_daily_rate: float, tenor_days: int,
                              cfg: StrategyConfig) -> List[Tuple[float, float]]:
    """Splits `capital` into tranches at ascending rate steps within one
    tenor bucket. Two sizing modes (cfg.tranche_sizing_mode):

    "calibrated" (default): inverted-pyramid, sized against that bucket's
    own empirically observed typical order size (TENOR_TYPICAL_ORDER_SIZE),
    calibrated to Fuly's published example (80@10%/100@11%/120@12% ->
    larger amount at the higher, less-competitive rate step). Tranche COUNT
    falls out of capital / typical-size, capped at max_orders_per_cycle.

    "fixed_count": a caller-chosen number of tranches (max_concurrent_orders),
    capital split EVENLY across them (not weighted) -- for when you'd rather
    directly control how many concurrent orders are outstanding than let it
    be derived from real trade-size calibration. Automatically reduced if
    capital/count would fall under Bitfinex's $150 minimum order size."""
    if cfg.tranche_sizing_mode == "fixed_count":
        from .constants import BFX_MIN_ORDER_USD
        max_by_min_size = max(1, math.floor(capital / BFX_MIN_ORDER_USD)) if capital > 0 else 1
        n = max(1, min(cfg.max_concurrent_orders, max_by_min_size))
        weights = [1.0] * n
    else:
        per_order = TENOR_TYPICAL_ORDER_SIZE.get(tenor_days, 500.0)
        n = max(1, min(cfg.max_orders_per_cycle, math.ceil(capital / per_order)))
        weights = [cfg.tranche_weight_base + cfg.tranche_weight_step * i for i in range(n)]

    rates = [best_daily_rate + i * (cfg.tranche_rate_step_apr / 365) for i in range(n)]
    total_weight = sum(weights)
    return [(capital * w / total_weight, r) for w, r in zip(weights, rates)]
