#!/usr/bin/env python3
"""
Bitfinex USD Funding History Collector
========================================

WHY THIS EXISTS
-----------------
To build a real FBRR-style forecasting model (predict future funding rates,
not just react to the current best rate), we need historical data -- lots
of it. This sandbox's outbound network access to Bitfinex is blocked at the
environment/proxy level (confirmed via curl and WebFetch, independent of
any API key), so this script cannot be run inside the sandbox that's
helping you. It is meant to be run on YOUR OWN machine, with normal
internet access. Once it finishes, upload the CSV files it writes into
./bfx_funding_data/ back into the chat (the same way you uploaded the BTC
15m OHLCV CSV) so the forecasting work can happen there.

WHAT IT PULLS (all via Bitfinex's PUBLIC REST v2 API -- no API key needed
for any of this; these are public market-wide endpoints, not your account's
private orders):

  1. funding_trades_fUSD.csv
     Every historical matched USD funding loan on Bitfinex: timestamp,
     rate (daily), implied APR, amount, period (tenor in days).
     Source: GET /v2/trades/fUSD/hist   (paginated backwards via `end`)
     This is the single most valuable dataset -- it's the literal ground
     truth of what rate/tenor/amount actually got matched, when.

  2. funding_candles_fUSD_p{2,30,120}.csv
     Hourly OHLC of the funding rate, bucketed by three common tenor codes
     (2-day, 30-day, 120-day offers). Turns the rate into a price-like time
     series you can run standard time-series/technical methods against.
     Source: GET /v2/candles/trade:1h:fUSD:p{N}/hist

  3. funding_size_outstanding.csv
     Total outstanding USD funding size over time -- a supply/demand
     pressure proxy (more capital chasing the same borrow demand tends to
     compress rates, and vice versa).
     Source: GET /v2/stats1/funding.size:1m:fUSD:long/hist

  4. btc_price_daily.csv
     Daily BTC/USD OHLC, as an exogenous demand driver: margin-trading
     leverage demand (and therefore USD funding demand) tends to rise with
     BTC volatility and directional moves.
     Source: GET /v2/candles/trade:1D:tBTCUSD/hist

  5. (OPTIONAL, only if you pass --api-key/--api-secret) your_own_funding_trades.csv
     Your OWN historical realized funding fills (rate/amount/period you
     personally were matched at) -- not needed to BUILD a general model,
     only useful afterward to backtest "how much would this model actually
     have earned me." Requires a Bitfinex API key with FUNDING READ-ONLY
     permission -- do NOT enable Withdraw/Transfer. Never paste your key
     into chat; only ever pass it as an environment variable or CLI flag
     on your own machine.
     Source: GET /v2/auth/r/funding/trades/fUSD/hist (HMAC-SHA384 signed)

RATE LIMITS
------------
Bitfinex's public REST endpoints are limited to roughly 30-90 requests/min
depending on endpoint tier. This script sleeps between paginated requests
to stay well under that, so a multi-year backfill of funding_trades will
take a while (expect tens of minutes, not seconds) -- that's normal, let
it run.

USAGE
------
  python fetch_bitfinex_funding_history.py --years 5
  python fetch_bitfinex_funding_history.py --years 5 --api-key $BFX_API_KEY --api-secret $BFX_API_SECRET

Output lands in ./bfx_funding_data/*.csv -- upload that whole folder (or
zip it) back into the chat when done.
"""
import argparse
import csv
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_PUB = "https://api-pub.bitfinex.com"
API_AUTH = "https://api.bitfinex.com"
OUT_DIR = "bfx_funding_data"
REQUEST_SLEEP_SEC = 1.5  # conservative pacing to stay under public rate limits


COMMON_HEADERS = {
    "Accept": "application/json",
    # Bitfinex's edge (Cloudflare) blocks the default urllib UA as a bot;
    # a normal browser UA gets through.
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
}


def _get(url: str):
    req = urllib.request.Request(url, headers=COMMON_HEADERS)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt + 1)
                print(f"  rate-limited (429), backing off {wait}s...")
                time.sleep(wait)
                continue
            if e.code == 403:
                wait = 5 * (attempt + 1)
                print(f"  got 403 (attempt {attempt+1}/5), backing off {wait}s and retrying...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Failed after retries: {url}")


