"""The desk — the "Grok Bot" orchestrator that runs the three bots.

Grok's role (per the article) is to RUN the desk: schedule seats, wire the
decision layer, and order the pipeline. Every order still funnels through the
deterministic risk gate. Jev makes the snap calls; code pulls the trigger.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from ..config import Config
from ..execution.broker import Broker, Intent, Order
from ..risk.engine import RiskEngine, gate_and_place, RiskDecision
from ..state import ComputedState, Inventory
from .bots import Bot, DirectionalBot, HouseBot, MarketMakerBot
from .trust import next_cap

# Optional import to avoid circular dependencies
try:
    from ..dashboard.store import TradeRecord, TradeStore
except ImportError:
    TradeStore = None  # type: ignore
    TradeRecord = None  # type: ignore


class Desk:
    def __init__(
        self,
        cfg: Config,
        broker: Broker,
        bots: Optional[List[Bot]] = None,
        trade_store: Optional[TradeStore] = None,
        event_callback: Optional[Callable[[Dict], None]] = None,
    ):
        self.cfg = cfg
        self.broker = broker
        self.bots = bots or [
            MarketMakerBot(cfg),
            HouseBot(cfg),
            DirectionalBot(cfg),
        ]
        self.risk = RiskEngine(cfg, broker)
        # trust-ladder scales the desk's total exposure cap
        self.risk.notional_cap = next_cap(cfg.max_position_notional, cfg.trust_stage)
        self.inventory = Inventory()
        self.trade_store = trade_store
        self.event_callback = event_callback
        self._reject_seq = 0
        self._events = open(cfg.events_path, "a", encoding="utf-8")
        if hasattr(self.broker, "add_fill_listener"):
            self.broker.add_fill_listener(self._on_broker_fill)

    def _on_broker_fill(self, order: Order, fill_record: Dict) -> None:
        """Sync asynchronous/resting limit fills (e.g. PaperBroker.sweep) into logs & TradeStore."""
        if order.order_type == "market":
            # Market orders fill synchronously inside broker.place() and are handled in apply()
            return
        ts = str(fill_record.get("timestamp", datetime.now(timezone.utc).isoformat()))
        bot_name = getattr(order, "bot_name", "") or "market_maker"
        self._log({
            "type": "fill",
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side,
            "qty": order.qty,
            "price": fill_record.get("price", order.price),
            "notional": fill_record.get("notional", order.notional),
            "realized_pnl": fill_record.get("realized_pnl", 0.0),
            "bot_name": bot_name,
            "status": "filled",
            "timestamp": ts,
        })
        if self.trade_store and TradeRecord:
            self.trade_store.record(TradeRecord(
                trade_id=str(order.order_id),
                timestamp=ts,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                price=float(fill_record.get("price", order.price)),
                notional=float(fill_record.get("notional", order.notional)),
                order_type=order.order_type,
                bot_name=bot_name,
                status="filled",
                reason=order.reason or "limit quote filled",
                realized_pnl=float(fill_record.get("realized_pnl", 0.0)),
            ))

    # -- helpers --------------------------------------------------------------

    def _log(self, event: Dict) -> None:
        if "timestamp" not in event:
            event["timestamp"] = datetime.now(timezone.utc).isoformat()
        try:
            self._events.write(json.dumps(event) + "\n")
            self._events.flush()
        except Exception:
            pass

        if self.event_callback:
            try:
                self.event_callback(event)
            except Exception:
                pass

    def net_qty(self, symbol: str) -> float:
        return self.broker.positions().get(symbol, 0.0)

    # -- apply intents through the risk gate ----------------------------------

    def apply(self, intent: Intent, state: ComputedState, bot_name: str = "desk") -> List[Order]:
        """Turn one intent into orders, gate each, place on the broker."""
        placed: List[Order] = []

        if intent.action == "cancel":
            # pull resting orders for this symbol
            for o in self.broker.open_orders():
                if o.symbol == intent.symbol:
                    if self.broker.cancel(o.order_id):
                        placed.append(o)
                        self._log({
                            "type": "order_cancel",
                            "order_id": o.order_id,
                            "symbol": o.symbol,
                            "side": o.side,
                            "qty": o.qty,
                            "price": o.price,
                            "status": "cancelled",
                            "bot_name": bot_name,
                            "intent": intent.reason,
                        })
            return placed

        order = intent.to_order()
        if order is None:
            return placed
        order.bot_name = bot_name

        result = gate_and_place(
            self.risk, self.broker, order,
            ref=state.reference_price if state.reference_price else state.mid_price,
            bid=state.bid_price, ask=state.ask_price,
            position=self.net_qty(intent.symbol),
        )

        notional = order.qty * (order.price if order.price > 0 else state.mid_price)
        if not order.order_id:
            self._reject_seq += 1
            oid = f"gated-reject-{self._reject_seq}"
        else:
            oid = order.order_id

        event_payload = {
            "type": "order",
            "order_id": oid,
            "symbol": order.symbol,
            "side": order.side,
            "qty": order.qty,
            "price": order.price if order.price > 0 else state.mid_price,
            "notional": notional,
            "order_type": order.order_type,
            "post_only": order.post_only,
            "status": order.status,
            "reason": order.reason,
            "bot_name": bot_name,
            "intent": intent.reason,
            "realized_pnl": 0.0,
        }

        # Check if broker filled it and reported realized pnl
        if hasattr(self.broker, "fills") and self.broker.fills:
            latest_fill = self.broker.fills[-1]
            if latest_fill.get("order_id") == order.order_id:
                event_payload["realized_pnl"] = latest_fill.get("realized_pnl", 0.0)

        self._log(event_payload)

        if self.trade_store and TradeRecord:
            trade = TradeRecord(
                trade_id=str(event_payload["order_id"]),
                timestamp=str(event_payload.get("timestamp", datetime.now(timezone.utc).isoformat())),
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                price=float(event_payload["price"]),
                notional=float(notional),
                order_type=order.order_type,
                bot_name=bot_name,
                status=order.status,
                reason=order.reason or intent.reason,
                realized_pnl=float(event_payload["realized_pnl"]),
            )
            self.trade_store.record(trade)

        placed.append(result)
        return placed

    # -- one tick -------------------------------------------------------------

    def tick(self, state: ComputedState) -> List[Order]:
        """Run every enabled bot once and place the gated orders."""
        # Log market telemetry
        tick_event = {
            "type": "tick",
            "symbol": state.symbol,
            "mid_price": state.mid_price,
            "spread_bps": state.spread_bps,
            "order_imbalance": state.order_imbalance,
            "realized_vol": state.realized_vol,
            "bid_price": state.bid_price,
            "ask_price": state.ask_price,
            "cash_balance": self.broker.balance(),
            "positions": self.broker.positions(),
        }
        if state.extra:
            for k in ("eth_btc_ratio", "eth_btc_change_bps", "eth_btc_regime"):
                if k in state.extra:
                    tick_event[k] = state.extra[k]
        self._log(tick_event)

        all_orders: List[Order] = []
        for bot in self.bots:
            if not getattr(bot, "enabled", True):
                continue
            bot_name = getattr(bot, "name", "bot")
            intents = bot.step(state, net_qty=self.net_qty(state.symbol), target_qty=0.0)
            # Refresh resting quotes for this bot & symbol before placing new two-sided quotes
            if any(i.action == "quote" for i in intents):
                for existing in list(self.broker.open_orders()):
                    if existing.symbol == state.symbol and getattr(existing, "bot_name", "") == bot_name:
                        if self.broker.cancel(existing.order_id):
                            if self.trade_store and TradeRecord and existing.order_id in self.trade_store._by_id:
                                prev = self.trade_store._by_id[existing.order_id]
                                prev.status = "cancelled"
                                self.trade_store.record(prev)
            for intent in intents:
                all_orders.extend(self.apply(intent, state, bot_name=bot_name))
        return all_orders

    def tick_pair(self, btc_state: ComputedState, eth_state: ComputedState) -> List[Order]:
        """Tick BTC and ETH markets together, enriching both with the ETH/BTC signal filter."""
        from ..math.indicators import compute_pair_signal

        pair_sig = compute_pair_signal(
            eth_prices=[eth_state.reference_price or eth_state.mid_price, eth_state.mid_price],
            btc_prices=[btc_state.reference_price or btc_state.mid_price, btc_state.mid_price],
            drop_threshold_bps=self.cfg.eth_btc_drop_threshold_bps,
            rise_threshold_bps=self.cfg.eth_btc_rise_threshold_bps,
        )
        btc_state.extra.update(pair_sig)
        eth_state.extra.update(pair_sig)

        orders: List[Order] = []
        orders.extend(self.tick(btc_state))
        orders.extend(self.tick(eth_state))
        return orders

    def kill(self) -> None:
        self.risk.kill()
        self.broker.cancel_all()
        self._log({
            "type": "kill_switch",
            "status": "engaged",
            "message": "Emergency kill switch engaged: all orders cancelled.",
        })

    def close(self) -> None:
        try:
            self._events.close()
        except Exception:
            pass
