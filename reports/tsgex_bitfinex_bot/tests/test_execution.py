import dataclasses
from datetime import timedelta

from tsgex_bfx_bot.client import BitfinexClient
from tsgex_bfx_bot.execution import place_frr_tranche, place_tranche, reconcile_pending_offers
from tsgex_bfx_bot.mock_client import MockBitfinexClient


class NoFillMockClient(MockBitfinexClient):
    """MockBitfinexClient with the stochastic fill simulation disabled, so
    staleness (wait-timeout / rate-drift) tests aren't flaky against the
    same RNG that also drives fill probability -- fill behavior itself is
    covered separately in test_mock_client.py."""
    def get_active_funding_offers(self, symbol):
        return list(self._offers)


def test_place_tranche_dry_run_against_real_client_never_calls_submit(cfg, funded_state, now):
    class ExplodingClient(BitfinexClient):
        def submit_funding_offer(self, *a, **k):
            raise AssertionError("dry-run against the real client must not submit anything")

    rec = place_tranche(ExplodingClient(), cfg, funded_state, now, live=False,
                         amount=500.0, rate=0.0002, tenor=2)
    assert rec["amount"] == 500.0
    pos = funded_state.positions[-1]
    assert pos.status == "pending"
    assert pos.offer_id is None  # never submitted anywhere, so no real offer id


def test_place_tranche_mock_always_submits_even_without_live(cfg, funded_state, now):
    client = MockBitfinexClient()
    place_tranche(client, cfg, funded_state, now, live=False, amount=500.0, rate=0.0002, tenor=2)
    assert len(client._offers) == 1  # mock actually tracked it, enabling fill simulation
    pos = funded_state.positions[-1]
    assert pos.offer_id is not None


def test_place_frr_tranche_ledgers_nonzero_rate_not_the_api_zero_signal(cfg, funded_state, now):
    client = MockBitfinexClient()
    rec = place_frr_tranche(client, cfg, funded_state, now, live=False,
                             amount=1000.0, quoted_rate=0.0003, tenor=2)
    pos = funded_state.positions[-1]
    assert pos.daily_rate == 0.0003  # NOT 0 -- the ledger accrual proxy, decoupled from the API's rate=0


def test_reconcile_pending_offers_marks_filled_when_offer_disappears(cfg, funded_state, now):
    client = MockBitfinexClient()
    place_tranche(client, cfg, funded_state, now, live=False, amount=500.0, rate=0.0002, tenor=2)
    client._offers = []  # simulate: it filled
    events = reconcile_pending_offers(client, cfg, funded_state, {2: 0.0002}, now, live=False)
    assert events[0]["event"] == "filled"
    assert funded_state.positions[-1].status == "active"


def test_reconcile_pending_offers_noop_on_plain_dry_run_real_client(cfg, funded_state, now):
    """Against the real (non-mock) client with live=False, nothing was ever
    really submitted, so there's nothing to reconcile -- must not crash or
    call any network method."""
    class ExplodingClient(BitfinexClient):
        def get_active_funding_offers(self, *a, **k):
            raise AssertionError("must not be called in plain dry-run mode")

    events = reconcile_pending_offers(ExplodingClient(), cfg, funded_state, {2: 0.0002}, now, live=False)
    assert events == []


def test_reconcile_pending_offers_cancels_on_wait_timeout(cfg, funded_state, now):
    client = NoFillMockClient()
    place_tranche(client, cfg, funded_state, now, live=False, amount=500.0, rate=0.0002, tenor=2)
    # 2d bucket's default max wait is 6h; jump 7h ahead with the offer still open
    later = now + timedelta(hours=7)
    events = reconcile_pending_offers(client, cfg, funded_state, {2: 0.0002}, later, live=False)
    kinds = [e["event"] for e in events]
    assert "cancelled_stale" in kinds
    assert "relisted" in kinds
    cancelled = [p for p in funded_state.positions if p.status == "cancelled"]
    assert len(cancelled) == 1
    assert cancelled[0].interest_earned == 0.0


def test_reconcile_pending_offers_cancels_on_rate_drift(cfg, funded_state, now):
    client = NoFillMockClient()
    place_tranche(client, cfg, funded_state, now, live=False, amount=500.0, rate=0.0002, tenor=2)
    # drift threshold default is 1pp net; move the live 2d rate far away, same moment (no wait elapsed)
    drifted_rate = {2: 0.0010}  # ~36.5% gross vs the original ~7.3% gross
    events = reconcile_pending_offers(client, cfg, funded_state, drifted_rate, now, live=False)
    kinds = [e["event"] for e in events]
    assert "cancelled_stale" in kinds


def test_reconcile_pending_offers_leaves_fresh_close_rate_orders_alone(cfg, funded_state, now):
    client = NoFillMockClient()
    place_tranche(client, cfg, funded_state, now, live=False, amount=500.0, rate=0.0002, tenor=2)
    events = reconcile_pending_offers(client, cfg, funded_state, {2: 0.0002}, now, live=False)
    assert events == []
    assert funded_state.positions[-1].status == "pending"
