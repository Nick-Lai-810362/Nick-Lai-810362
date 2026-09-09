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
```

Run the test suite with `pytest` from this directory (or anywhere, since
`pyproject.toml` sets `pythonpath = ["."]`).

## Module map

```
tsgex_bitfinex_lending_bot.py   Thin CLI entry point (configures logging, calls cli.main())

tsgex_bfx_bot/
  constants.py     Real-data-derived numbers: target tenors, per-tenor typical
                    order size, max-wait heuristics, platform fees. Every
                    value's source is documented inline.
  config.py        StrategyConfig dataclass + platform_fee()/net_apr()
  ledger.py        Position/BotState, the principal-vs-profit ledger:
                    load/save, contribute, reconcile (matured + pending),
                    open/cancel a position, CSV export
  client.py        BitfinexClient (real REST calls) + extract_offer_id()
  mock_client.py   MockBitfinexClient: synthetic book shaped like real
                    liquidity, plus a simulated pending-offer fill lifecycle
  governance.py    assert_minimal_permissions() -- refuses to run --live if
                    the API key can withdraw/transfer
  audit.py         write_audit_log() -- JSON-lines decision trail
  strategy.py      best_rate_by_tenor(), decide_tenor_allocation(),
                    compute_spike_signal(), build_tranches_for_tenor()
  execution.py     place_tranche(), place_frr_tranche(),
                    reconcile_pending_offers() (fill detection + stale
                    cancel+relist)
  runner.py        run_cycle() -- wires the above into one strategy cycle
  cli.py           argparse + main()

tests/             pytest suite, one file per module + test_integration.py
                    for end-to-end regression coverage (several tests encode
                    real bugs found during development -- see their
                    docstrings and CHANGELOG.md)
```

## Data flow of one cycle (`runner.run_cycle`)

1. Settle any matured (filled + tenor elapsed) positions -> principal back
   to idle, interest realized as profit.
2. Read the live funding book, compute the best rate at each real liquid
   tenor (2/7/30 days; 120d only if `--authorize-extreme-tenor`).
3. Reconcile pending (submitted, not yet filled) positions against the
   exchange's real open-offers list: no longer listed = filled; still open
   but stale (waited too long, or the market rate has drifted from the
   quoted rate) = cancel + immediately re-list at the current rate.
4. If the best net rate is below `--floor-rate`, or there's no idle capital,
   hold.
5. Dispatch on `--mode` (`dave_high` / `dave_fast` / `custom` / `frr` /
   `barbell`) to decide how much to place at which tenor(s), and place it.
6. Write a structured audit-log record and persist the ledger.

## Safety

- Dry-run by default; `--live` requires `BFX_API_KEY`/`BFX_API_SECRET` env
  vars (never pass credentials on the CLI).
- `governance.assert_minimal_permissions()` refuses to run `--live` if the
  key has withdrawal/transfer scope, independent of what you intended to
  grant it.
- `--mock` needs no network access or credentials at all.
