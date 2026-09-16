import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from tsgex_bfx_bot.client import BitfinexClient, extract_offer_id


def test_signed_post_request_url_has_no_doubled_api_prefix():
    """Regression for a real bug found via a live call with a real API key
    (see CHANGELOG.md "v5.9"): the HTTP request path must be "/v2/<endpoint>"
    (matching the public endpoints), NOT "/api/v2/<endpoint>" -- the
    "/api/v2/" prefix belongs only in the HMAC signature payload string,
    per Bitfinex's own documented (if easy to misread) convention. Using it
    for the request URL too sent every authenticated call to a URL that
    doesn't exist (a live 404)."""
    client = BitfinexClient(api_key="k", api_secret="s")
    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["url"] = req.full_url
        captured["signature"] = req.headers["Bfx-signature"]
        captured["nonce"] = req.headers["Bfx-nonce"]
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        resp.read.return_value = b"{}"
        return resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client._signed_post("auth/r/permissions", {})

    assert captured["url"] == "https://api.bitfinex.com/v2/auth/r/permissions"

    expected_sig = hmac.new(
        b"s", f"/api/v2/auth/r/permissions{captured['nonce']}{json.dumps({})}".encode(), hashlib.sha384
    ).hexdigest()
    assert captured["signature"] == expected_sig


def test_extract_offer_id_mock_shape():
    mock_offer = [1001, "fUSD", 123456789, None, 500.0, 500.0, "LIMIT", None, None, 0,
                  "ACTIVE", None, None, None, 0.0002, 2]
    assert extract_offer_id(mock_offer) == 1001


def test_extract_offer_id_live_notification_envelope_shape():
    # [MTS, TYPE, MESSAGE_ID, null, [offer_data...], CODE, STATUS, TEXT]
    live_resp = [1234567890, "fon-req", None, None, [55555, "fUSD", None], "SUCCESS", "ok", "Submitted"]
    assert extract_offer_id(live_resp) == 55555


def test_extract_offer_id_unknown_shape_returns_none():
    assert extract_offer_id({"unexpected": "dict"}) is None
    assert extract_offer_id([]) is None
    assert extract_offer_id(None) is None
