from tsgex_bfx_bot.mock_client import MockBitfinexClient


def test_funding_book_includes_core_and_thin_periods():
    """v5.2: the mock book now also quotes a spread of thinly-traded periods
    (3-29d, excluding 7/30) so --mock can exercise the generalized N-tenor
    allocation and depth filter, alongside the core liquid periods."""
    client = MockBitfinexClient()
    book = client.get_funding_book("fUSD")
    periods = {row[1] for row in book}
    assert {2, 7, 30, 120}.issubset(periods)
    assert set(MockBitfinexClient.THIN_PERIODS).issubset(periods)


def test_thin_periods_have_less_depth_than_core_2d_liquidity():
    client = MockBitfinexClient()
    book = client.get_funding_book("fUSD")
    depth = {}
    for rate, period, _, amount in book:
        depth[period] = depth.get(period, 0.0) + abs(amount)
    for t in MockBitfinexClient.THIN_PERIODS:
        assert depth[t] < depth[2]  # mirrors real liquidity concentration at 2d


def test_funding_book_2d_liquidity_dominates_by_row_count():
    client = MockBitfinexClient()
    book = client.get_funding_book("fUSD")
    counts = {}
    for row in book:
        counts[row[1]] = counts.get(row[1], 0) + 1
    assert counts[2] > counts[30] > counts[120]  # mirrors the real liquidity concentration


def test_submitted_offer_appears_in_open_offers_before_any_fill_roll():
    client = MockBitfinexClient()
    offer = client.submit_funding_offer("fUSD", 500.0, 0.0002, 2)
    assert offer[0] in [o[0] for o in client._offers]


def test_cancel_removes_offer():
    client = MockBitfinexClient()
    offer = client.submit_funding_offer("fUSD", 500.0, 0.0002, 2)
    client.cancel_funding_offer(offer[0])
    assert client._offers == []


def test_fill_probability_roughly_matches_configured_rate_over_many_trials():
    """Statistical check, not exact: over many independent 2d offers, the
    fraction that 'fill' on the first check should land near
    FILL_PROB_PER_CYCLE[2] (0.55), not e.g. near 0 or 1."""
    client = MockBitfinexClient(seed=123)
    n = 2000
    for _ in range(n):
        client.submit_funding_offer("fUSD", 500.0, 0.0002, 2)
    remaining = client.get_active_funding_offers("fUSD")
    fill_rate = 1 - len(remaining) / n
    assert 0.45 < fill_rate < 0.65  # target 0.55, generous tolerance for one Bernoulli batch


def test_different_seeds_produce_different_sequences():
    a = MockBitfinexClient(seed=1).get_funding_book("fUSD")
    b = MockBitfinexClient(seed=2).get_funding_book("fUSD")
    assert a != b


def test_same_seed_is_fully_reproducible():
    a = MockBitfinexClient(seed=7)
    b = MockBitfinexClient(seed=7)
    assert a.get_funding_book("fUSD") == b.get_funding_book("fUSD")
    assert a.get_funding_book("fUSD") == b.get_funding_book("fUSD")  # second call too
