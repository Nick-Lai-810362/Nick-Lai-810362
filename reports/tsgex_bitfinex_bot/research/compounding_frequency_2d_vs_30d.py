"""
Validates the core premise behind the new "jump" mode (v5.5) before baking it
into the strategy: does continuously re-lending at the liquid 2-day tenor
actually out-compound parking capital at 30-day, using REAL rate data and a
REAL (non-overlapping) compounding simulation -- not the hourly hold-forever
ceiling from research/param_sweep_utilization_vs_return.py, which measured a
snapshot blend, not compounded terminal wealth.

Method: resample each series at ITS OWN natural period (every 2 days for
p2, every 30 days for p30 -- i.e. exactly when a real position matures and
must be re-lent), take the real quoted daily_rate at that instant, and
compound net-of-fee simple interest forward across the full ~5-year span.
This mirrors what actually happens on the exchange: interest per period is
SIMPLE (rate * days), but capital compounds ACROSS periods as it's relent.

USAGE: python compounding_frequency_2d_vs_30d.py [--data-dir PATH]
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tsgex_bfx_bot.config import StrategyConfig, net_apr  # noqa: E402

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
cfg = StrategyConfig()  # default 15% standard fee

def compound(series: pd.Series, tenor_days: int):
    """Resample at the tenor's own natural period, take the real rate at
    each maturity boundary, and compound net-of-fee simple interest forward.
    Skips any period where the real data has no quote (thin-liquidity gaps),
    rather than fabricating a fill."""
    idx = pd.date_range(series.index.min(), series.index.max(), freq=f"{tenor_days}D", tz="UTC")
    at_maturity = series.reindex(idx, method="nearest", tolerance=pd.Timedelta(hours=12))
    at_maturity = at_maturity.where((at_maturity >= 0) & (at_maturity < 0.01)).dropna()
    wealth = 1.0
    for daily_rate in at_maturity.to_numpy():
        gross_apr = daily_rate * 365
        net = net_apr(gross_apr, cfg)
        wealth *= (1 + net * tenor_days / 365)
    years = (at_maturity.index[-1] - at_maturity.index[0]).days / 365.25
    annualized = wealth ** (1 / years) - 1
    return wealth, annualized, len(at_maturity), years


print("=" * 100)
print("Real compounded terminal wealth: continuously re-lending at 2d vs. 30d, net-of-fee, real fUSD rates")
print("=" * 100)
for tenor, series, label in [(2, p2, "2d (jump mode candidate)"), (30, p30, "30d (park-and-wait)")]:
    wealth, annualized, n, years = compound(series, tenor)
    print(f"{label:<28}  n_periods={n:>4}  span={years:.2f}y  terminal_wealth_multiple={wealth:.3f}x  "
          f"geometric_annualized_net_return={annualized*100:6.2f}%")
