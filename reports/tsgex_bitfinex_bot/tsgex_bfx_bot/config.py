"""
Strategy configuration and the two small pure functions (platform_fee,
net_apr) that most other modules depend on.
"""
from dataclasses import dataclass, field
from typing import Optional

from .constants import (
    DEFAULT_MAX_WAIT_HOURS,
    PLATFORM_FEE_HIDDEN,
    PLATFORM_FEE_STANDARD,
)


@dataclass
class StrategyConfig:
    symbol: str = "fUSD"
    mode: str = "dave_high"  # "dave_high" | "dave_fast" | "custom" | "frr" | "barbell"

    platform_fee_standard: float = PLATFORM_FEE_STANDARD
    platform_fee_hidden: float = PLATFORM_FEE_HIDDEN
    order_visibility: str = "standard"  # "standard" | "hidden"

    floor_rate: float = 0.05          # net-of-fee APR floor; below this, hold and place nothing
    reserved_amount: float = 0.0      # capital always kept unlent

    term_premium_min_pp: float = 0.02
    authorize_extreme_tenor: bool = False
    barbell_short_fraction: float = 0.5

    # How much of the short-tenor (anchor) allocation decide_tenor_allocation
    # is allowed to shift away to longer tenors that clear term_premium_min_pp,
    # in total across every longer tenor combined. The short bucket always
    # keeps at least (1 - this) -- see v4 finding #1: liquidity is 89.6%
    # concentrated at the shortest tenor, so the anchor bucket should never be
    # fully vacated even when several longer tenors all clear the premium bar.
    max_total_shift_from_short: float = 0.7

    # A period's live-book depth (see strategy.depth_by_tenor) must clear this
    # before decide_tenor_allocation will consider shifting capital into it --
    # a rate quoted by a single thin order isn't something a real tranche can
    # reliably fill against (v4 finding #1). Disclosed heuristic, roughly ~1.5x
    # the average calibrated tranche size (TENOR_TYPICAL_ORDER_SIZE), not
    # measured order-book depth data (Bitfinex's REST API exposes no
    # historical depth endpoint).
    min_period_depth_usd: float = 1000.0

    # Tranche sizing mode: "calibrated" (default) sizes tranches against each
    # tenor's own real observed trade size (TENOR_TYPICAL_ORDER_SIZE), letting
    # tranche COUNT fall out of capital/typical-size. "fixed_count" instead
    # splits capital evenly across a caller-chosen number of concurrent orders
    # (max_concurrent_orders) -- for direct control over how many orders are
    # outstanding at once instead of letting it be derived from calibration.
    tranche_sizing_mode: str = "calibrated"
    max_concurrent_orders: int = 20

    # Safety bound on tranche count, NOT a Bitfinex-imposed limit (none is
    # published). High enough that a NT$5,000,000-scale account (~USD
    # 158,730) at the P75 calibration (~192 tranches @2d) is not truncated.
    # Only applies to "calibrated" mode -- "fixed_count" mode is bounded by
    # max_concurrent_orders instead.
    max_orders_per_cycle: int = 400
    tranche_rate_step_apr: float = 0.01
    tranche_weight_base: float = 0.8
    tranche_weight_step: float = 0.2

    # Stale pending-order cancel+relist
    max_wait_hours: dict = field(default_factory=lambda: dict(DEFAULT_MAX_WAIT_HOURS))
    max_wait_multiplier: float = 1.0
    rate_drift_threshold_pp: float = 0.01

    # FBRR / Dave-High reserve behavior: disclosed proxy signal, not Fuly's real model.
    # DEFAULT OFF -- a real backtest against 5 years of real fUSD hourly rate
    # data (see CHANGELOG.md "v5.1") found this signal's assumed direction is
    # empirically BACKWARDS: when it fires (fast MA > slow MA, i.e. recent
    # upward momentum), the rate subsequently DECLINES on average (-0.7 to
    # -1.0pp over the next 24h/7d, n>11,000, consistent both in-sample and
    # out-of-sample), not rises as the "reserve capital for an anticipated
    # increase" logic assumes. Enable only if you've independently validated
    # a signal you trust -- see enable_spike_reserve.
    enable_spike_reserve: bool = False
    spike_fast_window: int = 6
    spike_slow_window: int = 24
    fbrr_reserve_fraction: float = 0.15

    state_path: str = "bfx_bot_state.json"
    audit_log_path: Optional[str] = "bfx_bot_audit_log.jsonl"
    poll_interval_sec: int = 300


def platform_fee(cfg: StrategyConfig) -> float:
    return cfg.platform_fee_hidden if cfg.order_visibility == "hidden" else cfg.platform_fee_standard


def net_apr(gross_apr: float, cfg: StrategyConfig) -> float:
    """What actually lands in the account after Bitfinex's platform cut on
    interest earned. All rate-based decisions in this bot (floor check,
    tenor allocation, stale-order drift check) are evaluated on THIS number,
    not the gross quoted rate."""
    return gross_apr * (1 - platform_fee(cfg))
