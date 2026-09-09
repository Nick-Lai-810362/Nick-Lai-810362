#!/usr/bin/env python3
"""
TSGEX Bitfinex USD Margin Funding Automation Bot -- CLI entry point.

This is a thin wrapper: all logic lives in the tsgex_bfx_bot/ package next
to this script (constants.py, config.py, ledger.py, client.py, mock_client.py,
governance.py, audit.py, strategy.py, execution.py, runner.py, cli.py).
See README.md for the module map and CHANGELOG.md for the full research and
design-decision history (real Bitfinex tenor/liquidity data, the principal/
profit ledger, pending-order fill tracking and stale-order cancel+relist).

USAGE EXAMPLES
--------------
  # First-time setup: contribute principal, then run a demo with the clock
  # fast-forwarded so positions actually fill/mature within a short test
  python tsgex_bitfinex_lending_bot.py --mock --contribute 158730 --mode dave_high \\
      --cycles 10 --mock-days-per-cycle 3

  # Real dry-run against live market data (places no orders), needs network
  python tsgex_bitfinex_lending_bot.py --contribute 158730 --mode barbell

  # Export the full position history (principal/profit split) to CSV
  python tsgex_bitfinex_lending_bot.py --export-csv history.csv --export-tenor 30 \\
      --export-start 2026-01-01 --export-end 2026-12-31

  # Actually place live orders (only after reviewing dry-run output)
  python tsgex_bitfinex_lending_bot.py --live --mode dave_high

SETTING UP A REAL API KEY
---------------------------
1. Bitfinex -> API Keys -> Create New Key.
2. Enable ONLY "Margin Funding" (read + write/orders). Do NOT enable
   "Withdraw" or "Transfer" under any circumstance.
3. Move the capital you want to lend into your Bitfinex FUNDING wallet
   (not the Exchange wallet) -- this bot only sees/acts on funding balance.
4. If Bitfinex's own built-in "Lending Pro" auto-lending is on, turn it OFF
   first -- running two auto-lenders against the same balance causes
   duplicate/conflicting offers.
5. Optionally IP-restrict the key.
6. Export credentials as env vars (never pass them on the CLI):
     export BFX_API_KEY=...
     export BFX_API_SECRET=...
"""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")

from tsgex_bfx_bot.cli import main  # noqa: E402  (after logging config on purpose)

if __name__ == "__main__":
    main(sys.argv[1:])
