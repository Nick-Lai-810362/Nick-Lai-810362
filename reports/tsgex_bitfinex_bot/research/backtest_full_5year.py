"""
Full-history backtest of the ACTUAL bot -- not a re-implementation of its
math in a spreadsheet, but the real tsgex_bfx_bot.runner.run_cycle() (the
exact function the CLI calls every cycle) driven hour-by-hour, walk-forward,
over the real ~5-year hourly fUSD funding-rate history already collected for
this project. This is what the user asked for: how long an order sits before
it fills, when the bot cancels and re-lists a stale order, how it responds to
real historical rate swings, and what annualized return actually resulted --
using the program's own decision/execution/ledger code, not a hypothetical.

DATA: research/data/funding_candles_fUSD_p2.csv / _p30.csv (2d and 30d fUSD
hourly close rates). p2 covers 2020-12-23 to 2026-09-07; p30 only starts
2021-08-23 -- the joint (both-valid) window used below is bounded by p30's
start, giving ~5.0 years, matching "近五年" (approximately 5 years).

WALK-FORWARD / NO-LOOKAHEAD: at simulated hour i, HistoricalFundingBook only
ever exposes row i's rate (the "current" market print) to decide_tenor_
allocation() -- nothing at i+1..N is readable at that point in the loop, by
construction (the client's cursor only moves forward). No forecasting model
is fit anywhere in the live decision path; every decision uses only what a
real bot polling the live book at that real historical moment could have
seen.

WHAT IS AND ISN'T REAL DATA HERE (read before trusting the numbers):
  - REAL: the 2d and 30d funding RATES at every historical hour (this is
    the actual market history, unmodified except for the same cleaning
    already used throughout this project: hourly grid, forward-filled up to
    6h gaps, outlier ticks >1%/day dropped, and only hours where BOTH tenors
    have a valid print are kept -- see backtest_spike_and_premium.py).
  - DISCLOSED HEURISTIC, NOT MEASURED (same limitation disclosed in
    constants.py: Bitfinex's REST API has no historical order-book or
    fill-latency endpoint, so none of this could be measured even in
    principle):
      * Per-tenor order-book DEPTH is held constant (2d deep/liquid, 30d
        thin-but-tradeable), shaped from the real TENOR_TYPICAL_ORDER_SIZE
        calibration and the real v4 finding that liquidity is ~89.6%
        concentrated at 2d. A real historical dry-liquidity spell at 30d
        cannot be detected from a close-price series alone, so this
        backtest cannot know about (and therefore cannot react to) one --
        every hour's 30d depth clears cfg.min_period_depth_usd by
        construction.
      * Per-tenor FILL PROBABILITY per polling cycle reuses
        MockBitfinexClient.FILL_PROB_PER_CYCLE UNCHANGED (2d=55%, 7d=35%,
        30d=15%, 120d=5% chance of being matched within one cycle) -- the
        same heuristic already disclosed and used in this project's Part B
        utilization sweep (CHANGELOG.md "v5.4"), now applied to a 1-HOUR
        cycle instead of that sweep's 6-hour cycle. The two studies' absolute
        numbers are therefore not directly comparable (a flat per-cycle
        probability compounds differently at different cycle lengths); each
        is internally honest about its own cycle length.

PERFORMANCE NOTE: running one cycle per REAL data hour over ~5 years is
~44,000 cycles per mode. runner.run_cycle() unconditionally calls
ledger.save_state() at the end of every cycle, which JSON-serializes the
ENTIRE position history -- fine for a real bot cycling every few minutes,
pathological for 44,000 backtest cycles replaying a growing multi-thousand-
position ledger. This script temporarily monkeypatches runner.save_state to
a no-op FOR THE DURATION OF ITS OWN LOOP ONLY (the shipped runner.py/
ledger.py files are not modified) and calls the real save_state() once,
manually, after each mode's loop finishes, purely so the run completes in
minutes instead of hours. This changes nothing about when positions are
opened, filled, cancelled, or matured -- only how often the (otherwise
unobserved, mid-loop) ledger snapshot is written to disk.

(A "fixed_count" tranche-sizing override was tried first as a precaution
against exactly this cost, then measured and dropped: because "lendable"
idle capital on any given cycle is usually a small slice of total capital
--  most of it stays deployed -- the calibrated ladder rarely reaches its
theoretical ~190-tranche width in practice, so every mode below runs with
the bot's real out-of-the-box default "calibrated" tranche sizing.)

USAGE: python backtest_full_5year.py [--data-dir PATH] [--modes dave_high,dave_fast,barbell,frr]
DEPENDENCIES: pandas, numpy (same as the project's other research scripts).
"""
import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsgex_bfx_bot.analytics import apr as compute_apr  # noqa: E402
from tsgex_bfx_bot.analytics import earnings as compute_earnings  # noqa: E402
from tsgex_bfx_bot.analytics import overview as compute_overview  # noqa: E402
from tsgex_bfx_bot.config import StrategyConfig  # noqa: E402
from tsgex_bfx_bot.constants import TENOR_TYPICAL_ORDER_SIZE  # noqa: E402
from tsgex_bfx_bot.ledger import BotState, contribute_principal, reconcile_matured_positions, save_state  # noqa: E402
from tsgex_bfx_bot.mock_client import MockBitfinexClient  # noqa: E402
import tsgex_bfx_bot.runner as runner_mod  # noqa: E402

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
CAPITAL = 158_730.0  # NT$5,000,000 @ ~31.5 -- this project's standing worked-example scale
DEPTH_ORDERS = {2: 40, 30: 3}  # matches MockBitfinexClient's own liquidity-shape ratio (40:3)


