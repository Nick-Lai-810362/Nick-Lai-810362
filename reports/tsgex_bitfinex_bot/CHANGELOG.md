# Changelog

## v5.1 (real backtest of the spike signal and term-premium persistence -- `enable_spike_reserve` now defaults False)

The user asked for the FBRR-style prediction question to actually be
answered, not just built around, using the real 5-year hourly p2/p30/p120
rate data already collected (this sandbox cannot reach the Bitfinex API
directly -- see `research/backtest_spike_and_premium.py` for the script and
`research/backtest_results_2026-09-09.txt` for the raw output). Same
standard as the earlier BTC technical-analysis study in this project:
chronological split-half (fit on the first half, confirm on the held-out
second half), compared against a naive "no change" baseline, negative
results reported as plainly as positive ones.

**Finding 1 (acted on): the spike-proxy signal's assumed direction is
empirically backwards.** `compute_spike_signal` (fast MA(6) > slow MA(24))
fires when the rate has recent upward momentum; `dave_high` mode's design
assumed that meant "reserve capital, a further rate increase is coming."
Tested against 5 years of real hourly data (n>11,000 per bucket, both
in-sample and out-of-sample): when the signal fires, the rate's mean
forward change over the next 24h/7d is **-0.7 to -1.0 percentage points**
(a decline); when it doesn't fire, the mean forward change is **+0.6 to
+0.8pp** (a rise) -- the opposite of what the reserve logic assumes, and
consistent across both halves of the data (not an in-sample artifact). This
mirrors the earlier BTC finding that simple momentum/trend heuristics don't
have real exploitable edge in this kind of market -- here the effect isn't
even edge-less, it points the wrong way. **Action taken:** added
`StrategyConfig.enable_spike_reserve` (default `False`) gating the reserve
behavior; `dave_high` mode no longer silently reserves capital on this
signal unless explicitly re-enabled with `--enable-spike-reserve`, which
now carries an explicit warning about this finding. Not inverted into a new
"fade the signal" bet -- a mean-reversion effect existing in aggregate
(Test 1) did NOT translate into a useful point forecast (Test 3: using it
to predict the future rate level was 2-5% WORSE than assuming no change at
all), so the honest, appropriately cautious response is to disable the
heuristic, not to flip it into an unvalidated opposite strategy.

