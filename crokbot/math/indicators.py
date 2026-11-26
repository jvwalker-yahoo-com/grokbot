"""Indicators & order-book math. Pure functions, no I/O, unit-testable.

Every number the decision layer needs is computed HERE and passed to Jev as a
figure — Jev never does arithmetic (it miscounts).
"""
from __future__ import annotations

import math
from statistics import pstdev
from typing import Dict, List, Optional, Sequence

from ..state import OrderBook


def mid_price(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    """Mid of the touch. None if either side is missing."""
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def spread(bid: float, ask: float) -> float:
    """Absolute spread."""
    return ask - bid


def spread_bps(bid: float, ask: float) -> float:
    """Spread in basis points of the mid price."""
    mid = mid_price(bid, ask)
    if not mid:
        return 0.0
    return (ask - bid) / mid * 10_000.0


def order_imbalance(bid_depth: float, ask_depth: float) -> float:
    """Depth imbalance in [-1, +1]. +1 all bids, -1 all asks, 0 balanced."""
    total = bid_depth + ask_depth
    if total <= 0:
        return 0.0
    return (bid_depth - ask_depth) / total


def _returns(prices: Sequence[float]) -> List[float]:
    out: List[float] = []
    for prev, cur in zip(prices, prices[1:]):
        if prev:
            out.append((cur - prev) / prev)
    return out


def realized_vol(prices: Sequence[float], annualize: bool = False) -> float:
    """Realized volatility = population std-dev of log-ish simple returns."""
    if len(prices) < 2:
        return 0.0
    r = _returns(prices)
    if not r:
        return 0.0
    sd = pstdev(r)
    return sd * math.sqrt(365.0) if annualize else sd


def realized_vol_from_log(prices: Sequence[float], annualize: bool = False) -> float:
    """Log-return realized vol (closer to market convention)."""
    if len(prices) < 2:
        return 0.0
    r = [math.log(cur / prev) for prev, cur in zip(prices, prices[1:]) if prev > 0 and cur > 0]
    if not r:
        return 0.0
    sd = pstdev(r)
    return sd * math.sqrt(365.0) if annualize else sd


def price_change_bps(current: float, reference: float) -> float:
    """Price change vs reference in basis points."""
    if not reference:
        return 0.0
    return (current - reference) / reference * 10_000.0


def compute_pair_ratio(eth_price: float, btc_price: float) -> float:
    """Synthetic ETH/BTC cross ratio computed in code."""
    if not btc_price or btc_price <= 0 or eth_price <= 0:
        return 0.0
    return round(eth_price / btc_price, 8)


def compute_pair_signal(
    eth_prices: Sequence[float],
    btc_prices: Sequence[float],
    drop_threshold_bps: float = -15.0,
    rise_threshold_bps: float = 15.0,
) -> Dict[str, object]:
    """Compute ETH/BTC relative strength signal from ETH and BTC price histories.

    Returns dict with:
      - eth_btc_ratio: current ETH/BTC price ratio
      - eth_btc_change_bps: basis-point change from start of window to current
      - eth_btc_regime: 'falling_sharply' | 'rising_sharply' | 'neutral'
    """
    if not eth_prices or not btc_prices:
        return {
            "eth_btc_ratio": 0.0,
            "eth_btc_change_bps": 0.0,
            "eth_btc_regime": "neutral",
        }

    curr_ratio = compute_pair_ratio(eth_prices[-1], btc_prices[-1])
    ref_ratio = compute_pair_ratio(eth_prices[0], btc_prices[0])
    change_bps = round(price_change_bps(curr_ratio, ref_ratio), 4) if ref_ratio > 0 else 0.0

    if change_bps <= drop_threshold_bps:
        regime = "falling_sharply"
    elif change_bps >= rise_threshold_bps:
        regime = "rising_sharply"
    else:
        regime = "neutral"

    return {
        "eth_btc_ratio": curr_ratio,
        "eth_btc_change_bps": change_bps,
        "eth_btc_regime": regime,
    }


def compute_state(book: OrderBook, prices: Sequence[float], reference_price: float,
                  near_levels: int = 3, extra: Optional[Dict[str, object]] = None) -> "object":
    """Build a ComputedState straight from an OrderBook + a price series."""
    from ..state import ComputedState

    bid = book.best_bid
    ask = book.best_ask
    mid = mid_price(bid, ask)
    if bid is None or ask is None or mid is None:
        raise ValueError("order book has no two-sided touch")

    return ComputedState(
        symbol=book.symbol,
        mid_price=round(mid, 8),
        spread=round(spread(bid, ask), 8),
        spread_bps=round(spread_bps(bid, ask), 4),
        order_imbalance=round(order_imbalance(book.bid_depth, book.ask_depth), 6),
        near_imbalance=round(order_imbalance(book.near_bid(near_levels), book.near_ask(near_levels)), 6),
        realized_vol=round(realized_vol_from_log(prices), 6),
        price_change_bps=round(price_change_bps(mid, reference_price), 4),
        reference_price=reference_price,
        bid_depth=round(book.bid_depth, 6),
        ask_depth=round(book.ask_depth, 6),
        bid_price=bid,
        ask_price=ask,
        extra=dict(extra) if extra else {},
    )