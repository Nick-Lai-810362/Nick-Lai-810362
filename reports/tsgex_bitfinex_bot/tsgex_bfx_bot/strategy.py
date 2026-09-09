"""
Live-book-driven tenor allocation and tranche construction.

decide_tenor_allocation() reads the ACTUAL currently-available rate at each
tenor bucket from the live funding book every cycle and only shifts capital
to a longer tenor when the CURRENTLY observed premium clears a configurable
minimum -- NOT a fixed rate->tenor lookup table. See CHANGELOG.md ("v4"
finding #3) for why a fixed table was tried and rejected: the real 2d->30d
term premium varies from ~0.78pp (a same-day snapshot) to ~3.65pp (5-year
median), so a static table would be wrong on a random day.
"""
import math
from typing import Dict, List, Tuple

from .config import StrategyConfig, net_apr
from .constants import EXTREME_TENOR, TARGET_TENORS, TENOR_TYPICAL_ORDER_SIZE


def best_rate_by_tenor(book: list, target_tenors=TARGET_TENORS) -> Dict[int, float]:
    """Scans the full funding book and returns {tenor_days: best (lowest)
    daily_rate actually quoted at that tenor right now}, restricted to
    target_tenors. A tenor with no rows in the current book is omitted."""
    out: Dict[int, float] = {}
    for row in book:
        rate, period = row[0], row[1]
        if period in target_tenors:
            if period not in out or rate < out[period]:
                out[period] = rate
    return out


def decide_tenor_allocation(tenor_rates: Dict[int, float], cfg: StrategyConfig) -> Dict[int, float]:
    """Given the live best rate at each available tenor, decide what
    fraction of lendable capital goes to each tenor."""
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


def compute_spike_signal(rate_history: List[float], cfg: StrategyConfig) -> bool:
    """Disclosed EMA-crossover proxy for Fuly's undisclosed FBRR forecasting
    model -- NOT a reproduction of it, just a transparent stand-in behavior."""
    if len(rate_history) < cfg.spike_slow_window:
        return False
    fast = sum(rate_history[-cfg.spike_fast_window:]) / cfg.spike_fast_window
    slow = sum(rate_history[-cfg.spike_slow_window:]) / cfg.spike_slow_window
    return fast > slow


def build_tranches_for_tenor(capital: float, best_daily_rate: float, tenor_days: int,
                              cfg: StrategyConfig) -> List[Tuple[float, float]]:
    """Inverted-pyramid split within one tenor bucket, sized against that
    bucket's own empirically observed typical order size (TENOR_TYPICAL_
    ORDER_SIZE), calibrated to Fuly's published example (80@10%/100@11%/
    120@12% -> larger amount at the higher, less-competitive rate step)."""
    per_order = TENOR_TYPICAL_ORDER_SIZE.get(tenor_days, 500.0)
    n = max(1, min(cfg.max_orders_per_cycle, math.ceil(capital / per_order)))
    rates = [best_daily_rate + i * (cfg.tranche_rate_step_apr / 365) for i in range(n)]
    weights = [cfg.tranche_weight_base + cfg.tranche_weight_step * i for i in range(n)]
    total_weight = sum(weights)
    return [(capital * w / total_weight, r) for w, r in zip(weights, rates)]
