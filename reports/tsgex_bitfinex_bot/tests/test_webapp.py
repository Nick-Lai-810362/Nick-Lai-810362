"""
Unit tests for webapp.py's pure helper functions, plus one real end-to-end
HTTP test that spins up DashboardHandler on an actual socket and hits every
route with urllib -- catching wiring bugs (route dispatch, query parsing,
JSON shape) that pure unit tests of analytics.py alone wouldn't.
"""
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import HTTPServer

import pytest

from tsgex_bfx_bot.client import BitfinexClient
from tsgex_bfx_bot.ledger import contribute_principal, mark_filled, open_position, save_state
from tsgex_bfx_bot.mock_client import MockBitfinexClient
from tsgex_bfx_bot.profiles import Profile
from tsgex_bfx_bot.webapp import (
    DashboardHandler,
    build_client,
    live_open_offers_snapshot,
    live_wallet_snapshot,
    platform_fee_for,
)


def test_build_client_mock_ignores_credentials():
    p = Profile(name="x", api_key_env="DOES_NOT_EXIST_KEY", api_secret_env="DOES_NOT_EXIST_SECRET")
    assert isinstance(build_client(p, mock=True), MockBitfinexClient)


def test_build_client_no_credentials_returns_none(monkeypatch):
    monkeypatch.delenv("TEST_WA_KEY", raising=False)
    monkeypatch.delenv("TEST_WA_SECRET", raising=False)
    p = Profile(name="x", api_key_env="TEST_WA_KEY", api_secret_env="TEST_WA_SECRET")
    assert build_client(p, mock=False) is None


def test_build_client_real_with_credentials(monkeypatch):
    monkeypatch.setenv("TEST_WA_KEY2", "k")
    monkeypatch.setenv("TEST_WA_SECRET2", "s")
    p = Profile(name="x", api_key_env="TEST_WA_KEY2", api_secret_env="TEST_WA_SECRET2")
    client = build_client(p, mock=False)
    assert isinstance(client, BitfinexClient)
    assert client.api_key == "k"


def test_platform_fee_for_standard_vs_hidden():
    assert platform_fee_for(Profile(name="x")) == pytest.approx(0.15)
    assert platform_fee_for(Profile(name="x", order_visibility="hidden")) == pytest.approx(0.18)


def test_live_wallet_snapshot_none_client_is_unavailable():
    snap = live_wallet_snapshot(None)
    assert snap["available"] is False
    assert snap["funding_wallet_usd"] is None


def test_live_wallet_snapshot_reads_funding_usd_row():
    snap = live_wallet_snapshot(MockBitfinexClient())
    assert snap["available"] is True
    assert snap["funding_wallet_usd"] is not None
    assert "balance" in snap["funding_wallet_usd"]


class _BrokenClient:
    def get_wallet_balances(self):
        raise RuntimeError("network unreachable")

    def get_active_funding_offers(self, symbol):
        raise RuntimeError("network unreachable")


def test_live_wallet_snapshot_degrades_gracefully_on_error():
    snap = live_wallet_snapshot(_BrokenClient())
    assert snap["available"] is False
    assert "network unreachable" in snap["error"]


def test_live_open_offers_snapshot_degrades_gracefully_on_error():
    snap = live_open_offers_snapshot(_BrokenClient(), "fUSD")
    assert snap["available"] is False


def test_live_open_offers_snapshot_counts_mock_offers():
    client = MockBitfinexClient()
    client.submit_funding_offer("fUSD", 500.0, 0.0002, 2)
    snap = live_open_offers_snapshot(client, "fUSD")
    assert snap["available"] is True
    assert snap["count"] == 1


@pytest.fixture
def running_server(tmp_path):
    """A real DashboardHandler bound to 127.0.0.1 on an OS-assigned port,
    serving one 'test' profile backed by a freshly built local ledger."""
    from tsgex_bfx_bot.ledger import BotState

    state_path = str(tmp_path / "state.json")
    state = BotState()
    contribute_principal(state, 10_000.0)
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    p1 = open_position(state, 1000.0, 0.0002, 2, now)
    mark_filled(p1, now)
    open_position(state, 500.0, 0.0002, 7, now)  # left pending
    save_state(state, state_path)

    DashboardHandler.profiles = [Profile(name="test", state_path=state_path)]
    DashboardHandler.mock = True
    server = HTTPServer(("127.0.0.1", 0), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _get_json(server, path):
    port = server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return json.loads(resp.read().decode())


def test_index_page_serves_html(running_server):
    port = running_server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
        body = resp.read().decode()
    assert resp.status == 200
    assert "<title>" in body


def test_api_profiles_lists_configured_profile(running_server):
    data = _get_json(running_server, "/api/profiles")
    assert data == [{"name": "test", "symbol": "fUSD", "has_credentials": True}]


def test_api_overview_reflects_ledger_state(running_server):
    data = _get_json(running_server, "/api/overview?profile=test")
    assert data["overview"]["principal_contributed_total"] == 10_000.0
    assert data["overview"]["committed_active"] == 1000.0
    assert data["overview"]["committed_pending"] == 500.0
    assert data["live"]["available"] is True  # mock mode


def test_api_offers_lists_pending_and_active(running_server):
    data = _get_json(running_server, "/api/offers?profile=test")
    assert len(data["offers"]) == 2
    assert data["live"]["available"] is True


def test_api_history_filters_by_status(running_server):
    data = _get_json(running_server, "/api/history?profile=test&status=pending")
    assert len(data["history"]) == 1
    assert data["history"][0]["status"] == "pending"


def test_api_earnings_and_apr_return_shape(running_server):
    e = _get_json(running_server, "/api/earnings?profile=test")
    a = _get_json(running_server, "/api/apr?profile=test")
    assert "realized_profit_total" in e
    assert "current_weighted_gross_apr" in a


def test_api_unknown_profile_returns_400(running_server):
    port = running_server.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/overview?profile=does-not-exist")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 400


def test_unknown_route_returns_404(running_server):
    port = running_server.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/does-not-exist")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 404
