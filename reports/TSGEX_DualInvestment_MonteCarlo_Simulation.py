"""
Dual Investment year-long simulation.

Two operating rules, both using ONE unified premium-decay formula:
    rate(gap%) = ATM_RATE * exp(-DECAY_K * gap%)
This is calibrated so it reproduces the user-specified 20%-50% annualized
band at a -1.5%~-3% OTM distance, and also governs how the rate decays
once a position gets "stuck" holding BTC below the locked conversion price
(the "wheel" mechanic from the prior analysis).

Regime 1 ("最高收益 / nearest-strike"): every cycle, strike = spot (ATM, gap=0%).
Regime 2 ("不被轉換 / OTM buffer"): every cycle, strike = spot * (1 - buffer),
    buffer ~ Uniform(1.5%, 3%).

Both regimes use IDENTICAL wheel logic once converted to BTC: keep the locked
strike, keep selling "Sell High" at that same strike, rate decays with the
gap between spot and the locked strike, until price reverts and it converts
back to USDT (restoring nominal value at the locked strike + all premium
collected while stuck).

Price model: BTC as GBM, zero drift (deliberately no market forecast),
annualized volatility sigma sampled per-cycle from historical/implied vol
context (DVOL normal range ~50-65%, base case 55%).
"""
import numpy as np

RNG = np.random.default_rng(20260905)

ATM_RATE = 1.00      # 100% annualized at gap=0 (ATM), see calibration note below
DECAY_K = 0.4666      # calibrated: rate(2.25%) ~= 35% (midpoint of user's 20-50% band)
TENOR_DAYS = 7
CYCLES_PER_YEAR = 52
SIGMA_ANNUAL = 0.55   # base case, mid of Deribit DVOL "normal" 50-65% range (Sept 2026 context)
SPOT0 = 77000.0
N_PATHS = 20000


def rate_for_gap(gap_pct):
    """gap_pct: percentage distance OTM (>=0 expected; negative clipped to 0 i.e. treated as ATM/ITM)."""
    g = max(gap_pct, 0.0)
    return ATM_RATE * np.exp(-DECAY_K * g)


def simulate_regime(regime, sigma_annual=SIGMA_ANNUAL, mu_annual=0.0, n_paths=N_PATHS, seed=None):
    """
    regime: 'atm' (Regime 1) or 'otm_buffer' (Regime 2)
    Returns: array of ending total-return multiples (final_value / 1.0), one per path,
             plus diagnostic counters.
    """
    rng = np.random.default_rng(seed) if seed is not None else RNG
    dt = TENOR_DAYS / 365.0
    sig_cycle = sigma_annual * np.sqrt(dt)

    final_multiples = np.zeros(n_paths)
    conversions_count = np.zeros(n_paths, dtype=int)
    stuck_cycles_count = np.zeros(n_paths, dtype=int)
    ever_stuck = np.zeros(n_paths, dtype=bool)

    for p in range(n_paths):
        value = 1.0          # normalized starting principal = 1.0 (USDT)
        spot = SPOT0
        holding_btc = False
        locked_strike = None
        btc_qty = None        # only meaningful while holding_btc

        for c in range(CYCLES_PER_YEAR):
            # simulate this cycle's BTC log-return (zero drift GBM)
            z = rng.standard_normal()
            mu_cycle = mu_annual * dt
            spot_next = spot * np.exp(mu_cycle - 0.5 * sig_cycle**2 + sig_cycle * z)

            if not holding_btc:
                if regime == "atm":
                    strike = spot  # gap = 0%
                else:  # otm_buffer
                    buffer_pct = rng.uniform(1.5, 3.0)
                    strike = spot * (1 - buffer_pct / 100.0)
                gap_pct = 0.0 if regime == "atm" else (spot - strike) / spot * 100.0
                rate = rate_for_gap(gap_pct)
                premium = value * rate * dt
                if spot_next < strike:
                    # converted: principal (incl. this cycle's premium) becomes BTC at strike
                    conversions_count[p] += 1
                    btc_qty = (value + premium) / strike
                    locked_strike = strike
                    holding_btc = True
                    value = None  # tracked via btc_qty while holding BTC
                else:
                    value = value + premium
            else:
                gap_pct = max((locked_strike - spot) / spot * 100.0, 0.0)
                rate = rate_for_gap(gap_pct)
                btc_value_now = btc_qty * spot
                premium_usd = btc_value_now * rate * dt
                btc_qty = btc_qty + premium_usd / spot  # premium credited as extra BTC
                stuck_cycles_count[p] += 1
                ever_stuck[p] = True
                if spot_next >= locked_strike:
                    # converts back: BTC (incl. accumulated premium-BTC) -> USDT at locked strike
                    value = btc_qty * locked_strike
                    holding_btc = False
                    btc_qty = None
                    locked_strike = None
                # else: stays in BTC, continue next cycle with same locked_strike

            spot = spot_next

        if holding_btc:
            # mark-to-market at year end if still stuck (unrealized)
            value = btc_qty * spot

        final_multiples[p] = value

    return {
        "final_multiples": final_multiples,
        "conversions_count": conversions_count,
        "stuck_cycles_count": stuck_cycles_count,
        "ever_stuck": ever_stuck,
    }


