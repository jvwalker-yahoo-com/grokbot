"""Execution layer: the Broker protocol, Order/Intent types, and brokers.

The risk engine gates every order BEFORE it reaches a broker. Brokers implement
the same protocol so paper and eToro swap interchangeably.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Side:
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    symbol: str
    side: str                      # "buy" | "sell"
    qty: float
    price: float                   # 0.0 => market order
    order_type: str = "limit"      # "limit" | "market"
    post_only: bool = False
    order_id: str = ""
    status: str = "new"            # new | filled | partial | cancelled | rejected
    reason: str = ""
    bot_name: str = ""

    @property
    def is_buy(self) -> bool:
        return self.side == Side.BUY

    @property
    def notional(self) -> float:
        return self.qty * self.price

    def effective_notional(self, reference_price: Optional[float] = None) -> float:
        px = self.price if self.price > 0 else (reference_price or 0.0)
        return self.qty * px


@dataclass
class Intent:
    """A policy decision BEFORE the risk gate. It may fan out to 0+ orders."""
    symbol: str
    action: str = "noop"            # quote | cancel | buy | sell | rebalance | noop
    side: Optional[str] = None
    price: Optional[float] = None
    qty: Optional[float] = None
    post_only: bool = False
    reason: str = ""

    def to_order(self) -> Optional[Order]:
        if self.action in ("noop", "cancel") or self.side is None:
            return None
        if self.qty is None or self.qty <= 0:
            return None
        price = self.price if self.price is not None else 0.0
        return Order(
            symbol=self.symbol,
            side=self.side,
            qty=self.qty,
            price=price,
            order_type="market" if price <= 0 else "limit",
            post_only=self.post_only,
        )


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: str
    qty: float
    price: float


class Broker(ABC):
    """Anything that can place orders and report positions/phils."""

    @abstractmethod
    def place(self, order: Order) -> Order:
        """Submit an order and return it with broker-assigned id/status."""

    @abstractmethod
    def cancel(self, order_id: str) -> bool: ...

    @abstractmethod
    def positions(self) -> Dict[str, float]:
        """symbol -> net qty."""

    @abstractmethod
    def balance(self) -> float: ...

    @abstractmethod
    def open_orders(self) -> List[Order]: ...

    def cancel_all(self) -> int:
        n = 0
        for o in self.open_orders():
            if self.cancel(o.order_id):
                n += 1
        return n