# TSGEX Bitfinex USD Margin Funding Automation Bot

An independently engineered automation bot for Bitfinex USD margin funding
(`fUSD`), grounded in real historical Bitfinex data (not assumed constants)
and Fuly.ai's publicly documented strategy techniques. See `CHANGELOG.md`
for the full research and design-decision history.

## Quick start

```bash
# See the strategy run against a synthetic funding book, no network needed.
# The clock is fast-forwarded 3 simulated days per cycle so positions
# actually fill and mature within a short demo run.
python tsgex_bitfinex_lending_bot.py --mock --contribute 158730 --mode dave_high \
    --cycles 10 --mock-days-per-cycle 3

# Dry-run against REAL live market data (places no orders), needs network
python tsgex_bitfinex_lending_bot.py --contribute 158730 --mode barbell

# Export the full position ledger (principal/profit split) to CSV
python tsgex_bitfinex_lending_bot.py --export-csv history.csv --export-tenor 30

# Actually place live orders (only after reviewing dry-run output)
python tsgex_bitfinex_lending_bot.py --live --mode dave_high

# Local web dashboard: asset overview, open orders, lending history, realized
# + annualized returns, and (via --profiles-file) switching between several
# Bitfinex accounts each with their own API key. Try it with zero API keys:
python tsgex_bitfinex_dashboard.py --mock
# then open http://127.0.0.1:8765/. With a real account, export the same
# BFX_API_KEY/BFX_API_SECRET env vars the bot uses and drop --mock.
```

Run the test suite with `pytest` from this directory (or anywhere, since
`pyproject.toml` sets `pythonpath = ["."]`).

## Module map

```
tsgex_bitfinex_lending_bot.py   Thin CLI entry point (configures logging, calls cli.main())
tsgex_bitfinex_dashboard.py     Thin entry point for the local web dashboard (calls webapp.main())

tsgex_bfx_bot/
  constants.py     Real-data-derived numbers: reference tenors, per-tenor
                    typical order size, max-wait heuristics, platform fees.
                    Every value's source is documented inline.
  config.py        StrategyConfig dataclass + platform_fee()/net_apr()
  ledger.py        Position/BotState, the principal-vs-profit ledger:
                    load/save, contribute, reconcile (matured + pending),
                    open/cancel a position, CSV export
  client.py        BitfinexClient (real REST calls) + extract_offer_id()
  mock_client.py   MockBitfinexClient: synthetic book shaped like real
                    liquidity (core 2/7/30/120d periods plus a spread of thin
                    3-29d periods), plus a simulated pending-offer fill lifecycle
  governance.py    assert_minimal_permissions() -- refuses to run --live if
                    the API key can withdraw/transfer
  audit.py         write_audit_log() -- JSON-lines decision trail
  strategy.py      best_rate_by_tenor(), depth_by_tenor(),
                    decide_tenor_allocation(), compute_spike_signal(),
                    build_tranches_for_tenor()
  execution.py     place_tranche(), place_frr_tranche(),
                    reconcile_pending_offers() (fill detection + stale
                    cancel+relist)
  runner.py        run_cycle() -- wires the above into one strategy cycle
  cli.py           argparse + main()
  analytics.py     overview(), open_offers(), history(), earnings(), apr() --
                    pure functions over BotState powering the dashboard
  profiles.py      Profile/load_profiles()/find_profile() -- multi-sub-
                    account config for webapp.py (each profile names its OWN
                    env vars; credentials are never stored in the config file)
  webapp.py        Local (127.0.0.1-only) HTTP server: same-origin JSON API
                    (analytics.py + live BitfinexClient calls, each wrapped
                    to degrade to "local ledger only" on any failure) +
                    serves webapp_static/dashboard.html
  webapp_static/
    dashboard.html Multi-tab dashboard SPA (資產總覽/掛單詳情/出借歷史紀錄/
                    收益與年化報酬), vanilla JS, no external dependencies

tests/             pytest suite, one file per module + test_integration.py
                    for end-to-end regression coverage (several tests encode
                    real bugs found during development -- see their
                    docstrings and CHANGELOG.md) + test_webapp.py, which
                    spins up a real DashboardHandler on a real socket and
                    hits every route with urllib
```

### Why the dashboard is a local server, not a claude.ai Artifact

An Artifact page's sandbox blocks browser-side `fetch`/`XHR` to any host
outside a small CDN allowlist -- `api.bitfinex.com` isn't on it, so a
browser-only Artifact page cannot call the live Bitfinex API at all (a hard
platform constraint, not a design choice). Calling the real, authenticated
API needs a real backend making the signed HTTP request server-side --
`webapp.py` is exactly that: a plain Python `http.server` (stdlib only) that
serves the dashboard and a same-origin JSON API backed by `client.py`. Every
view also works fully offline from the bot's own local ledger file when no
API key is configured or Bitfinex is unreachable; live exchange data (wallet
balance, live open-offer count) is an optional overlay on top. See
`tsgex_bfx_bot/webapp.py`'s module docstring for the full reasoning.

There is also a simpler, `claude.ai`-hosted Artifact
(`reports/TSGEX_Bitfinex_Bot_Dashboard.html`) for quickly eyeballing an
exported CSV without running anything locally -- it has no live-API or
multi-account features for the reason above, just position-history charts
and filtering.

## Data flow of one cycle (`runner.run_cycle`)

1. Settle any matured (filled + tenor elapsed) positions -> principal back
   to idle, interest realized as profit.
2. Read the live funding book, compute the best rate AND total quoted depth
   at every period actually quoted right now (not a fixed 2/7/30 shortlist --
   Bitfinex accepts any period 2-120 days). A period beyond 30 days is only
   considered with `--authorize-extreme-tenor`; any period is skipped if its
   book depth is below `--min-period-depth-usd` (a rate quoted by one thin
   order isn't reliably fillable at tranche scale).
3. Reconcile pending (submitted, not yet filled) positions against the
   exchange's real open-offers list: no longer listed = filled; still open
   but stale (waited too long, or the market rate has drifted from the
   quoted rate) = cancel + immediately re-list at the current rate.
4. If the best net rate is below `--floor-rate`, or there's no idle capital,
   hold.
5. Dispatch on `--mode` (`dave_high` / `dave_fast` / `custom` / `frr` /
   `barbell`) to decide how much to place at which tenor(s), and place it.
   Within each tenor bucket, tranches are sized by `--tranche-sizing-mode`:
   `calibrated` (default) derives tranche count from that tenor's real
   observed trade size; `fixed_count` instead splits the bucket's capital
   evenly across `--max-concurrent-orders` tranches, for direct control over
   how many concurrent orders are outstanding.
6. Write a structured audit-log record and persist the ledger.

## Safety

- Dry-run by default; `--live` requires `BFX_API_KEY`/`BFX_API_SECRET` env
  vars (never pass credentials on the CLI).
- `governance.assert_minimal_permissions()` refuses to run `--live` if the
  key has withdrawal/transfer scope, independent of what you intended to
  grant it.
- `--mock` needs no network access or credentials at all.
