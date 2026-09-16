"""
Honest backtest: does the bot's spike-proxy signal (fast6/slow24 MA
crossover, exactly as implemented in strategy.compute_spike_signal) or the
observed 2d->30d term premium actually predict anything about FUTURE rates?

Same rigor as the earlier BTC technical-analysis backtest in this project:
- real 5-year hourly data, no synthetic simulation
- chronological split-half (fit expectations on first half, confirm on
  second half held out) to guard against data-snooping
- compared against a naive "no change" baseline
- report negative results as plainly as positive ones

DATA: research/data/funding_candles_fUSD_p2.csv and _p30.csv, committed
alongside this script for reproducibility. Collected 2026-09-07 via
TSGEX_Bitfinex_Funding_History_Collector.py (5 years of hourly Bitfinex
fUSD funding-rate candles at the 2-day and 30-day tenor buckets). Override
the location with --data-dir or the BFX_RESEARCH_DATA_DIR env var if you
have a fresher pull you want to re-run this against.

DEPENDENCIES: pandas, numpy (`pip install pandas numpy`).

USAGE: python backtest_spike_and_premium.py [--data-dir PATH]
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


def load(data_dir: Path, filename: str, series_name: str):
    df = pd.read_csv(data_dir / filename)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"])
    df = df.sort_values("timestamp_utc").drop_duplicates("timestamp_utc").set_index("timestamp_utc")
    return df["close"].rename(series_name)


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--data-dir", default=os.environ.get("BFX_RESEARCH_DATA_DIR", str(DEFAULT_DATA_DIR)),
                 help=f"Directory containing funding_candles_fUSD_p2.csv and _p30.csv (default: {DEFAULT_DATA_DIR})")
args = ap.parse_args()
data_dir = Path(args.data_dir)

p2 = load(data_dir, "funding_candles_fUSD_p2.csv", "p2")
p30 = load(data_dir, "funding_candles_fUSD_p30.csv", "p30")

# hourly grid, forward-filled up to 6h gaps (thin market -> some hours have no trade)
idx = pd.date_range(p2.index.min(), p2.index.max(), freq="1h", tz="UTC")
p2h = p2.reindex(idx).ffill(limit=6)
p30h = p30.reindex(idx).ffill(limit=6)

# drop the absurd outlier ticks (>1%/day = >365% APR, bad prints) as done before
p2h = p2h.where((p2h >= 0) & (p2h < 0.01))
p30h = p30h.where((p30h >= 0) & (p30h < 0.01))

apr2 = p2h * 365 * 100   # percentage points, e.g. 7.3 means 7.3% APR
apr30 = p30h * 365 * 100

# ---------------------------------------------------------------------------
# TEST 1: the bot's exact spike-proxy signal (compute_spike_signal:
# fast MA(6) > slow MA(24) of the observed rate). Does firing predict a
# real subsequent rate INCREASE, which is what dave_high mode assumes when
# it reserves capital "for an anticipated rate increase"?
# ---------------------------------------------------------------------------
fast = apr2.rolling(6).mean()
slow = apr2.rolling(24).mean()
spike = (fast > slow)

results = []
for horizon_h, label in [(24, "+24h"), (168, "+7d")]:
    fwd_change = apr2.shift(-horizon_h) - apr2
    df = pd.DataFrame({"spike": spike, "fwd_change": fwd_change}).dropna()
    mid = df.index[len(df)//2]
    first_half, second_half = df[df.index < mid], df[df.index >= mid]
    for label_half, sub in [("first half (in-sample)", first_half), ("second half (out-of-sample)", second_half)]:
        on = sub[sub.spike]["fwd_change"]
        off = sub[~sub.spike]["fwd_change"]
        results.append({
            "test": "spike_signal", "horizon": label, "half": label_half,
            "n_on": len(on), "n_off": len(off),
            "mean_fwd_change_when_on_pp": on.mean(),
            "mean_fwd_change_when_off_pp": off.mean(),
            "median_on_pp": on.median(), "median_off_pp": off.median(),
        })

print("="*100)
print("TEST 1: spike_signal (fast6>slow24 MA crossover) vs forward APR change (percentage points)")
print("="*100)
for r in results:
    print(f"[{r['horizon']:>4}] {r['half']:<28}  n_on={r['n_on']:>6} n_off={r['n_off']:>6}  "
          f"mean_change|ON={r['mean_fwd_change_when_on_pp']:+7.3f}pp  mean_change|OFF={r['mean_fwd_change_when_off_pp']:+7.3f}pp  "
          f"median|ON={r['median_on_pp']:+7.3f}pp  median|OFF={r['median_off_pp']:+7.3f}pp")

# ---------------------------------------------------------------------------
# TEST 2: does the CURRENT observed term premium (p30 - p2, what
# decide_tenor_allocation reads live) predict the premium PERSISTS long
# enough to be worth locking capital into 30d? Compare premium now vs
# premium N days later.
# ---------------------------------------------------------------------------
premium_now = apr30 - apr2
print()
print("="*100)
print("TEST 2: does the current term premium predict the FUTURE premium (persistence)?")
print("="*100)
for horizon_d, label in [(7, "+7d"), (14, "+14d"), (30, "+30d")]:
    h = horizon_d * 24
    premium_future = (apr30 - apr2).shift(-h)
    df = pd.DataFrame({"now": premium_now, "future": premium_future}).dropna()
    mid = df.index[len(df)//2]
    first_half, second_half = df[df.index < mid], df[df.index >= mid]
    for label_half, sub in [("in-sample", first_half), ("out-of-sample", second_half)]:
        # bucket by whether premium_now clears the bot's own 2pp threshold
        cleared = sub[sub["now"] >= 2.0]
        not_cleared = sub[sub["now"] < 2.0]
        corr = sub["now"].corr(sub["future"]) if len(sub) > 10 else float("nan")
        print(f"[{label:>4}] {label_half:<15}  n={len(sub):>6}  corr(now,future)={corr:+.3f}  "
              f"when now>=2pp: future_mean={cleared['future'].mean():+6.2f}pp (n={len(cleared)})  "
              f"when now<2pp: future_mean={not_cleared['future'].mean():+6.2f}pp (n={len(not_cleared)})")

# ---------------------------------------------------------------------------
# TEST 3: baseline comparison -- does ANYTHING beat naive persistence for
# predicting the future 2d rate level itself (not the spike signal
# specifically)? Same standard as the earlier BTC TA test: compare model MAE
# vs "predict no change" MAE.
# ---------------------------------------------------------------------------
print()
print("="*100)
print("TEST 3: forecasting the future 2d rate level -- spike-signal-conditioned mean vs naive persistence")
print("="*100)
for horizon_h, label in [(24, "+24h"), (168, "+7d")]:
    fwd = apr2.shift(-horizon_h)
    df = pd.DataFrame({"now": apr2, "fwd": fwd, "spike": spike}).dropna()
    mid = df.index[len(df)//2]
    train, test = df[df.index < mid], df[df.index >= mid]
    # "model": persistence + the spike-conditioned mean shift learned on train
    shift_on = train[train.spike]["fwd"].sub(train[train.spike]["now"]).mean()
    shift_off = train[~train.spike]["fwd"].sub(train[~train.spike]["now"]).mean()
    pred = test["now"] + np.where(test["spike"], shift_on, shift_off)
    mae_model = (pred - test["fwd"]).abs().mean()
    mae_naive = (test["now"] - test["fwd"]).abs().mean()
    print(f"[{label:>4}] naive-persistence MAE={mae_naive:6.3f}pp   "
          f"spike-conditioned MAE={mae_model:6.3f}pp   "
          f"improvement={ (mae_naive-mae_model)/mae_naive*100:+5.1f}%")
