"""
Dual Investment year-long simulation v3.

Fix vs v2: v2 held tenor fixed at 7 days for every cycle, for both regimes,
for the entire year. That's wrong -- real products (OKX confirmed: terms
within a 7-day window including a 2-day term; Binance: roughly 1 week up to
4-8 weeks) offer a MENU of tenors, and shorter tenor genuinely commands a
higher quoted ANNUALIZED rate for the same strike distance -- this is not
just marketing, it falls out of Black-Scholes: an ATM option's premium as
a fraction of notional scales with sigma*sqrt(T), so annualized rate
(premium/T) scales with 1/sqrt(T).

v3 makes tenor an explicit parameter and derives how the calibrated rate
curve should shift for a different tenor, anchored to the SAME two
user-given data points at the reference T=7 days (ATM_RATE_7D=1.25,
DECAY_K_7D=0.6109 from v2's 2-point fit), scaled via the same 1/sqrt(T)
family implied by Black-Scholes moneyness (d1 ~ gap / (sigma*sqrt(T))):

    ATM_RATE(T)  = ATM_RATE_7D  * sqrt(7/T)
    DECAY_K(T)   = DECAY_K_7D   * sqrt(7/T)

Sanity check against Black-Scholes ATM fair value at sigma=55%:
  T=1d -> ~419% theoretical vs our 331% (still conservative)
  T=7d -> ~158% theoretical vs our 125% (still conservative, matches v2)
  T=30d-> ~77%  theoretical vs our 60%  (still conservative)
So the scaled curve stays conservative (below theoretical fair value) at
every tenor, not just at the one anchor point -- it isn't a coincidence
that only holds at T=7.
"""
import numpy as np

RNG = np.random.default_rng(20260907)

ATM_RATE_7D = 1.25
DECAY_K_7D = 0.6108604879161034
REF_TENOR_DAYS = 7.0
SIGMA_ANNUAL = 0.55
SPOT0 = 77000.0
N_PATHS = 20000


def curve_for_tenor(tenor_days):
    scale = np.sqrt(REF_TENOR_DAYS / tenor_days)
    return ATM_RATE_7D * scale, DECAY_K_7D * scale


def rate_for_gap(gap_pct, atm_rate, decay_k):
    g = max(gap_pct, 0.0)
    return atm_rate * np.exp(-decay_k * g)


def simulate_regime(regime, tenor_days=7.0, sigma_annual=SIGMA_ANNUAL, mu_annual=0.0,
                     n_paths=N_PATHS, seed=None, years=1.0):
    rng = np.random.default_rng(seed) if seed is not None else RNG
    atm_rate, decay_k = curve_for_tenor(tenor_days)
    dt = tenor_days / 365.0
    sig_cycle = sigma_annual * np.sqrt(dt)
    cycles = int(round(years * 365.0 / tenor_days))

    final_multiples = np.zeros(n_paths)
    still_open = np.zeros(n_paths, dtype=bool)
    conversions_count = np.zeros(n_paths, dtype=int)

    for p in range(n_paths):
        value = 1.0
        spot = SPOT0
        holding_btc = False
        locked_strike = None
        btc_qty = None

        for c in range(cycles):
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
                rate = rate_for_gap(gap_pct, atm_rate, decay_k)
                premium = value * rate * dt
                if spot_next < strike:
                    conversions_count[p] += 1
                    btc_qty = (value + premium) / strike
                    locked_strike = strike
                    holding_btc = True
                    value = None
                else:
                    value = value + premium
            else:
                gap_pct = max((locked_strike - spot) / spot * 100.0, 0.0)
                rate = rate_for_gap(gap_pct, atm_rate, decay_k)
                btc_value_now = btc_qty * spot
                premium_usd = btc_value_now * rate * dt
                btc_qty = btc_qty + premium_usd / spot
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

    return {"final_multiples": final_multiples, "still_open": still_open,
            "conversions_count": conversions_count, "atm_rate": atm_rate, "decay_k": decay_k,
            "cycles": cycles}


def summarize_row(tenor_days, regime, result):
    fm = result["final_multiples"]
    ann = (fm - 1.0) * 100.0
    open_mask = result["still_open"]
    closed_share = (~open_mask).mean() * 100
    closed_mean = ((fm[~open_mask] - 1.0) * 100.0).mean() if (~open_mask).any() else float("nan")
    open_mean = ((fm[open_mask] - 1.0) * 100.0).mean() if open_mask.any() else float("nan")
    print(f"  T={tenor_days:5.1f}d  ATM={result['atm_rate']:6.1%}  cycles/yr={result['cycles']:4d}  |  "
          f"blended mean={ann.mean():7.2f}%  median={np.median(ann):7.2f}%  P(loss)={(fm<1).mean()*100:5.1f}%  |  "
          f"closed: {closed_share:5.1f}% share, mean={closed_mean:7.2f}%  |  open mean={open_mean:7.2f}%")


if __name__ == "__main__":
    print("Sanity check: rate curve at each tenor (gap=0 i.e. ATM):")
    for T in [1, 2, 3, 5, 7, 14, 21, 30]:
        a, k = curve_for_tenor(T)
        print(f"  T={T:2d}d  ATM_RATE={a:.1%}  decay_k={k:.4f}")

    print("\n=== Regime 1 (ATM / highest-yield) across realistic tenor menu, sigma=55%, zero drift ===")
    for T in [1, 2, 3, 5, 7, 14, 21, 30]:
        res = simulate_regime("atm", tenor_days=T, n_paths=15000, seed=4000 + T)
        summarize_row(T, "atm", res)

    print("\n=== Regime 2 (OTM buffer -1.5%~-3%) across tenor menu, sigma=55%, zero drift ===")
    for T in [3, 7, 14, 30]:
        res = simulate_regime("otm_buffer", tenor_days=T, n_paths=15000, seed=5000 + T)
        summarize_row(T, "otm_buffer", res)

    print("\n=== Regime 1 (ATM) at T=1d, with bullish drift sensitivity ===")
    for mu in [0.0, 0.30, -0.30]:
        res = simulate_regime("atm", tenor_days=1, mu_annual=mu, n_paths=15000, seed=6000)
        print(f"  drift={mu:+.0%}:")
        summarize_row(1, "atm", res)
