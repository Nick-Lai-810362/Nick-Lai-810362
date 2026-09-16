"""
Local, real-API-connected dashboard: 資產總覽 / 掛單詳情 / 出借歷史紀錄 / 收益與年化報酬,
with a sub-account switcher (profiles.py) so one dashboard can flip between
several Bitfinex accounts, each hitting the exchange with its own API key.

WHY THIS IS A SEPARATE LOCAL WEB SERVER, NOT A claude.ai ARTIFACT: an
Artifact page runs in a sandbox whose Content-Security-Policy blocks
fetch/XHR to any host outside a small CDN allowlist -- api.bitfinex.com is
not on it, so a browser-side Artifact page CANNOT call the live Bitfinex API
at all (this is a hard platform constraint, not a design choice). Calling
the real, authenticated API requires a real backend making the signed HTTP
request server-side, which is what this module is: a plain Python HTTP
server (stdlib only, no new dependency) that serves a single-page dashboard
and a same-origin JSON API backed by tsgex_bfx_bot.client.BitfinexClient.

Every number the dashboard can show also works with zero API keys and zero
network access, straight from this bot's own local ledger (bfx_bot_state.json)
-- live exchange data (wallet balance, live open-offer count) is an optional
overlay layered on top when a profile has working credentials, and every
live call is wrapped so a network failure or missing key degrades to
"local ledger only", never a crash.

SECURITY: binds to 127.0.0.1 by default and refuses any other host without
--allow-remote -- this can display real account balances and open orders.
"""
import argparse
import json
import logging
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import analytics
from .client import BitfinexClient
from .constants import PLATFORM_FEE_HIDDEN, PLATFORM_FEE_STANDARD
from .ledger import load_state
from .mock_client import MockBitfinexClient
from .profiles import Profile, find_profile, load_profiles

log = logging.getLogger("tsgex_bot.webapp")

STATIC_DIR = Path(__file__).resolve().parent / "webapp_static"


def build_client(profile: Profile, mock: bool):
    if mock:
        return MockBitfinexClient()
    if not profile.has_credentials():
        return None
    return BitfinexClient(os.environ.get(profile.api_key_env), os.environ.get(profile.api_secret_env))


def platform_fee_for(profile: Profile) -> float:
    return PLATFORM_FEE_HIDDEN if profile.order_visibility == "hidden" else PLATFORM_FEE_STANDARD


def live_wallet_snapshot(client) -> dict:
    if client is None:
        return {"available": False, "error": "此帳戶尚未設定 API 金鑰環境變數", "funding_wallet_usd": None}
    try:
        wallets = client.get_wallet_balances()
        funding_usd = None
        for w in wallets:
            if len(w) >= 2 and w[0] == "funding" and str(w[1]).upper() == "USD":
                funding_usd = {"balance": w[2] if len(w) > 2 else None,
                                "balance_available": w[4] if len(w) > 4 else None}
                break
        return {"available": True, "error": None, "funding_wallet_usd": funding_usd}
    except Exception as e:
        log.warning(f"live wallet fetch failed: {e}")
        return {"available": False, "error": str(e), "funding_wallet_usd": None}


def live_open_offers_snapshot(client, symbol: str) -> dict:
    if client is None:
        return {"available": False, "error": "此帳戶尚未設定 API 金鑰環境變數", "count": None}
    try:
        offers = client.get_active_funding_offers(symbol)
        return {"available": True, "error": None, "count": len(offers)}
    except Exception as e:
        log.warning(f"live offers fetch failed: {e}")
        return {"available": False, "error": str(e), "count": None}


