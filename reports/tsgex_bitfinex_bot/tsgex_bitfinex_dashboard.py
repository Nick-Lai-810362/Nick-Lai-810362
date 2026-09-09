#!/usr/bin/env python3
"""
TSGEX Bitfinex USD Margin Funding Bot -- local web dashboard.

A real, API-connected dashboard (資產總覽 / 掛單詳情 / 出借歷史紀錄 / 收益與年化報酬),
with a sub-account switcher so one dashboard can flip between several
Bitfinex accounts, each hitting the exchange with its own API key. Runs
entirely on your own machine -- this is a plain local web server, not a
claude.ai Artifact (an Artifact page's sandbox blocks calling the live
Bitfinex API at all; see tsgex_bfx_bot/webapp.py's docstring for why).

USAGE EXAMPLES
--------------
  # Try every view immediately with synthetic data, no API keys needed
  python tsgex_bitfinex_dashboard.py --mock

  # Single real account: export the same BFX_API_KEY/BFX_API_SECRET env
  # vars the bot itself uses, then open http://127.0.0.1:8765/
  export BFX_API_KEY=...
  export BFX_API_SECRET=...
  python tsgex_bitfinex_dashboard.py

  # Multiple sub-accounts: write a profiles.json (see tsgex_bfx_bot/profiles.py
  # for the exact format -- each profile names its OWN env var names, never
  # the credentials themselves) and pass it in
  python tsgex_bitfinex_dashboard.py --profiles-file profiles.json

SAFETY: binds to 127.0.0.1 only by default -- pass --allow-remote to bind
elsewhere, only if you understand this can display real account balances
and open orders. Every view also works fully offline, straight from this
bot's own local ledger file, when no API key is configured or Bitfinex is
unreachable.
"""
import sys

from tsgex_bfx_bot.webapp import main

if __name__ == "__main__":
    main(sys.argv[1:])
