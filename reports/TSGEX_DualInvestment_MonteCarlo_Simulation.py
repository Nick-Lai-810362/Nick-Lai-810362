"""
Dual Investment year-long simulation v2.

Fixes vs v1:
1. Premium calibration was too low. v1 arbitrarily set ATM_RATE=100%.
   v2 does a proper 2-point fit to the user's OWN stated anchors:
   -1.5% OTM -> 50% annualized, -3% OTM -> 20% annualized.
   Solving rate(gap)=ATM*exp(-k*gap) for those two points gives
   ATM_RATE=125%, k=0.6109 (not 100%/0.4666 as guessed in v1).
   Sanity check: Black-Scholes fair value for a 7-day ATM option at
   55% annualized vol implies ~158% annualized premium, so 125% is
   still conservative relative to theoretical fair value, not inflated.

2. v1 blended two different things into one "annualized return" number:
   (a) paths that completed a full round-trip (converted to BTC, then
       converted back to USDT) within the year, and
   (b) paths still holding BTC at the year-end cutoff, marked to market
       at whatever the spot happened to be on day 365.
   For a driftless random walk, expected time-to-return to a fixed
   barrier is infinite (it's recurrent but not positive-recurrent), so
   a large share of "stuck" paths are still open at year-end through no
   fault of the strategy -- that's a duration/liquidity fact, not a
   realized loss. v2 reports these two populations SEPARATELY, plus the
   blended figure for reference, so it's clear which part of the
   negative average (if any) comes from real realized underperformance
   vs. from marking an unfinished position at an arbitrary cutoff date.
"""
import numpy as np

RNG = np.random.default_rng(20260906)

# --- calibrated via 2-point fit to user's stated anchors (-1.5%->50%, -3%->20%) ---
ATM_RATE = 1.25
DECAY_K = 0.6108604879161034

TENOR_DAYS = 7
CYCLES_PER_YEAR = 52
SIGMA_ANNUAL = 0.55
SPOT0 = 77000.0
N_PATHS = 20000


def rate_for_gap(gap_pct):
    g = max(gap_pct, 0.0)
    return ATM_RATE * np.exp(-DECAY_K * g)


def simulate_regime(regime, sigma_annual=SIGMA_ANNUAL, mu_annual=0.0, n_paths=N_PATHS, seed=None):
    rng = np.random.default_rng(seed) if seed is not None else RNG
    dt = TENOR_DAYS / 365.0
    sig_cycle = sigma_annual * np.sqrt(dt)

    final_multiples = np.zeros(n_paths)
    still_open = np.zeros(n_paths, dtype=bool)
    conversions_count = np.zeros(n_paths, dtype=int)
    stuck_cycles_count = np.zeros(n_paths, dtype=int)
    completed_roundtrip_returns = []   # for paths closed at year end AND that were stuck at least once
    never_stuck_returns = []           # paths that never converted at all (pure premium compounding)

    for p in range(n_paths):
        value = 1.0
        spot = SPOT0
        holding_btc = False
        locked_strike = None
        btc_qty = None
        was_ever_stuck = False

        for c in range(CYCLES_PER_YEAR):
            z = rng.standard_normal()
            mu_cycle = mu_annual * dt
            spot_next = spot * np.exp(mu_cycle - 0.5 * sig_cycle**2 + sig_cycle * z)

            if not holding_btc:
                if regime == "atm":
                    strike = spot
                else:
                    buffer_pct = rng.uniform(1.5, 3.0)
                    strike = spot * (1 - buffer_pct / 100.0)
                gap_pct = 0.0 if regime == "atm" else (spot - strike) / spot * 100.0
                rate = rate_for_gap(gap_pct)
                premium = value * rate * dt
                if spot_next < strike:
                    conversions_count[p] += 1
                    was_ever_stuck = True
                    btc_qty = (value + premium) / strike
                    locked_strike = strike
                    holding_btc = True
                    value = None
                else:
                    value = value + premium
            else:
                gap_pct = max((locked_strike - spot) / spot * 100.0, 0.0)
                rate = rate_for_gap(gap_pct)
                btc_value_now = btc_qty * spot
                premium_usd = btc_value_now * rate * dt
                btc_qty = btc_qty + premium_usd / spot
                stuck_cycles_count[p] += 1
                if spot_next >= locked_strike:
                    value = btc_qty * locked_strike
                    holding_btc = False
                    btc_qty = None
                    locked_strike = None

            spot = spot_next

        if holding_btc:
            value = btc_qty * spot
            still_open[p] = True
        final_multiples[p] = value

        if not still_open[p] and was_ever_stuck:
            completed_roundtrip_returns.append(value)
        if not was_ever_stuck:
            never_stuck_returns.append(value)

    return {
        "final_multiples": final_multiples,
        "still_open": still_open,
        "conversions_count": conversions_count,
        "stuck_cycles_count": stuck_cycles_count,
        "completed_roundtrip_returns": np.array(completed_roundtrip_returns),
        "never_stuck_returns": np.array(never_stuck_returns),
    }