def load(data_dir: Path, filename: str, series_name: str) -> pd.Series:
    df = pd.read_csv(data_dir / filename)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"])
    df = df.sort_values("timestamp_utc").drop_duplicates("timestamp_utc").set_index("timestamp_utc")
    return df["close"].rename(series_name)


class HistoricalFundingBook(MockBitfinexClient):
    """MockBitfinexClient's disclosed offer-lifecycle simulation (fill
    probability, submit/cancel, wallet balances) unchanged; only
    get_funding_book() is overridden to return the REAL historical rate at
    the current walk-forward cursor instead of a synthetic random walk."""

    def __init__(self, p2_rates: np.ndarray, p30_rates: np.ndarray, seed: int = 42):
        super().__init__(seed=seed)
        self._p2 = p2_rates
        self._p30 = p30_rates
        self._i = 0

    def set_index(self, i: int) -> None:
        self._i = i

    def get_funding_book(self, symbol: str, precision: str = "P0", length: int = 100):
        r2 = float(self._p2[self._i])
        r30 = float(self._p30[self._i])
        book = []
        for _ in range(DEPTH_ORDERS[2]):
            book.append([r2, 2, 1, TENOR_TYPICAL_ORDER_SIZE[2]])
        for _ in range(DEPTH_ORDERS[30]):
            book.append([r30, 30, 1, TENOR_TYPICAL_ORDER_SIZE[30]])
        return book


