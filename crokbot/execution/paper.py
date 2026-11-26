"""PaperBroker — an in-memory simulator with a simple fill model.

Keeps a book of resting limit orders and fills them against a supplied market
price (mark-to-market). Market orders fill immediately at the given price.
Enough realism to exercise the risk gate, inventory tracking, and the house
bot's delta-neutral rebalancing without touching real money.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .broker import Broker, Order

_next_id = [0]


def _new_id() -> str:
    _next_id[0] += 1
    return f"paper-{_next_id[0]}"


class PaperBroker(Broker):
    def __init__(self, initial_balance: float = 100_000.0):
        self._balance = initial_balance
        self._orders: Dict[str, Order] = {}
        self._pos: Dict[str, float] = {}
        self._avg: Dict[str, float] = {}
        self._fills: List = []
        self._fill_listeners: List[Callable[[Order, Dict], None]] = []
        self.current_price: Optional[float] = None
        self.market_prices: Dict[str, float] = {}

    def add_fill_listener(self, cb: Callable[[Order, Dict], None]) -> None:
        self._fill_listeners.append(cb)

    def set_market(self, symbol: str, price: float) -> None:
        self.current_price = price
        self.market_prices[symbol] = price

    def place(self, order: Order) -> Order:
        order.order_id = _new_id()
        self._orders[order.order_id] = order
        if order.order_type == "market" or order.price <= 0:
            mkt_price = self.market_prices.get(order.symbol, self.current_price)
            if mkt_price is None:
                order.status = "rejected"
                order.reason = "no market price"
                return order
            self._apply_fill(order, mkt_price)
        return order

    def _apply_fill(self, order: Order, price: float) -> None:
        cost = order.qty * price
        self._balance += (-cost if order.is_buy else cost)
        qty = order.qty if order.is_buy else -order.qty
        old = self._pos.get(order.symbol, 0.0)
        entry_price = self._avg.get(order.symbol, price)

        # Calculate realized PnL if closing or reducing opposite position
        realized_pnl = 0.0
        if old > 1e-12 and not order.is_buy:
            closed_qty = min(old, order.qty)
            realized_pnl = (price - entry_price) * closed_qty
        elif old < -1e-12 and order.is_buy:
            closed_qty = min(abs(old), order.qty)
            realized_pnl = (entry_price - price) * closed_qty

        new = old + qty
        if abs(new) > 1e-12 and abs(old) > 1e-12 and ((old > 0 and new > 0) or (old < 0 and new < 0)):
            self._avg[order.symbol] = (entry_price * old + qty * price) / new
        elif abs(new) > 1e-12:
            self._avg[order.symbol] = price
        else:
            self._avg[order.symbol] = 0.0

        self._pos[order.symbol] = new
        order.status = "filled"
        fill_record = {
            "order_id": order.order_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": order.symbol,
            "side": order.side,
            "qty": order.qty,
            "price": price,
            "notional": cost,
            "realized_pnl": round(realized_pnl, 4),
        }
        self._fills.append(fill_record)
        for cb in list(self._fill_listeners):
            try:
                cb(order, fill_record)
            except Exception:
                pass

    def sweep(self, symbol: str, market_price: float) -> int:
        """Fill any resting limit orders crossed by the market (price-time priority)."""
        self.current_price = market_price
        self.market_prices[symbol] = market_price
        filled = 0
        for o in list(self._orders.values()):
            if o.status != "new" or o.symbol != symbol:
                continue
            hit = (o.is_buy and o.price >= market_price) or (not o.is_buy and o.price <= market_price)
            if hit:
                self._apply_fill(o, o.price)
                filled += 1
        return filled

    def cancel(self, order_id: str) -> bool:
        o = self._orders.get(order_id)
        if o and o.status == "new":
            o.status = "cancelled"
            return True
        return False

    def positions(self) -> Dict[str, float]:
        return {k: v for k, v in self._pos.items() if abs(v) > 1e-12}

    def balance(self) -> float:
        return self._balance

    def open_orders(self) -> List[Order]:
        return [o for o in self._orders.values() if o.status == "new"]

    @property
    def fills(self) -> List:
        return self._fills