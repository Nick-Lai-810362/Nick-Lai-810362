from tsgex_bfx_bot.client import extract_offer_id


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