class DashboardHandler(BaseHTTPRequestHandler):
    profiles = []      # set on the class by main() before serve_forever()
    mock = False

    def log_message(self, fmt, *args):
        log.info("%s - %s" % (self.address_string(), fmt % args))

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _profile_from_query(self, qs: dict) -> Profile:
        name = qs.get("profile", [None])[0]
        return find_profile(self.profiles, name)

    def do_GET(self):
        parsed = urlsplit(self.path)
        qs = parse_qs(parsed.query)
        try:
            if parsed.path in ("/", "/index.html"):
                self._send_html((STATIC_DIR / "dashboard.html").read_text(encoding="utf-8"))
            elif parsed.path == "/api/profiles":
                self._send_json([{"name": p.name, "symbol": p.symbol,
                                   "has_credentials": self.mock or p.has_credentials()} for p in self.profiles])
            elif parsed.path == "/api/overview":
                self._handle_overview(qs)
            elif parsed.path == "/api/offers":
                self._handle_offers(qs)
            elif parsed.path == "/api/history":
                self._handle_history(qs)
            elif parsed.path == "/api/earnings":
                self._handle_earnings(qs)
            elif parsed.path == "/api/apr":
                self._handle_apr(qs)
            else:
                self._send_json({"error": "not found"}, status=404)
        except KeyError as e:
            self._send_json({"error": str(e)}, status=400)
        except Exception as e:
            log.exception("request failed")
            self._send_json({"error": str(e)}, status=500)

    def _handle_overview(self, qs):
        profile = self._profile_from_query(qs)
        state = load_state(profile.state_path)
        client = build_client(profile, self.mock)
        self._send_json({"overview": analytics.overview(state), "live": live_wallet_snapshot(client)})

    def _handle_offers(self, qs):
        profile = self._profile_from_query(qs)
        state = load_state(profile.state_path)
        client = build_client(profile, self.mock)
        self._send_json({"offers": analytics.open_offers(state, platform_fee=platform_fee_for(profile)),
                          "live": live_open_offers_snapshot(client, profile.symbol)})

    def _handle_history(self, qs):
        profile = self._profile_from_query(qs)
        state = load_state(profile.state_path)
        tenor = qs.get("tenor", [None])[0]
        status = qs.get("status", [None])[0]
        start = qs.get("start", [None])[0]
        end = qs.get("end", [None])[0]
        rows = analytics.history(
            state,
            tenor=int(tenor) if tenor else None,
            status=status or None,
            start=datetime.fromisoformat(start).replace(tzinfo=timezone.utc) if start else None,
            end=datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else None,
            platform_fee=platform_fee_for(profile),
        )
        self._send_json({"history": rows})

    def _handle_earnings(self, qs):
        profile = self._profile_from_query(qs)
        state = load_state(profile.state_path)
        self._send_json(analytics.earnings(state))

    def _handle_apr(self, qs):
        profile = self._profile_from_query(qs)
        state = load_state(profile.state_path)
        self._send_json(analytics.apr(state, datetime.now(timezone.utc), platform_fee=platform_fee_for(profile)))


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__ or "TSGEX Bitfinex Funding Bot -- local dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--profiles-file", default=None,
                     help="Path to a JSON file describing multiple sub-accounts to switch between "
                          "(see profiles.py for the format). Defaults to a single 'default' profile "
                          "matching cli.py's own BFX_API_KEY/BFX_API_SECRET/bfx_bot_state.json defaults.")
    ap.add_argument("--mock", action="store_true",
                     help="Use MockBitfinexClient for every profile's live data instead of a real "
                          "Bitfinex connection -- try every view with zero API keys or network access.")
    ap.add_argument("--allow-remote", action="store_true",
                     help="Required to bind to any host other than 127.0.0.1/localhost. This dashboard "
                          "can display real account balances and open orders -- do not expose it on a "
                          "network without understanding that risk.")
    return ap


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
    args = build_arg_parser().parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        raise SystemExit(
            f"REFUSING TO BIND to {args.host}: this dashboard can display real account balances and "
            f"open orders. Pass --allow-remote if you specifically intend to expose it beyond this "
            f"machine (e.g. behind your own auth/VPN) -- otherwise use the default 127.0.0.1."
        )

    profiles = load_profiles(args.profiles_file)
    log.info(f"Loaded {len(profiles)} profile(s): {[p.name for p in profiles]}")
    if args.mock:
        log.info("MOCK mode: every profile's live data comes from MockBitfinexClient, not a real Bitfinex connection.")
    else:
        for p in profiles:
            if not p.has_credentials():
                log.warning(f"Profile '{p.name}': no {p.api_key_env}/{p.api_secret_env} env vars set -- "
                            f"live data will show as unavailable; local ledger view still works.")

    DashboardHandler.profiles = profiles
    DashboardHandler.mock = args.mock
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    log.info(f"Dashboard running at http://{args.host}:{args.port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
