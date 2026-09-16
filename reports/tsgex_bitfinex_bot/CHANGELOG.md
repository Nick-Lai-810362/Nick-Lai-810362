# Changelog

## v5.8 (fix: real bug -- `best_rate_by_tenor()` mixed funding bids and asks)

The user asked how to confirm the bot actually works against the real
Bitfinex API before handing over live credentials. This session's own
sandbox has zero network egress (confirmed: the proxy rejects
`api.bitfinex.com:443` with an explicit "organization policy" denial), so
the user ran the dry-run (`python tsgex_bitfinex_lending_bot.py --mode
dave_high --cycles 5`, no `--live`, no `--mock`) on their own machine.

**Bug #1 -- HTTP 403 on every request.** `client.py`'s `_get()`/`_signed_post()`
sent no `User-Agent` header, so `urllib` defaulted to `Python-urllib/3.9`, a
well-known bot signature that Bitfinex's edge/WAF layer rejects outright
before the request reaches any API logic. Fixed by sending an honest,
descriptive `User-Agent` (`tsgex-bfx-bot/5.7 (+github URL)`) on every
request. This could not have been caught earlier -- this bot's dev sandbox
has never had network egress to Bitfinex to notice it.

**Bug #2 -- `best_rate_by_tenor()` mixed funding bids and asks (the real
find).** After the 403 was fixed, every cycle reported a nonsensical
~0.04% gross APR and correctly held (below `floor_rate`). The user's own
sharp follow-up question -- "could 0.04 actually be an un-annualized daily
rate?" -- turned out not to be the cause (the code does annualize before
printing), but pushed the investigation to fetch and inspect a real
`GET /v2/book/fUSD/P0` response directly. That response confirmed
Bitfinex's funding book mixes BOTH sides in one array: `AMOUNT < 0` rows
are funding BIDS (someone wants to BORROW), `AMOUNT > 0` rows are funding
ASKS (someone wants to LEND -- the side a lending bot actually competes
against). `strategy.best_rate_by_tenor()` took the global minimum rate per
tenor across BOTH sides with no sign filtering, so it could pick up a deep,
stale, irrelevant bid-side rate (real capture: a 2d bid down at
0.00013992, i.e. that OTHER side's worst quote) instead of the real
best ASK (real capture: 0.00022328, ~8.15%/yr -- consistent with this
project's own 5-year historical median). `depth_by_tenor()` still sums both
sides deliberately (a general "is this tenor actively traded at all"
signal, not a fill-probability estimate for one side) -- left unchanged,
flagged as an open question for later, not bundled into this fix.

Neither bug was catchable by the existing test suite: `MockBitfinexClient`
only ever generates positive-amount rows, so bid/ask mixing was invisible
to every unit test and to the full 5-year backtest (v5.7, which also only
used the mock's lifecycle simulation). This is exactly the failure mode the
user's live dry-run was for. Added a regression test
(`test_best_rate_by_tenor_ignores_bid_side_negative_amount_rows`) using a
trimmed excerpt of the actual live capture as its fixture.

**Confirmed fixed against a second live run** (same user, same machine,
`--mode dave_high --contribute 10000 --cycles 5`, still no `--live`/`--mock`):
the live 2d rate now reads as a sane 8.61%-20.61% gross ladder (13
calibrated tranches summing to the full $10,000 contributed, in line with
this project's own 5-year historical median), the tranche ladder and
ledger bookkeeping behaved exactly as designed, and no exceptions occurred
across 5 real-data cycles. This is the first time any part of this bot's
live-book code path has run against a real Bitfinex response end to end.

## v5.7 (research: full ~5-year walk-forward backtest of the real `run_cycle()` -- no code change)

The user asked for a complete backtest report of THIS PROGRAM (not a
spreadsheet re-derivation of its math): fill latency from order placement to
match, cancel+relist operations, and rate volatility, over the real ~5-year
fUSD rate history already collected, using the bot's own designed polling
behavior, walk-forward with no lookahead (as if the future rate path were
unknown at every simulated moment -- which it genuinely is, since the walk-
forward cursor in `HistoricalFundingBook` only ever exposes the current row).

Built `research/backtest_full_5year.py`: a `MockBitfinexClient` subclass
(`HistoricalFundingBook`) that keeps the mock's disclosed offer-lifecycle
simulation (`FILL_PROB_PER_CYCLE`, submit/cancel, wallet) unchanged and only
overrides `get_funding_book()` to return the REAL historical 2d/30d rate at
the current cursor instead of a synthetic random walk, then drives the
literal `runner.run_cycle()` once per real historical hour (the finest grain
the 5-year dataset supports) across all four non-`custom` modes (`dave_high`,
`dave_fast`, `barbell`, `frr` -- `custom` is redundant with `dave_high`
since they differ only in the spike-reserve check, which defaults off).
Window: 2021-08-23 to 2026-09-07 (bounded by p30's shorter real history),
42,911 valid joint hourly observations, ~158,730 USD starting capital (the
project's standing NT$5,000,000 worked example). Full output:
`research/backtest_full_5year_results_2026-09-16.txt`.

**Headline results** (CAGR = geometric annualized growth of terminal net
worth vs. contributed principal; `realized_apr` = analytics.py's simple-
interest annualization of total realized profit -- see its own documented
caveat that this UNDERSTATES true compounding):

| mode | CAGR | realized_apr | final net worth (from $158,730) | cancelled (stale) |
|---|---|---|---|---|
| dave_high | 28.80%/yr | 52.94% | $569,022 | 125,782 |
| barbell | 13.86%/yr | 18.94% | $305,481 | 87,413 |
| dave_fast | 6.31%/yr | 7.40% | $216,073 | 6,687 |
| frr | 6.31%/yr | 7.40% | $216,073 | 6,687 |

`dave_fast` and `frr` are numerically IDENTICAL in this backtest -- not a
bug: `execution.place_frr_tranche()` already documents that it books FRR
accrual against "the currently observed short-tenor rate" as a disclosed
proxy (no real historical hourly FRR series exists to backtest against
separately), and both modes place one single full-lendable-amount tranche
at the short tenor per cycle, so they are mathematically the same trade
sequence here. A live FRR order would actually settle against Bitfinex's own
floating rate, which can differ from the best displayed rate -- this
backtest cannot measure that gap.

**Answers the user's specific spike-handling question with real numbers**:
of every stale pending order this backtest cancelled and relisted, over
99.9% (dave_high: 125,656/125,782; barbell: 100.0%; dave_fast/frr: 99.3%)
were triggered by `rate_drift_threshold_pp` (the quoted rate moved away from
the market), not by hitting `max_wait_hours` (patience timeout) -- confirming
the mechanism described in v5.0/v5.6 is, in practice, almost always the
rate-reactive path, not the patience path, over real 5-year rate volatility.
Median time from order placement to fill: ~1.0h across every mode (p90
2-4h) -- the disclosed `FILL_PROB_PER_CYCLE` heuristic (not measured; no
historical order-book endpoint exists, same limitation disclosed since v5.0)
applied at 1-hour-cycle granularity.

**What is and isn't real data here** (same disclosure standard as every
other backtest in this project): the 2d/30d RATES driving every decision are
the real historical series. Per-tenor order-book DEPTH is a constant,
disclosed heuristic (real historical depth-over-time cannot be measured --
Bitfinex's API has no historical order-book endpoint), so a real illiquidity
dry-spell at 30d that happened at some point in these 5 years cannot be
detected or reacted to by this backtest. `FILL_PROB_PER_CYCLE` is the same
already-disclosed heuristic from `MockBitfinexClient`, reused unmodified at
a 1-hour cycle length -- not directly comparable to the 6-hour-cycle version
used in v5.4's utilization sweep. No config default changed as a result of
this backtest; it answers "what would have happened," not "what should the
defaults be."

## v5.6 (fix: dead, misleading `StrategyConfig.poll_interval_sec` field removed)

The user asked how a sudden mid-cycle rate spike on a still-pending order is
handled, and how often the bot actually polls for that. The cancel+relist
answer was already correct and already covered this (see v5.0:
`execution.reconcile_pending_offers()` compares a pending order's quoted
rate against the CURRENT live rate every cycle and cancels+relists if the
drift exceeds `--rate-drift-threshold-pp` in EITHER direction -- a sudden
spike is exactly the "drifted away from my quoted rate" case, no special-
casing needed). But answering "how often" surfaced a real bug: `cli.py`'s
actual poll cadence is its own separate `--poll-interval` CLI flag
(default 5 real seconds, used directly in `time.sleep()`), while
`StrategyConfig.poll_interval_sec` (default 300) sat right next to it in
the config dataclass, looking like it controlled the same thing, and was
never read anywhere in the codebase -- confirmed via grep across the whole
package and test suite. Anyone constructing a `StrategyConfig` directly
(bypassing `cli.py`) and setting `poll_interval_sec` expecting it to change
polling frequency would have silently gotten 5 seconds regardless. Removed
the dead field rather than wiring it up post hoc, since `cli.py`'s
`--poll-interval` argument is already the single real source of truth and
duplicating it in the dataclass would just reintroduce the same trap.

Also clarified for the user: polling is NOT millisecond-scale, by design --
Bitfinex's own documented request-rate limit is 10-90 requests/minute
depending on endpoint, and each cycle already makes multiple calls (book
GET, active-offers check, any submit/cancel calls), so sub-second polling
would risk the rate limit for no real benefit -- Bitfinex's own FRR updates
only hourly, and nothing in the funding market moves on a millisecond
timescale that this bot could usefully react to. `--poll-interval` (default
5s) is user-configurable if a different cadence is wanted.

## v5.5 (retraction: "jump mode" high-turnover premise tested against real data and REJECTED)

The user asked for a high-annualized-return design in the spirit of Fuly's
publicly documented "Jump Strategy" (跳跳樂), and I proposed one: skip the
30d tenor's premium entirely and instead compound faster by always
re-lending at the liquid 2d tenor, reasoning that "even a modest gross rate
differential compounds faster at 2d." **That reasoning was wrong, and I
tested it against real data before writing any code -- see
`research/compounding_frequency_2d_vs_30d.py` and
`research/compounding_frequency_results_2026-09-16.txt`.**

Method: resampled the real 5-year hourly fUSD p2/p30 series at EACH
tenor's own natural maturity period (every 2 days for p2, every 30 days for
p30 -- i.e. exactly when a real position matures and must be re-lent), and
compounded net-of-fee simple interest forward across the full span, a
different and more realistic methodology than v5.4's Part A (which measured
a snapshot blend under a full-instant-fill assumption, not compounded
terminal wealth). Result: **continuously re-lending at 2d produced a
geometric annualized net return of 5.60% over 5.7 years (1043 periods);
parking at 30d produced 9.31% over 5.0 years (62 periods)** -- a ~3.7
percentage-point gap that closely cross-validates v4's independently
measured 5-year median (p30-p2) spread of +3.65pp using a completely
different method (point-in-time snapshot vs. compounded terminal wealth).
Two independent measurements agreeing this closely is strong evidence the
30d term premium is real, not noise -- and it is large enough that no
realistic compounding-frequency effect at single-digit APRs comes close to
closing a 3.7pp/year gap (compounding frequency only matters at much higher
rates or far more compounding periods than funding markets ever see).

**Conclusion: the "jump mode" proposal is REJECTED. No new mode was added.**
The already-existing `custom`/`dave_high` behavior --
`decide_tenor_allocation()` shifting SOME capital to 30d only when a live
premium clears `term_premium_min_pp`, capped by `max_total_shift_from_short`
and gated by `min_period_depth_usd` -- remains the best-supported design in
this codebase for pursuing return without pretending fill risk at the thin
30d tenor doesn't exist (v4 finding #1: 30d is only ~1% of trade volume).
This finding, if anything, reinforces v5.4's conclusion from the other
direction: the 30d premium is real and worth partially capturing (so don't
abandon it for a "just churn 2d faster" scheme that real data shows
underperforms it), but it's real liquidity limits, not the premium's
existence, that should govern how much of `max_total_shift_from_short` a
given account size can realistically expect to get filled at -- something
this project still has no real order-book depth data to quantify (see v5.2,
v5.4). No default changed here either; this entry exists so the rejected
idea and the evidence against it are on record, not silently dropped.

## v5.4 (research: capital utilization vs. annualized return -- no code change, `term_premium_min_pp` default kept)

The user asked how to get the highest annualized return WITHOUT sacrificing
capital utilization. These pull in different directions and needed to be
tested as two separate questions with different evidence quality, not
answered from intuition -- see `research/param_sweep_utilization_vs_return.py`
and `research/param_sweep_results_2026-09-14.txt`.

**Part A (real data, rigorous): replayed `decide_tenor_allocation()` against
all 42,911 real hourly fUSD p2/p30 observations (2021-08 to 2026-09, the
same data as v5.1) under a grid of `term_premium_min_pp` values, assuming
full instant fill.** Under that assumption, blended net APR is monotonically
higher the LOWER the threshold goes (0.0 -> +1.98pp out-of-sample lift over
always-2d, vs. the current default 0.02 -> +1.63pp, vs. 0.08 -> +0.46pp),
because a lower threshold shifts more weight onto the 30d tenor whenever
ANY positive premium is visible. **This result is a ceiling, not an
achievable number**, because it shares the same full-fill assumption v5.0
already flagged as unrealistic.

**Part B (mock simulation, disclosed heuristic -- Bitfinex has no historical
order-book/fill-latency endpoint, so there is no real data to backtest fill
probability against): ran the bot's own `run_cycle()` against
`MockBitfinexClient`'s fill-probability heuristic across a grid of
`--max-wait-multiplier` / `--rate-drift-threshold-pp`, measuring the ACTIVE
(actually earning) capital fraction, separately from PENDING (committed but
not yet earning).** Single-seed, noisy (cell-to-cell swings of 40+
percentage points on adjacent settings), so read directionally only: a
`rate_drift_threshold_pp` that's too tight drove MORE cancel+relist churn,
which resets a position back to `pending` (restarting its wait for a fresh
fill) rather than helping it fill sooner -- in this mock, active fraction was
consistently worse at the tightest drift setting (0.005) than looser ones
across every wait-multiplier tested.

**Why these don't combine into one number, and why the default wasn't
changed:** Part A's "lower threshold always wins" result only holds because
it assumes 30d fills exactly as reliably as 2d. v4's real trade-count data
says otherwise -- 2d is 89.6% of matched trade volume, 30d is ~1% -- and
`MockBitfinexClient`'s fill probabilities don't scale down further as more
capital is pushed at a thin tenor (a disclosed simplification, see
`mock_client.py`), so Part A's optimistic ceiling likely overstates what a
lower threshold would actually achieve once a large real position tries to
fill against that thin 30d book. The current default (0.02) already commits
26-35% of capital to 30d in this backtest; pushing it lower chases a paper
return this project has no real data to confirm is actually collectable.
**No default changed** -- the honest position, per this project's own
`decide_tenor_allocation()` docstring, is that the tenor-allocation
threshold reads the CURRENT live premium, not a forecast, and this research
didn't produce real fill-probability data to justify moving it either way.

**Practical answer given to the user:** utilization is driven almost
entirely by stale-order discipline (keep `--rate-drift-threshold-pp` loose
enough to avoid relist churn -- 0.005 was the one setting that consistently
hurt active fraction across the sweep) and by staying anchored to the
liquid 2d tenor rather than chasing yield into the thin 30d market past
what the current default already allocates; return is driven by
`term_premium_min_pp`, but the sweep itself shows why going below the
current default is a real-data-unverified bet, not a proven improvement.

## v5.3 (real, API-connected local web dashboard)

The user pointed out the only dashboard that existed (the CSV-import
Artifact from the v5 revision) was import-only and had none of: an
API-connected view, asset overview, open-order detail, total/annualized
earnings, principal, lending history, or switching between sub-accounts with
different API keys -- and asked for all of it to actually be built, not just
described.

**Why this had to be a new local web server, not more work on the existing
Artifact:** a claude.ai Artifact page's sandbox blocks browser-side
`fetch`/`XHR` to any host outside a small CDN allowlist, and
`api.bitfinex.com` is not on it -- a browser-only Artifact page cannot call
the live Bitfinex API AT ALL, full stop, regardless of how the page is
written. This is a hard platform constraint discovered by reading the
Artifact tool's own documented CSP, not a design tradeoff. Calling the real,
authenticated API needs a real backend making the signed HTTP request
server-side, so "串接 API 的頁面" and "切換不同子帳號串接不同 API" could only
be honestly delivered as a local web server the user runs on their own
machine (`python tsgex_bitfinex_dashboard.py`) using the bot's own existing
`client.py`.

**New: `tsgex_bfx_bot/webapp.py`** -- a plain Python `http.server` (stdlib
only, no new dependency) binding to `127.0.0.1` by default (refuses any
other host without `--allow-remote`, since this can show real account
balances) and serving:
- `GET /` -- `webapp_static/dashboard.html`, a real multi-tab SPA: 資產總覽 /
  掛單詳情 / 出借歷史紀錄 / 收益與年化報酬.
- `GET /api/{overview,offers,history,earnings,apr}?profile=X` -- JSON backed
  by the bot's own local ledger (`bfx_bot_state.json`), always available with
  zero API keys or network access, PLUS an optional live-data overlay
  (Bitfinex funding-wallet balance via a new `client.get_wallet_balances()`,
  and a live open-offer count via the existing `get_active_funding_offers()`)
  when a profile has working credentials -- every live call is wrapped so a
  missing key or network failure degrades to "local ledger only, live
  overlay unavailable," never a crash. Neither new client method has been
  verified against a real Bitfinex call (network egress to Bitfinex is
  blocked in the sandbox this bot was developed in) -- same disclosed caveat
  as `extract_offer_id()` from v5.0.0.
- `GET /api/profiles` + `--profiles-file` (`profiles.py`) -- multiple named
  sub-accounts, each with its OWN state file and OWN env-var names for its
  key/secret (never the credentials themselves, so a shared profiles.json
  never leaks a secret, matching cli.py's existing env-var-only convention).
  Switching accounts in the dashboard is a dropdown, no restart needed.

**New: `tsgex_bfx_bot/analytics.py`** -- the actual numbers requested,
computed as pure, unit-tested functions over `BotState` (shared by the API
and directly testable without spinning up a server): `overview()` (principal
contributed, idle principal/profit, committed active/pending, net worth
estimate), `open_offers()` (current pending/active orders with gross/net
APR), `history()` (the full filterable lending-history table), `earnings()`
(realized profit total, cumulative-by-maturity series, profit by tenor), and
`apr()` (two distinct, both-legitimate readings: current amount-weighted APR
of just-active capital, and a conservative realized-APR annualizing total
realized profit against total contributed principal since the earliest
position -- see the function's docstring for a real caveat found via manual
smoke-testing: this realized-APR figure goes nonsensical if computed against
a ledger built with `--mock-days-per-cycle`, since that fast-forwards
position timestamps ahead of real wall-clock time; irrelevant to real
trading, only to fast-forwarded mock demos).

Verified end-to-end against a REAL generated ledger (not just synthetic
pytest fixtures): ran the bot for 10 fast-forwarded mock cycles, pointed
`tsgex_bitfinex_dashboard.py --mock` at the resulting state file, and curled
every route.

Also kept the original CSV-import Artifact dashboard around
(`reports/TSGEX_Bitfinex_Bot_Dashboard.html`) as a lighter option for
eyeballing an exported CSV without running anything locally -- it never had,
and structurally cannot have, live-API or multi-account features, for the
same CSP reason above.

## v5.2 (generalized N-tenor allocation, fixed_count tranche mode, rate-unit + min-order-size re-verification)

Three follow-up questions from the user, answered by research where a claim
needed verifying and by implementation where the feature was genuinely
missing.

**1. "Same-tenor tranche count could instead be a fixed number of concurrent
orders, splitting total idle capital evenly?"** Added `StrategyConfig.
tranche_sizing_mode`: `"calibrated"` (default, unchanged -- P75 real-trade-
size inverted pyramid) or `"fixed_count"`, which splits a tenor bucket's
capital evenly across `--max-concurrent-orders` tranches instead of deriving
the count from calibration. Automatically reduces the count if capital/count
would fall under Bitfinex's $150 minimum order size (`build_tranches_for_
tenor` in `strategy.py`).

**2. "Why only 2/7/30 days -- shouldn't 3,4,5,6,8,9,10...29 each get their own
adaptive allocation?"** `best_rate_by_tenor()` no longer filters the live
book to the fixed `TARGET_TENORS = (2, 7, 30)` shortlist -- it now returns
every period actually quoted right now (Bitfinex accepts any period 2-120
days). `decide_tenor_allocation()` was generalized to loop over however many
periods are live: the shortest is the anchor, and each longer period
(ascending) gets a share shifted from the anchor if its live net-APR premium
over the anchor clears `--term-premium-min-pp`, up to a new `--max-total-
shift-from-short` cap (default 0.7, extracted from what was previously a
hardcoded literal) so the most liquid tenor is never fully vacated. A new
`depth_by_tenor()` + `--min-period-depth-usd` (default $1,000) filter skips
any period whose current book depth is too thin to reliably fill a real
tranche against -- necessary now that the book isn't pre-filtered to only
the three tenors known to be liquid (v4 finding #1: liquidity is 89.6%
concentrated at 2d; most other periods are quoted by only a handful of
participants). `MockBitfinexClient` now also generates thin quotes at
3,4,5,6,8,9,10,14,21,29d so `--mock` exercises this meaningfully.

**3. "Order rates should be submitted as hourly, not daily -- did you know
that?"** Researched before changing anything, since silently complying with
an incorrect unit claim would have introduced a severe live-trading pricing
bug. Three independent, converging sources confirm the `rate` field in a
Bitfinex funding-offer submission is a **daily** rate, not hourly: (a)
Bitfinex's own funding interest formula is `amount * rate% * (seconds_lent /
seconds_in_a_day) * (1 - fee%)`, explicitly a per-day basis; (b) Bitfinex's
own worked example states "2 BTC at 0.04% = 0.0008 BTC/day"; (c) a real
API response with `rate='0.0002'` at a 7-day period annualizes
(`rate * 365`) to a realistic ~7.3% APR -- annualizing it as if hourly
(`rate * 24 * 365`) would imply a nonsensical ~175% APR. **No code change**
-- this codebase already treats `rate` as daily throughout (see `net_apr()`
in `config.py`, `TENOR_TYPICAL_ORDER_SIZE`-based tranche rates in
`strategy.py`). The likely source of the user's confusion: Bitfinex's Flash
Return Rate (FRR) *updates* hourly (a different, real fact) -- but FRR's
update cadence and an individual offer's own rate time-unit are unrelated
facts about the same market.

**4. "Research whether Bitfinex has a minimum order size, and enforce it."**
Re-verified: Bitfinex's documented minimum funding-offer size is **$150
USD** (Bitfinex Help Center), matching `constants.BFX_MIN_ORDER_USD`, already
enforced where tranches are constructed (`build_tranches_for_tenor`'s
`fixed_count` branch now explicitly floors the tranche count against it, and
`runner.run_cycle` already skipped any tenor bucket below it before this
change).

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