def summarize(label, result):
    fm = result["final_multiples"]
    annual_return_pct = (fm - 1.0) * 100.0
    pct = lambda q: np.percentile(annual_return_pct, q)
    print(f"\n=== {label} ===")
    print(f"  Mean annual return:      {annual_return_pct.mean():7.2f}%")
    print(f"  Median annual return:    {np.median(annual_return_pct):7.2f}%")
    print(f"  P5  / P25:               {pct(5):7.2f}% / {pct(25):7.2f}%")
    print(f"  P75 / P95:               {pct(75):7.2f}% / {pct(95):7.2f}%")
    print(f"  Min / Max:               {annual_return_pct.min():7.2f}% / {annual_return_pct.max():7.2f}%")
    print(f"  P(loss vs principal):    {(fm < 1.0).mean()*100:6.2f}%")
    print(f"  P(ever stuck in BTC):    {result['ever_stuck'].mean()*100:6.2f}%")
    print(f"  Avg conversions/year:    {result['conversions_count'].mean():5.2f}")
    print(f"  Avg cycles stuck/year:   {result['stuck_cycles_count'].mean():5.2f} (of {CYCLES_PER_YEAR})")
    return {
        "mean": annual_return_pct.mean(),
        "median": np.median(annual_return_pct),
        "p5": pct(5), "p25": pct(25), "p75": pct(75), "p95": pct(95),
        "min": annual_return_pct.min(), "max": annual_return_pct.max(),
        "p_loss": (fm < 1.0).mean() * 100,
        "p_ever_stuck": result["ever_stuck"].mean() * 100,
        "avg_conversions": result["conversions_count"].mean(),
        "avg_stuck_cycles": result["stuck_cycles_count"].mean(),
    }


if __name__ == "__main__":
    print(f"Assumptions: spot=${SPOT0:,.0f}, sigma_annual={SIGMA_ANNUAL:.0%}, tenor={TENOR_DAYS}d, "
          f"cycles/yr={CYCLES_PER_YEAR}, ATM_RATE={ATM_RATE:.0%}, decay_k={DECAY_K}, paths={N_PATHS}")
    print(f"Sanity check rate_for_gap: gap=0% -> {rate_for_gap(0):.1%}, "
          f"gap=1.5% -> {rate_for_gap(1.5):.1%}, gap=2.25% -> {rate_for_gap(2.25):.1%}, "
          f"gap=3% -> {rate_for_gap(3):.1%}, gap=5% -> {rate_for_gap(5):.1%}, gap=10% -> {rate_for_gap(10):.1%}")

    res_atm = simulate_regime("atm", seed=1001)
    res_otm = simulate_regime("otm_buffer", seed=1002)

    s_atm = summarize("Regime 1: 最高收益 (ATM, nearest strike)", res_atm)
    s_otm = summarize("Regime 2: 不被轉換 (OTM buffer -1.5%~-3%)", res_otm)

    # sensitivity: low-vol and high-vol scenarios (DVOL observed range 36% - 100%)
    for sigma, tag in [(0.36, "低波動 36%"), (0.80, "高波動 80%")]:
        r1 = simulate_regime("atm", sigma_annual=sigma, n_paths=8000, seed=2001)
        r2 = simulate_regime("otm_buffer", sigma_annual=sigma, n_paths=8000, seed=2002)
        summarize(f"[敏感度 sigma={sigma:.0%}] Regime 1 ATM ({tag})", r1)
        summarize(f"[敏感度 sigma={sigma:.0%}] Regime 2 OTM buffer ({tag})", r2)

    # sensitivity: directional drift (bullish / bearish), base vol 55%
    for mu, tag in [(0.30, "多頭偏向 +30%/年"), (-0.30, "空頭偏向 -30%/年")]:
        r1 = simulate_regime("atm", mu_annual=mu, n_paths=8000, seed=3001)
        r2 = simulate_regime("otm_buffer", mu_annual=mu, n_paths=8000, seed=3002)
        summarize(f"[敏感度 drift={mu:+.0%}] Regime 1 ATM ({tag})", r1)
        summarize(f"[敏感度 drift={mu:+.0%}] Regime 2 OTM buffer ({tag})", r2)