def run_backtest(mode: str, timestamps, p2_arr: np.ndarray, p30_arr: np.ndarray, tmp_dir: Path) -> dict:
    cfg = StrategyConfig(mode=mode, audit_log_path=None, state_path=str(tmp_dir / f"backtest_{mode}.json"))

    state = BotState()
    contribute_principal(state, CAPITAL)
    client = HistoricalFundingBook(p2_arr, p30_arr)
    rate_history = []

    real_save_state = runner_mod.save_state
    runner_mod.save_state = lambda *a, **kw: None
    t0 = time.time()
    n = len(timestamps)
    try:
        for i in range(n):
            client.set_index(i)
            runner_mod.run_cycle(client, cfg, state, rate_history, timestamps[i], live=False)
            if (i + 1) % 5000 == 0:
                print(f"    [{mode}] {i+1:,}/{n:,} cycles  "
                      f"({time.time()-t0:6.1f}s elapsed, {len(state.positions):,} positions so far)",
                      file=sys.stderr)
    finally:
        runner_mod.save_state = real_save_state

    reconcile_matured_positions(state, timestamps[-1])
    save_state(state, cfg.state_path)
    elapsed = time.time() - t0
    print(f"    [{mode}] done: {n:,} cycles in {elapsed:.1f}s, final position count = {len(state.positions):,}",
          file=sys.stderr)

    ov = compute_overview(state)
    ea = compute_earnings(state)
    ap = compute_apr(state, timestamps[-1])

    elapsed_days = (timestamps[-1] - timestamps[0]).total_seconds() / 86400.0
    terminal_wealth = ov["net_worth_estimate"]
    cagr = ((terminal_wealth / CAPITAL) ** (365.0 / elapsed_days) - 1.0) if elapsed_days > 0 else None

    matured = [p for p in state.positions if p.status == "matured"]
    cancelled = [p for p in state.positions if p.status == "cancelled"]
    fill_wait_hours = []
    for p in matured + [p for p in state.positions if p.status == "active"]:
        if p.filled_ts:
            wait_h = (pd.Timestamp(p.filled_ts) - pd.Timestamp(p.placed_ts)).total_seconds() / 3600
            fill_wait_hours.append(wait_h)

    return {
        "mode": mode, "elapsed_days": elapsed_days, "n_cycles": n, "wall_seconds": elapsed,
        "overview": ov, "earnings": ea, "apr": ap, "cagr": cagr,
        "position_count_total": len(state.positions), "matured_count": len(matured),
        "cancelled_stale_count": len(cancelled),
        "mean_fill_wait_hours": float(np.mean(fill_wait_hours)) if fill_wait_hours else None,
        "median_fill_wait_hours": float(np.median(fill_wait_hours)) if fill_wait_hours else None,
        "p90_fill_wait_hours": float(np.percentile(fill_wait_hours, 90)) if fill_wait_hours else None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=os.environ.get("BFX_RESEARCH_DATA_DIR", str(DEFAULT_DATA_DIR)))
    ap.add_argument("--modes", default="dave_high,dave_fast,barbell,frr")
    ap.add_argument("--tmp-dir", default="/tmp/tsgex_backtest_full5y")
    ap.add_argument("--limit-hours", type=int, default=None,
                     help="Debug/smoke-test only: truncate to the first N valid hours instead of the full history.")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    tmp_dir = Path(args.tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    p2 = load(data_dir, "funding_candles_fUSD_p2.csv", "p2")
    p30 = load(data_dir, "funding_candles_fUSD_p30.csv", "p30")

    idx = pd.date_range(p2.index.min(), p2.index.max(), freq="1h", tz="UTC")
    p2h = p2.reindex(idx).ffill(limit=6)
    p30h = p30.reindex(idx).ffill(limit=6)
    p2h = p2h.where((p2h >= 0) & (p2h < 0.01))
    p30h = p30h.where((p30h >= 0) & (p30h < 0.01))
    valid = p2h.notna() & p30h.notna()
    p2h, p30h = p2h[valid], p30h[valid]

    timestamps = list(p2h.index.to_pydatetime())
    p2_arr = p2h.to_numpy()
    p30_arr = p30h.to_numpy()
    if args.limit_hours:
        timestamps = timestamps[:args.limit_hours]
        p2_arr = p2_arr[:args.limit_hours]
        p30_arr = p30_arr[:args.limit_hours]
    n = len(timestamps)
    span_years = (timestamps[-1] - timestamps[0]).total_seconds() / 86400.0 / 365.0

    print("=" * 100)
    print(f"Full backtest window: {timestamps[0]} to {timestamps[-1]}  "
          f"({n:,} valid joint hourly observations, {span_years:.2f} years)")
    print(f"Capital: {CAPITAL:,.2f} USD (NT$5,000,000 worked-example scale)")
    print("=" * 100)

    modes = args.modes.split(",")
    all_results = []
    for mode in modes:
        print(f"\nRunning mode={mode} ...", file=sys.stderr)
        r = run_backtest(mode, timestamps, p2_arr, p30_arr, tmp_dir)
        all_results.append(r)

    print()
    print("=" * 100)
    print("RESULTS SUMMARY")
    print("=" * 100)
    header = (f"{'mode':<10} {'CAGR':>8} {'realized_apr':>13} {'cur_net_apr':>12} {'final_net_worth':>16} "
              f"{'realized_profit':>16} {'positions':>10} {'matured':>9} {'cancelled':>10} "
              f"{'mean_fill_h':>12} {'median_fill_h':>14} {'p90_fill_h':>11}")
    print(header)
    for r in all_results:
        cagr = r["cagr"]
        real_apr = r["apr"]["realized_apr"]
        cur_net = r["apr"]["current_weighted_net_apr"]
        print(f"{r['mode']:<10} "
              f"{(cagr*100 if cagr is not None else float('nan')):7.2f}% "
              f"{(real_apr*100 if real_apr is not None else float('nan')):12.2f}% "
              f"{(cur_net*100 if cur_net is not None else float('nan')):11.2f}% "
              f"{r['overview']['net_worth_estimate']:16,.2f} "
              f"{r['overview']['realized_profit_total']:16,.2f} "
              f"{r['position_count_total']:10,} "
              f"{r['matured_count']:9,} "
              f"{r['cancelled_stale_count']:10,} "
              f"{(r['mean_fill_wait_hours'] or float('nan')):12.2f} "
              f"{(r['median_fill_wait_hours'] or float('nan')):14.2f} "
              f"{(r['p90_fill_wait_hours'] or float('nan')):11.2f}")

    print()
    print("=" * 100)
    print("PER-MODE DETAIL")
    print("=" * 100)
    for r in all_results:
        print(f"\n--- {r['mode']} ---")
        print(f"  window: {r['elapsed_days']:.1f} days ({r['elapsed_days']/365:.2f} years), "
              f"{r['n_cycles']:,} hourly cycles, wall time {r['wall_seconds']:.1f}s")
        print(f"  overview: {r['overview']}")
        print(f"  apr: {r['apr']}")
        print(f"  earnings.profit_by_tenor: {r['earnings']['profit_by_tenor']}")
        print(f"  CAGR (terminal net worth vs contributed principal, geometric): "
              f"{r['cagr']*100 if r['cagr'] is not None else float('nan'):.3f}%")


if __name__ == "__main__":
    main()