def _signed_post(endpoint: str, api_key: str, api_secret: str, body: dict = None):
    body = body or {}
    nonce = str(int(time.time() * 1_000_000))
    path = f"/api/v2/{endpoint}"
    body_json = json.dumps(body)
    sig_payload = f"{path}{nonce}{body_json}"
    sig = hmac.new(api_secret.encode(), sig_payload.encode(), hashlib.sha384).hexdigest()
    headers = {
        **COMMON_HEADERS,
        "Content-Type": "application/json",
        "bfx-nonce": nonce,
        "bfx-apikey": api_key,
        "bfx-signature": sig,
    }
    req = urllib.request.Request(f"{API_AUTH}{path}", data=body_json.encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fetch_funding_trades(symbol: str, start_dt: datetime, end_dt: datetime, out_path: str):
    """Paginate backwards from end_dt to start_dt using the `end` cursor,
    since Bitfinex's trades/hist endpoint returns newest-first and only
    accepts a limit of up to 10,000 per call."""
    print(f"Fetching funding trades for {symbol} from {start_dt.date()} to {end_dt.date()}...")
    cursor = ms(end_dt)
    start_ms = ms(start_dt)
    rows = []
    while cursor > start_ms:
        url = f"{API_PUB}/v2/trades/{symbol}/hist?limit=10000&end={cursor}&sort=-1"
        batch = _get(url)
        if not batch:
            break
        rows.extend(batch)
        oldest_mts = batch[-1][0]
        print(f"  got {len(batch)} rows, oldest so far: {datetime.fromtimestamp(oldest_mts/1000, tz=timezone.utc).date()}")
        if oldest_mts >= cursor:
            break  # no progress, avoid infinite loop
        cursor = oldest_mts
        time.sleep(REQUEST_SLEEP_SEC)

    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_utc", "mts", "offer_id", "amount", "daily_rate", "apr", "period_days"])
        for r in rows:
            mts, offer_id, amount, rate, period = r[0], r[1], r[2], r[3], r[4]
            ts = datetime.fromtimestamp(mts / 1000, tz=timezone.utc).isoformat()
            w.writerow([ts, mts, offer_id, amount, rate, rate * 365, period])
    print(f"  wrote {len(rows)} rows -> {out_path}")


def fetch_candles(symbol_expr: str, start_dt: datetime, end_dt: datetime, out_path: str, timeframe: str = "1h"):
    print(f"Fetching {timeframe} candles for {symbol_expr}...")
    cursor = ms(end_dt)
    start_ms = ms(start_dt)
    rows = []
    while cursor > start_ms:
        url = f"{API_PUB}/v2/candles/trade:{timeframe}:{symbol_expr}/hist?limit=10000&end={cursor}&sort=-1"
        batch = _get(url)
        if not batch:
            break
        rows.extend(batch)
        oldest_mts = batch[-1][0]
        if oldest_mts >= cursor:
            break
        cursor = oldest_mts
        time.sleep(REQUEST_SLEEP_SEC)

    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_utc", "mts", "open", "close", "high", "low", "volume"])
        for r in rows:
            mts, o, c, h, l, v = r
            ts = datetime.fromtimestamp(mts / 1000, tz=timezone.utc).isoformat()
            w.writerow([ts, mts, o, c, h, l, v])
    print(f"  wrote {len(rows)} rows -> {out_path}")


def fetch_stats(key_expr: str, start_dt: datetime, end_dt: datetime, out_path: str):
    print(f"Fetching stats {key_expr}...")
    cursor = ms(end_dt)
    start_ms = ms(start_dt)
    rows = []
    while cursor > start_ms:
        url = f"{API_PUB}/v2/stats1/{key_expr}/hist?limit=10000&end={cursor}&sort=-1"
        batch = _get(url)
        if not batch:
            break
        rows.extend(batch)
        oldest_mts = batch[-1][0]
        if oldest_mts >= cursor:
            break
        cursor = oldest_mts
        time.sleep(REQUEST_SLEEP_SEC)

    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_utc", "mts", "value"])
        for r in rows:
            mts, val = r[0], r[1]
            ts = datetime.fromtimestamp(mts / 1000, tz=timezone.utc).isoformat()
            w.writerow([ts, mts, val])
    print(f"  wrote {len(rows)} rows -> {out_path}")


def fetch_own_funding_trades(symbol: str, api_key: str, api_secret: str, out_path: str):
    print("Fetching YOUR OWN historical funding trades (requires funding-read API key)...")
    rows = _signed_post(f"auth/r/funding/trades/{symbol}/hist", api_key, api_secret, {"limit": 2500})
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_utc", "mts", "offer_id", "amount", "daily_rate", "apr", "period_days"])
        for r in rows:
            mts = r[1]
            ts = datetime.fromtimestamp(mts / 1000, tz=timezone.utc).isoformat()
            w.writerow([ts, mts, r[0], r[4], r[5], r[5] * 365, r[6]])
    print(f"  wrote {len(rows)} rows -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=float, default=5, help="How many years of history to pull (default 5)")
    ap.add_argument("--symbol", default="fUSD")
    ap.add_argument("--api-key", default=os.environ.get("BFX_API_KEY"))
    ap.add_argument("--api-secret", default=os.environ.get("BFX_API_SECRET"))
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=args.years * 365)

    fetch_funding_trades(args.symbol, start_dt, end_dt, os.path.join(OUT_DIR, f"funding_trades_{args.symbol}.csv"))

    for period_code in ["p2", "p30", "p120"]:
        fetch_candles(f"{args.symbol}:{period_code}", start_dt, end_dt,
                      os.path.join(OUT_DIR, f"funding_candles_{args.symbol}_{period_code}.csv"))

    fetch_stats(f"funding.size:1m:{args.symbol}:long", start_dt, end_dt,
                os.path.join(OUT_DIR, "funding_size_outstanding.csv"))

    fetch_candles("tBTCUSD", start_dt, end_dt,
                  os.path.join(OUT_DIR, "btc_price_daily.csv"), timeframe="1D")

    if args.api_key and args.api_secret:
        fetch_own_funding_trades(args.symbol, args.api_key, args.api_secret,
                                  os.path.join(OUT_DIR, "your_own_funding_trades.csv"))
    else:
        print("No API key/secret provided -- skipping your own historical funding trades "
              "(optional, only needed for personal backtest, not for building the general model).")

    print(f"\nDone. Zip up ./{OUT_DIR}/ and upload it back into the chat.")


if __name__ == "__main__":
    main()