def pctile_line(arr_pct):
    return (f"mean={arr_pct.mean():7.2f}%  median={np.median(arr_pct):7.2f}%  "
            f"P5={np.percentile(arr_pct,5):7.2f}%  P95={np.percentile(arr_pct,95):7.2f}%  "
            f"P(loss)={(arr_pct<0).mean()*100:5.1f}%  n={len(arr_pct)}")


def summarize(label, result):
    fm = result["final_multiples"]
    ann = (fm - 1.0) * 100.0
    print(f"\n=== {label} ===")
    print(f"  [Blended, ALL paths]              {pctile_line(ann)}")

    open_mask = result["still_open"]
    closed_ann = (fm[~open_mask] - 1.0) * 100.0
    open_ann = (fm[open_mask] - 1.0) * 100.0
    print(f"  [Closed by year-end, n={open_mask.size - open_mask.sum()}]     "
          f"share={ (~open_mask).mean()*100:5.1f}%   {pctile_line(closed_ann)}")
    print(f"  [Still open @ year-end, n={open_mask.sum()}]  "
          f"share={ open_mask.mean()*100:5.1f}%   {pctile_line(open_ann)}")

    nvr = result["never_stuck_returns"]
    if len(nvr):
        nvr_ann = (nvr - 1.0) * 100.0
        print(f"  [Never got stuck at all, n={len(nvr)}]    {pctile_line(nvr_ann)}")

    crt = result["completed_roundtrip_returns"]
    if len(crt):
        crt_ann = (crt - 1.0) * 100.0
        print(f"  [Completed >=1 round-trip & closed by year-end] {pctile_line(crt_ann)}")

    print(f"  Avg conversions/year: {result['conversions_count'].mean():.2f}   "
          f"Avg cycles stuck/year: {result['stuck_cycles_count'].mean():.2f} (of {CYCLES_PER_YEAR})")


if __name__ == "__main__":
    print(f"Calibration: ATM_RATE={ATM_RATE:.0%}, decay_k={DECAY_K:.4f} "
          f"(2-point fit to user's own -1.5%->50%, -3%->20% anchors)")
    print(f"Sanity: gap=0->{rate_for_gap(0):.1%}  1.5->{rate_for_gap(1.5):.1%}  "
          f"3->{rate_for_gap(3):.1%}  5->{rate_for_gap(5):.1%}  10->{rate_for_gap(10):.1%}")
    print(f"Spot=${SPOT0:,.0f}  sigma={SIGMA_ANNUAL:.0%}  tenor={TENOR_DAYS}d  "
          f"cycles/yr={CYCLES_PER_YEAR}  paths={N_PATHS}")

    res_atm = simulate_regime("atm", seed=1001)
    res_otm = simulate_regime("otm_buffer", seed=1002)
    summarize("Regime 1: 最高收益 (ATM)", res_atm)
    summarize("Regime 2: 不被轉換 (OTM buffer -1.5%~-3%)", res_otm)

    print("\n--- Sensitivity: volatility (drift=0) ---")
    for sigma in [0.36, 0.80]:
        r1 = simulate_regime("atm", sigma_annual=sigma, n_paths=10000, seed=2001)
        r2 = simulate_regime("otm_buffer", sigma_annual=sigma, n_paths=10000, seed=2002)
        summarize(f"[sigma={sigma:.0%}] Regime 1 ATM", r1)
        summarize(f"[sigma={sigma:.0%}] Regime 2 OTM buffer", r2)

    print("\n--- Sensitivity: drift (sigma=55%) ---")
    for mu in [0.30, -0.30]:
        r1 = simulate_regime("atm", mu_annual=mu, n_paths=10000, seed=3001)
        r2 = simulate_regime("otm_buffer", mu_annual=mu, n_paths=10000, seed=3002)
        summarize(f"[drift={mu:+.0%}] Regime 1 ATM", r1)
        summarize(f"[drift={mu:+.0%}] Regime 2 OTM buffer", r2)
