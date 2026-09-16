"""
Answers a direct follow-up to the v5.7 full 5-year backtest: how much of
dave_high's 28.80%/yr CAGR is being carried by the 2021 rate spike embedded
in the window, versus what a more "normal" year looks like?

Reuses the exact same real run_cycle() walk-forward machinery as
backtest_full_5year.py (same HistoricalFundingBook, same real fUSD p2/p30
data, same cleaning, same disclosed fill-probability heuristic) -- this is
not a re-derivation, just an added checkpoint: net worth is recorded at
every UTC calendar-year boundary the walk-forward crosses, in ADDITION to
running the whole thing a second time starting from 2022-01-01 (i.e. with
the 2021 portion of the data dropped entirely) for a clean "what if I had
started lending after the 2021 spike" comparison number.

USAGE: python backtest_year_by_year.py [--data-dir PATH]
"""
import argparse
import os
import sys
import time
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsgex_bfx_bot.analytics import overview as compute_overview  # noqa: E402
from tsgex_bfx_bot.config import StrategyConfig  # noqa: E402
from tsgex_bfx_bot.ledger import BotState, contribute_principal, reconcile_matured_positions, save_state  # noqa: E402
import tsgex_bfx_bot.runner as runner_mod  # noqa: E402

from backtest_full_5year import CAPITAL, DEFAULT_DATA_DIR, HistoricalFundingBook, load  # noqa: E402


def run_with_year_checkpoints(timestamps, p2_arr, p30_arr, tmp_dir: Path, label: str) -> list:
    cfg = StrategyConfig(mode="dave_high", audit_log_path=None, state_path=str(tmp_dir / f"yby_{label}.json"))
    state = BotState()
    contribute_principal(state, CAPITAL)
    client = HistoricalFundingBook(p2_arr, p30_arr)
    rate_history = []

    checkpoints = [{"ts": timestamps[0], "year_label": f"start ({timestamps[0].date()})",
                     "net_worth": CAPITAL}]
    current_year = timestamps[0].year

    real_save_state = runner_mod.save_state
    runner_mod.save_state = lambda *a, **kw: None
    t0 = time.time()
    n = len(timestamps)
    try:
        for i in range(n):
            client.set_index(i)
            runner_mod.run_cycle(client, cfg, state, rate_history, timestamps[i], live=False)
            if timestamps[i].year != current_year:
                nw = compute_overview(state)["net_worth_estimate"]
                checkpoints.append({"ts": timestamps[i], "year_label": str(current_year), "net_worth": nw})
                current_year = timestamps[i].year
            if (i + 1) % 10000 == 0:
                print(f"    [{label}] {i+1:,}/{n:,} cycles ({time.time()-t0:.1f}s)", file=sys.stderr)
    finally:
        runner_mod.save_state = real_save_state

    reconcile_matured_positions(state, timestamps[-1])
    save_state(state, cfg.state_path)
    final_nw = compute_overview(state)["net_worth_estimate"]
    checkpoints.append({"ts": timestamps[-1], "year_label": f"end ({timestamps[-1].date()})", "net_worth": final_nw})
    print(f"    [{label}] done: {n:,} cycles in {time.time()-t0:.1f}s", file=sys.stderr)
    return checkpoints


def print_checkpoint_table(checkpoints: list, title: str):
    print("=" * 100)
    print(title)
    print("=" * 100)
    print(f"{'period':<28} {'net worth at end of period':>28} {'period days':>12} {'period simple return':>22} "
          f"{'period annualized':>19}")
    for i in range(1, len(checkpoints)):
        prev, cur = checkpoints[i - 1], checkpoints[i]
        days = (cur["ts"] - prev["ts"]).total_seconds() / 86400.0
        simple_return = cur["net_worth"] / prev["net_worth"] - 1.0
        annualized = (cur["net_worth"] / prev["net_worth"]) ** (365.0 / days) - 1.0 if days > 0 else float("nan")
        label = cur["year_label"] if not cur["year_label"].startswith(("start", "end")) else \
            f"{prev['ts'].date()} -> {cur['ts'].date()}"
        print(f"{label:<28} {cur['net_worth']:28,.2f} {days:12.1f} {simple_return*100:21.2f}% {annualized*100:18.2f}%")
    total_days = (checkpoints[-1]["ts"] - checkpoints[0]["ts"]).total_seconds() / 86400.0
    total_cagr = (checkpoints[-1]["net_worth"] / checkpoints[0]["net_worth"]) ** (365.0 / total_days) - 1.0
    print(f"{'WHOLE WINDOW':<28} {checkpoints[-1]['net_worth']:28,.2f} {total_days:12.1f} "
          f"{(checkpoints[-1]['net_worth']/checkpoints[0]['net_worth']-1)*100:21.2f}% {total_cagr*100:18.2f}%")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=os.environ.get("BFX_RESEARCH_DATA_DIR", str(DEFAULT_DATA_DIR)))
    ap.add_argument("--tmp-dir", default="/tmp/tsgex_backtest_yby")
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

    timestamps_full = list(p2h.index.to_pydatetime())
    p2_arr_full = p2h.to_numpy()
    p30_arr_full = p30h.to_numpy()

    print(f"Full window: {timestamps_full[0]} to {timestamps_full[-1]} ({len(timestamps_full):,} hours)\n")

    print("Running FULL window (same as v5.7) with year-boundary checkpoints...", file=sys.stderr)
    cps_full = run_with_year_checkpoints(timestamps_full, p2_arr_full, p30_arr_full, tmp_dir, "full")
    print_checkpoint_table(cps_full, "dave_high, FULL WINDOW (2021-08-23 onward, includes the 2021 spike) -- year by year")

    # Second pass: drop everything before 2022-01-01 entirely.
    cutoff = pd.Timestamp("2022-01-01", tz="UTC").to_pydatetime()
    start_idx = next(i for i, t in enumerate(timestamps_full) if t >= cutoff)
    timestamps_post2021 = timestamps_full[start_idx:]
    p2_arr_post2021 = p2_arr_full[start_idx:]
    p30_arr_post2021 = p30_arr_full[start_idx:]
    print(f"Post-2021 window: {timestamps_post2021[0]} to {timestamps_post2021[-1]} "
          f"({len(timestamps_post2021):,} hours)\n", file=sys.stderr)

    print("Running POST-2021 window (starts 2022-01-01, 2021 spike fully excluded)...", file=sys.stderr)
    cps_post2021 = run_with_year_checkpoints(timestamps_post2021, p2_arr_post2021, p30_arr_post2021, tmp_dir,
                                              "post2021")
    print_checkpoint_table(cps_post2021, "dave_high, POST-2021 WINDOW ONLY (2022-01-01 onward) -- year by year")

    full_cagr = (cps_full[-1]["net_worth"] / cps_full[0]["net_worth"]) ** \
        (365.0 / (cps_full[-1]["ts"] - cps_full[0]["ts"]).total_seconds() * 86400.0) - 1.0
    post_cagr = (cps_post2021[-1]["net_worth"] / cps_post2021[0]["net_worth"]) ** \
        (365.0 / (cps_post2021[-1]["ts"] - cps_post2021[0]["ts"]).total_seconds() * 86400.0) - 1.0
    print("=" * 100)
    print("HEADLINE COMPARISON")
    print("=" * 100)
    print(f"Full window CAGR (2021-08-23 -> 2026-09-07, includes 2021 spike): {full_cagr*100:.2f}%/yr")
    print(f"Post-2021 CAGR   (2022-01-01 -> 2026-09-07, spike excluded):      {post_cagr*100:.2f}%/yr")


if __name__ == "__main__":
    main()
