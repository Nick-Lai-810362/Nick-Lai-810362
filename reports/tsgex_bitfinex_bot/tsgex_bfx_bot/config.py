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

    # Safety bound on tranche count, NOT a Bitfinex-imposed limit (none is
    # published). High enough that a NT$5,000,000-scale account (~USD
    # 158,730) at the P75 calibration (~192 tranches @2d) is not truncated.
    max_orders_per_cycle: int = 400
    tranche_rate_step_apr: float = 0.01
    tranche_weight_base: float = 0.8
    tranche_weight_step: float = 0.2

    # Stale pending-order cancel+relist
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


def platform_fee(cfg: StrategyConfig) -> float:
    return cfg.platform_fee_hidden if cfg.order_visibility == "hidden" else cfg.platform_fee_standard


def net_apr(gross_apr: float, cfg: StrategyConfig) -> float:
    """What actually lands in the account after Bitfinex's platform cut on
    interest earned. All rate-based decisions in this bot (floor check,
    tenor allocation, stale-order drift check) are evaluated on THIS number,
    not the gross quoted rate."""
    return gross_apr * (1 - platform_fee(cfg))
