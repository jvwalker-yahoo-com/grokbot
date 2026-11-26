"""Market-state types. Everything here is COMPUTED by code, never by the model.

The article's first rule: keep math in code. Jev reads dates as text and
miscounts at scale. Mid price, spread, imbalance and realized vol are computed
here and their NUMBERS are handed to Jev as words/figures.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass(frozen=True)
class BookLevel:
    price: float
    qty: float


@dataclass
class OrderBook:
    """A simplified two-sided book (top-of-book + depth on each side)."""
    symbol: str
    bids: List[BookLevel] = field(default_factory=list)  # sorted best-first
    asks: List[BookLevel] = field(default_factory=list)  # sorted best-first

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def bid_depth(self) -> float:
        return sum(l.qty for l in self.bids)

    @property
    def ask_depth(self) -> float:
        return sum(l.qty for l in self.asks)

    def near_bid(self, levels: int = 3) -> float:
        return sum(l.qty for l in self.bids[:levels])

    def near_ask(self, levels: int = 3) -> float:
        return sum(l.qty for l in self.asks[:levels])


@dataclass
class ComputedState:
    """All the numbers the decision layer receives, pre-computed."""
    symbol: str
    mid_price: float
    spread: float
    spread_bps: float
    order_imbalance: float          # in [-1, +1]: +1 all bids, -1 all asks
    near_imbalance: float           # same, over top `near_levels` levels
    realized_vol: float             # std-dev of period returns (decimal)
    price_change_bps: float         # recent price change vs reference, in bps
    reference_price: float
    bid_depth: float
    ask_depth: float
    bid_price: float
    ask_price: float
    ttl_seconds: float = 0.0
    extra: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0


@dataclass
class Inventory:
    """Net exposure per symbol — the House bot targets zero here."""
    positions: Dict[str, Position] = field(default_factory=dict)

    def qty(self, symbol: str) -> float:
        return self.positions.get(symbol, Position(symbol)).qty