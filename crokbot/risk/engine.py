"""Deterministic risk engine. Runs before EVERY order. No model gets a vote.

This is the layer that keeps the other four honest (article §5): hard-coded,
deterministic, checked first. Whatever Jev or the policy says, these gates are
the last word before an order reaches the broker.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from ..config import Config
from ..execution.broker import Broker, Order


@dataclass
class RiskDecision:
    ok: bool
    reason: str = ""


class RiskEngine:
    def __init__(self, cfg: Config, broker: Broker):
        self.cfg = cfg
        self.broker = broker
        self._kill = False
        self._day_start_balance = broker.balance() if broker.balance() > 0 else cfg.initial_balance
        self._today_realized = 0.0
        # effective per-position cap; the desk scales it by trust stage
        self.notional_cap = cfg.max_position_notional

    # -- kill switch (only a human or the trust ladder flips this off) --
    def kill(self) -> None:
        self._kill = True

    @property
    def killed(self) -> bool:
        return self._kill

    def update_day_start(self, balance: float) -> None:
        self._day_start_balance = balance

    @property
    def daily_loss_pct(self) -> float:
        if self._day_start_balance <= 0:
            return 0.0
        equity = self.broker.balance()
        if hasattr(self.broker, "positions"):
            pos = self.broker.positions()
            market_prices = getattr(self.broker, "market_prices", {}) or {}
            fallback_price = getattr(self.broker, "current_price", None) or 0.0
            for sym, qty in pos.items():
                px = market_prices.get(sym, fallback_price) or 0.0
                if px > 0:
                    equity += qty * px
        return max(0.0, (self._day_start_balance - equity) / self._day_start_balance * 100.0)

    def check(self, order: Order, reference_price: Optional[float] = None,
              best_bid: Optional[float] = None, best_ask: Optional[float] = None,
              position: float = 0.0) -> RiskDecision:
        """Gate a single order. Returns the first failing reason, else ok."""
        cfg = self.cfg

        if self._kill:
            return RiskDecision(False, "kill switch engaged")

        if self.daily_loss_pct >= cfg.max_daily_loss_pct:
            return RiskDecision(False, f"daily loss limit {cfg.max_daily_loss_pct}% hit")

        if order.qty <= 0:
            return RiskDecision(False, "non-positive quantity")

        market_prices = getattr(self.broker, "market_prices", {}) or {}
        fallback_px = market_prices.get(order.symbol, getattr(self.broker, "current_price", None)) or 0.0
        eff_price = order.price if order.price > 0 else (reference_price if reference_price else fallback_px)
        eff_notional = order.qty * eff_price

        if eff_notional > cfg.max_order_notional:
            return RiskDecision(False, f"order notional {eff_notional:.0f} > max {cfg.max_order_notional:.0f}")

        # Signed position impact: allow trades that strictly reduce existing exposure
        signed_delta = order.qty if order.is_buy else -order.qty
        new_sym_pos = position + signed_delta
        is_reducing = abs(position) > 1e-12 and abs(new_sym_pos) < abs(position)

        if not is_reducing:
            sym_projected = max(abs(new_sym_pos) * eff_price, abs(position) * eff_price + eff_notional) if (
                (position >= 0 and order.is_buy) or (position <= 0 and not order.is_buy)
            ) else abs(new_sym_pos) * eff_price

            other_gross = 0.0
            if hasattr(self.broker, "positions"):
                for sym, q in self.broker.positions().items():
                    if sym == order.symbol:
                        continue
                    px = market_prices.get(sym, fallback_px) or 0.0
                    other_gross += abs(q) * px

            total_projected = other_gross + sym_projected
            worst_projected = max(sym_projected, total_projected)
            if worst_projected > self.notional_cap:
                return RiskDecision(False, f"projected exposure {worst_projected:.0f} > cap {self.notional_cap:.0f}")

        if len(self.broker.open_orders()) >= cfg.max_open_orders and order.status == "new":
            return RiskDecision(False, f"too many open orders ({cfg.max_open_orders} max)")

        # price sanity band: reject a quote that strays from reference
        if reference_price and order.order_type == "limit" and order.price > 0:
            dev = abs(order.price - reference_price) / reference_price * 100.0
            if dev > cfg.price_band_pct:
                return RiskDecision(False, f"limit price {order.price:.4f} deviates {dev:.2f}% > {cfg.price_band_pct}%")

        # self-trade prevention: don't buy above the ask or sell below the bid
        if cfg.self_trade_prevention:
            if order.is_buy and best_ask is not None and order.price >= best_ask:
                return RiskDecision(False, "self-trade: buy would cross the ask")
            if not order.is_buy and best_bid is not None and order.price <= best_bid:
                return RiskDecision(False, "self-trade: sell would cross the bid")

        return RiskDecision(True)


def gate_and_place(engine: RiskEngine, broker: Broker, order: Order,
                   ref: Optional[float] = None, bid: Optional[float] = None,
                   ask: Optional[float] = None, position: float = 0.0) -> Order:
    """The single choke-point: risk-check then place. Returns the (possibly rejected) order."""
    d = engine.check(order, ref, bid, ask, position)
    if not d.ok:
        order.status = "rejected"
        order.reason = d.reason
        return order
    return broker.place(order)