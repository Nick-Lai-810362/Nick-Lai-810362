"""
Answers the user's question: how do you get the highest annualized return
WITHOUT sacrificing capital utilization? Splits the question into its two
genuinely separate halves and is honest about which one real data can answer
and which one can't.

PART A -- RETURN vs. term_premium_min_pp (real data, rigorous):
Uses the same real 5-year hourly fUSD p2/p30 rate series as CHANGELOG.md
"v5.1" (research/data/funding_candles_fUSD_p2.csv / _p30.csv) to replay
strategy.decide_tenor_allocation() at every real historical hour under a grid
of term_premium_min_pp values, and measures the resulting blended net APR --
assuming full, instant fill (i.e. this isolates the RETURN side of the
tradeoff from the fill/utilization side; see Part B for why they can't be
combined into one honest number). Chronological split-half (fit habits on
the first half, confirm on the held-out second half) exactly like the prior
backtest, so a result that only "works" in-sample is visible as such.

PART B -- UTILIZATION vs. stale-order settings (mock simulation, disclosed
heuristic, NOT real data): Bitfinex's REST API has no historical order-book
or fill-latency endpoint (same limitation disclosed throughout this
project -- see CHANGELOG.md "v5.0"), so there is no real data to backtest
fill probability against. This part instead runs the bot's own real
run_cycle()/ledger code against MockBitfinexClient's disclosed per-tenor
fill-probability heuristic, sweeping --max-wait-multiplier and
--rate-drift-threshold-pp, and measures average committed-capital fraction
(utilization) over many simulated cycles. This is a legitimate mechanical
test of how the code's own stale-order logic responds to those settings,
but the absolute utilization numbers it produces are only as good as the
MOCK fill-probability assumption -- do not read them as a real-world
utilization forecast, only as directional evidence for which way each knob
pushes utilization.

USAGE: python param_sweep_utilization_vs_return.py [--data-dir PATH]
DEPENDENCIES: pandas, numpy (same as backtest_spike_and_premium.py).
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsgex_bfx_bot.config import StrategyConfig, net_apr  # noqa: E402
from tsgex_bfx_bot.ledger import BotState, contribute_principal  # noqa: E402
from tsgex_bfx_bot.mock_client import MockBitfinexClient  # noqa: E402
from tsgex_bfx_bot.runner import run_cycle  # noqa: E402
from tsgex_bfx_bot.strategy import decide_tenor_allocation  # noqa: E402

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


def load(data_dir: Path, filename: str, series_name: str):
    df = pd.read_csv(data_dir / filename)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"])
    df = df.sort_values("timestamp_utc").drop_duplicates("timestamp_utc").set_index("timestamp_utc")
    return df["close"].rename(series_name)


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--data-dir", default=os.environ.get("BFX_RESEARCH_DATA_DIR", str(DEFAULT_DATA_DIR)))
args = ap.parse_args()
data_dir = Path(args.data_dir)

p2 = load(data_dir, "funding_candles_fUSD_p2.csv", "p2")
p30 = load(data_dir, "funding_candles_fUSD_p30.csv", "p30")

idx = pd.date_range(p2.index.min(), p2.index.max(), freq="1h", tz="UTC")
p2h = p2.reindex(idx).ffill(limit=6)
p30h = p30.reindex(idx).ffill(limit=6)
p2h = p2h.where((p2h >= 0) & (p2h < 0.01))
p30h = p30h.where((p30h >= 0) & (p30h < 0.01))
valid = p2h.notna() & p30h.notna()
p2h, p30h = p2h[valid], p30h[valid]

print("=" * 100)
print(f"PART A: blended net APR vs. term_premium_min_pp, replayed against {len(p2h):,} real hourly "
      f"fUSD p2/p30 observations ({p2h.index.min()} to {p2h.index.max()})")
print("=" * 100)

FEE = 0.15  # standard visibility, matches StrategyConfig default
GRID = [0.0, 0.005, 0.01, 0.02, 0.0365, 0.05, 0.08]  # 0.02=current default; 0.0365=the v4-measured 5yr median premium

mid = len(p2h) // 2
halves = {"in-sample (first half)": slice(0, mid), "out-of-sample (second half)": slice(mid, None)}

results = []
for thresh in GRID:
    cfg = StrategyConfig(term_premium_min_pp=thresh, max_total_shift_from_short=0.7)
    blended = np.empty(len(p2h))
    weight_30d = np.empty(len(p2h))
    p2_arr, p30_arr = p2h.to_numpy(), p30h.to_numpy()
    for i in range(len(p2h)):
        alloc = decide_tenor_allocation({2: p2_arr[i], 30: p30_arr[i]}, cfg, depth=None)
        net2, net30 = net_apr(p2_arr[i] * 365, cfg), net_apr(p30_arr[i] * 365, cfg)
        blended[i] = alloc.get(2, 0.0) * net2 + alloc.get(30, 0.0) * net30
        weight_30d[i] = alloc.get(30, 0.0)
    always_short = net_apr(p2_arr * 365, cfg)
    for half_name, sl in halves.items():
        results.append({
            "term_premium_min_pp": thresh, "half": half_name,
            "mean_blended_net_apr": blended[sl].mean(),
            "mean_always_2d_net_apr": always_short[sl].mean(),
            "mean_weight_on_30d": weight_30d[sl].mean(),
            "n": (sl.stop or len(p2h)) - (sl.start or 0),
        })

for r in results:
    lift_pp = (r["mean_blended_net_apr"] - r["mean_always_2d_net_apr"]) * 100
    print(f"thresh={r['term_premium_min_pp']:.4f}  {r['half']:<28}  n={r['n']:>6}  "
          f"blended_net_apr={r['mean_blended_net_apr']*100:6.2f}%  "
          f"always_2d_net_apr={r['mean_always_2d_net_apr']*100:6.2f}%  "
          f"lift={lift_pp:+5.2f}pp  mean_weight_on_30d={r['mean_weight_on_30d']*100:5.1f}%")

print()
print("=" * 100)
print("PART B: utilization vs. stale-order settings -- MOCK SIMULATION, disclosed fill-probability "
      "heuristic (MockBitfinexClient.FILL_PROB_PER_CYCLE), NOT real fill data. Directional only.")
print("=" * 100)

WAIT_GRID = [0.5, 1.0, 1.5, 2.0]
DRIFT_GRID = [0.005, 0.01, 0.02, 0.04]
CAPITAL = 100_000.0
CYCLES = 60
STEP_HOURS = 6

util_results = []
for wait_mult in WAIT_GRID:
    for drift in DRIFT_GRID:
        cfg = StrategyConfig(mode="custom", max_wait_multiplier=wait_mult, rate_drift_threshold_pp=drift,
                              state_path="/tmp/_never_used_sweep.json", audit_log_path=None)
        state = BotState()
        contribute_principal(state, CAPITAL)
        client = MockBitfinexClient(seed=42)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rate_history = []
        active_fracs = []
        pending_fracs = []
        for i in range(CYCLES):
            run_cycle(client, cfg, state, rate_history, now, live=False)
            now += timedelta(hours=STEP_HOURS)
            if i >= 5:  # skip the initial ramp-up before steady state
                active = sum(p.amount for p in state.positions if p.status == "active")
                pending = sum(p.amount for p in state.positions if p.status == "pending")
                active_fracs.append(active / CAPITAL)
                pending_fracs.append(pending / CAPITAL)
        util_results.append({
            "max_wait_multiplier": wait_mult, "rate_drift_threshold_pp": drift,
            "mean_active_fraction": float(np.mean(active_fracs)),  # EARNING interest -- the real utilization metric
            "mean_pending_fraction": float(np.mean(pending_fracs)),  # capital committed but NOT yet earning
            "cancelled_stale_total": sum(1 for p in state.positions if p.status == "cancelled"),
        })

print(f"{'wait_mult':>10}  {'drift_pp':>9}  {'active_(earning)':>17}  {'pending_(locked,idle)':>22}  {'cancelled_stale_total':>22}")
for r in util_results:
    print(f"{r['max_wait_multiplier']:>10.2f}  {r['rate_drift_threshold_pp']:>9.3f}  "
          f"{r['mean_active_fraction']*100:>16.1f}%  {r['mean_pending_fraction']*100:>21.1f}%  "
          f"{r['cancelled_stale_total']:>22}")
