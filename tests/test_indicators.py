import pytest

from crokbot.math.indicators import (
    compute_state,
    mid_price,
    order_imbalance,
    price_change_bps,
    realized_vol,
    spread,
    spread_bps,
)
from crokbot.state import BookLevel, OrderBook


def test_mid_price():
    assert mid_price(100.0, 102.0) == 101.0
    assert mid_price(None, 102.0) is None


def test_spread_bps():
    assert spread(100.0, 102.0) == 2.0
    assert spread_bps(100.0, 100.02) == pytest.approx((0.02 / 100.01) * 10000, rel=1e-6)


def test_order_imbalance():
    assert order_imbalance(10, 0) == 1.0
    assert order_imbalance(0, 10) == -1.0
    assert order_imbalance(5, 5) == 0.0
    assert order_imbalance(0, 0) == 0.0


def test_realized_vol():
    assert realized_vol([100.0] * 5) == 0.0
    assert realized_vol([100.0]) == 0.0
    assert realized_vol([100, 101, 102, 103, 104]) > 0.0


def test_price_change_bps():
    assert abs(price_change_bps(101.0, 100.0) - 100.0) < 1e-9
    assert price_change_bps(100.0, 0.0) == 0.0


def test_compute_state():
    book = OrderBook(
        symbol="BTCUSD",
        bids=[BookLevel(100.0, 1.0), BookLevel(99.9, 2.0)],
        asks=[BookLevel(100.02, 1.0), BookLevel(100.1, 2.0)],
    )
    s = compute_state(book, [99.8, 99.9, 100.0], reference_price=100.0)
    assert s.symbol == "BTCUSD"
    assert s.bid_price == 100.0 and s.ask_price == 100.02
    assert s.spread_bps > 0
    assert s.bid_depth == 3.0 and s.ask_depth == 3.0