**Finding 2 (noted, no code change): the term premium's persistence is
real but weaker than the in-sample numbers alone suggest.** The correlation
between the currently observed 2d->30d premium and the premium N days later
is positive but decays sharply out-of-sample (e.g. at the 7-day horizon:
+0.143 in-sample vs +0.038 out-of-sample) -- a classic sign of an unstable
relationship, likely reflecting a few slow-moving multi-year regimes in the
5-year window rather than a stable, exploitable pattern. Practically. the
gap between "premium now >= the bot's 2pp threshold" and "premium now <
2pp" in predicting the *future* premium is modest out-of-sample (+3.80pp vs
+3.23pp at 7 days) -- real, but nowhere near as clean a separation as the
in-sample numbers (+6.96pp vs +5.19pp) implied. This does NOT invalidate
`decide_tenor_allocation`'s design: it was always framed as reading the
CURRENTLY available rate at each tenor, not forecasting where the premium
is heading (see v4 finding #3) -- that framing turns out to be the right
level of humility, since the data doesn't support treating the premium as
strongly predictive of anything beyond itself right now.

## v5.0.0 (this modularization)

Reorganized the single-file v5 script into the `tsgex_bfx_bot/` package
(see README.md for the module map). **No behavior was intentionally
changed** -- verified by running the exact same `--mock` scenarios against
both the monolith and the package with the same RNG seed and getting
byte-identical ledger output (position counts, realized profit, all to the
cent).

Writing a real pytest suite during the refactor did catch one genuine,
pre-existing bug that manual smoke-testing had missed:

- **`extract_offer_id()` could never actually parse a live Bitfinex
  response.** The function checked "is `resp[0]` a list?" to decide between
  the mock shape and the live notification-envelope shape -- but the live
  envelope's `resp[0]` is `MTS` (a plain integer, not a list), so that
  check always misfired into the mock-shape branch and returned the
  timestamp as if it were the offer ID. In `--live` mode this would have
  meant every position's `offer_id` was wrong, breaking fill-detection and
  stale-order cancellation for real accounts (mock mode was never affected,
  which is why prior manual testing didn't surface it). Fixed by checking
  the more specific live-envelope shape first. Still unverified against a
  real Bitfinex API call (network egress is blocked in the sandbox this bot
  was developed in) -- test against your own key before relying on
  cancel+relist in `--live` mode.

Also fixed in passing: `ledger.export_positions_csv()`'s displayed net-APR
column was hardcoded to the 15% standard platform fee regardless of
`--order-visibility hidden` (18%); it now takes the real fee as a parameter,
wired from `cli.main()`.

## v5.0 (pending/fill lifecycle, P75 tranche calibration)

Two follow-up questions drove this revision.

**"How many orders would be better, and given partial fills are supported,
isn't one giant order better?"** No -- a single order commits 100% of that
capital to one rate guess (a counterparty large enough to take it all is
rare per the real data: one $1.18M trade vs a $500 median in the
~10,000-row recent trades sample), whereas the inverted-pyramid ladder
diversifies rate/execution risk regardless of any order-count ceiling (none
exists -- see v4 finding #4). But the v4 default (per-tenor MEDIAN real
trade size, 227 tranches on a NT$5,000,000/~USD158,730 position) also isn't
obviously optimal once pending orders need per-cycle monitoring and can
trigger cancel+relist churn. Moved the default to each tenor's **P75** real
trade size instead ($825/2d, $574/7d, $491/30d) -- still comfortably below
the thin P90 tail, cutting the NT$5M/2d case to ~192 tranches, a modest
reduction in operational overhead without reintroducing the "too few, too
large" problem.

**"How long should an order wait before being cancelled and re-listed, and
how much can the rate move?"** Exposed a real modeling gap: every prior
version treated a submitted order as INSTANTLY earning interest, which
isn't how Bitfinex funding offers actually work (they sit unfilled in the
book until a borrower takes them). Split the position lifecycle into
`pending -> active -> matured` (or `pending -> cancelled`): capital is
committed at SUBMISSION time (matches real account behavior -- it's locked
in the funding wallet the moment you place the offer) but the tenor/
interest clock only starts once actually filled.
`execution.reconcile_pending_offers()` checks every pending position
against the exchange's real open-offers list each cycle (a position no
longer listed there has filled -- the public API exposes no per-offer
partial-fill amount, so "disappeared from open offers" is the correct and
only available fill signal) and cancels+immediately re-lists any position
that's either:
- waited too long (`DEFAULT_MAX_WAIT_HOURS` -- a **disclosed heuristic, not
  measured data**, since Bitfinex's REST API has no historical order-book
  endpoint to measure real queue times from: `{2d: 6h, 7d: 24h, 30d: 72h,
  120d: 120h}`, scaled roughly proportional to tenor length and inversely to
  that bucket's real matching liquidity), or
- whose quoted rate has drifted from the current live rate by more than
  `--rate-drift-threshold-pp` (default 1 percentage point) in either
  direction.

`MockBitfinexClient` gained a simulated pending/fill lifecycle (a per-tenor
fill probability rolled each cycle) so `--mock` can exercise this
meaningfully with zero network access.

## v4 (real-data tenor logic + principal/profit ledger)

User asked to actually research how Bitfinex's real rate/tenor structure
works instead of assuming a static ladder, using the real fUSD data
collected via `TSGEX_Bitfinex_Funding_History_Collector.py` (5 years of
hourly p2/p30/p120 rate candles, plus a ~10,000-row recent trades sample)
and Bitfinex's own public documentation.

1. **Real liquidity is overwhelmingly concentrated at the 2-day tenor.**
   period=2 was 89.6% of matched trade count / 96%+ of volume in the real
   trades sample; period=30 ~1.0%, period=120 just 0.11%. Bitfinex's own
   docs confirm "the most common periods are 2, 7, or 30 days" ->
   `TARGET_TENORS = (2, 7, 30)`.

2. **120-day tenor measured no rate premium over 30-day, across 5 years of
   data.** Time-aligned join of 25,354 overlapping hourly p2/p30/p120 rows
   (2021-08 to 2026-09): median (p120 - p30) spread = +0.04 percentage
   points, positive only 55.4% of the time -- indistinguishable from zero,
   while p120 has ~8x less matched volume than the already-thin p30 market.
   Strictly dominated -> excluded from the default tenor set, opt-in only
   via `--authorize-extreme-tenor`.

3. **The 2d->30d term premium is real but not constant.** 5-year median
   (p30 - p2) spread = +3.65pp (positive 85.5% of the time), but a same-day
   snapshot showed only +0.78pp -- and the premium is itself larger when
   short rates are low (+4.30pp) than when they're already high (+2.52pp).
   A fixed rate->tenor lookup table (originally requested) would therefore
   be wrong on a random day. Replaced with `strategy.decide_tenor_
   allocation()`, which reads the ACTUAL live rate at each tenor from the
   funding book every cycle and only shifts capital to a longer tenor when
   the CURRENTLY observed premium clears `--term-premium-min-pp` (default
   2pp, chosen inside the observed 0.78-3.65pp range).

4. **No published Bitfinex limit on concurrent open funding offer COUNT
   exists** (searched `docs.bitfinex.com/docs/requirements-and-limitations`
   and the funding offer API reference directly) -- only a documented
   request-RATE limit (10-90/min). Partial fills are supported (a large
   offer can fill across many borrowers over time). Tranche sizing is
   calibrated per-tenor-bucket against the real observed trade-size
   distribution for that bucket instead of one generic range for every
   tenor; a submission pacing constant respects the documented request-rate
   limit.

5. **Principal vs profit ledger** (closes a real state-tracking gap): a
   prior version recomputed "how much is available to lend" fresh from
   total capital every cycle, with no memory of what was already placed --
   fine for a dry-run demo, wrong for continuous live operation (would
   re-lend the same capital every cycle). Added the persistent
   `BotState`/`Position` ledger: every dollar tagged principal or profit,
   the tag propagating forward through re-lending so compounded
   profit-on-profit stays tagged as profit.

Also fixed during this revision: `max_orders_per_cycle` defaulted to 30,
which silently overrode the per-tenor real-trade-size calibration for any
account large enough to need more tranches -- a NT$5,000,000 position's 227
calibrated 2-day tranches collapsed into 30 oversized ones, averaging
$5,291/tranche (above even the real 90th-percentile 2-day trade size).
Raised the default to 400.

## v3 (Fuly.ai-informed rebuild)

Independently engineered implementation of Fuly.ai's PUBLICLY DOCUMENTED
strategy mechanics (not their undisclosed source code or proprietary FBRR
forecasting model) -- sourced from Fuly's own Medium posts, help-center
articles, and third-party tutorials:

- Two named engines: IBRR (instant-best-rate, default) and FBRR
  (predictive, reserves capital ahead of an anticipated rate spike --
  implemented here as a disclosed EMA-crossover proxy signal, explicitly
  NOT a reproduction of Fuly's real undisclosed model).
- A third order type, FRR-pegged lending (rate floats hourly with
  Bitfinex's own Flash Return Rate).
- Inverted-pyramid tranche sizing calibrated to Fuly's published example
  (80 units@10%/100@11%/120@12% -> linear size increase per ~1%-APR step).
- "Jump Strategy" (跳跳樂): documented ~10% APR trigger snapping to the
  2-day minimum tenor.
- Two named presets (戴夫高利模式/戴夫極速模式) plus a barbell allocation mode
  (splits capital between a liquid short tenor and a longer tenor) and a
  net-of-platform-fee decision basis -- three additions not described in
  Fuly's own documentation, all valuable independent of any predictive
  edge: rate/execution-risk diversification, deciding on what actually
  lands in the account, and a full JSON-lines audit trail (Fuly is a closed
  SaaS with no equivalent).
