"""Thread-safe trade store, blotter and PnL calculation engine.

Maintains complete trade history, execution metrics, and persists/restores
from the events log.
"""
from __future__ import annotations

import csv
import io
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional


@dataclass
class TradeRecord:
    trade_id: str
    timestamp: str
    symbol: str
    side: str                            # buy | sell
    qty: float
    price: float
    notional: float
    order_type: str = "limit"            # limit | market
    bot_name: str = "desk"               # market_maker | house | directional | manual
    status: str = "filled"               # new | filled | cancelled | rejected
    reason: str = ""
    realized_pnl: float = 0.0

    @property
    def is_buy(self) -> bool:
        return self.side.lower() == "buy"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class PerformanceMetrics:
    total_trades: int = 0
    filled_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    win_rate_pct: float = 0.0
    total_realized_pnl: float = 0.0
    total_volume: float = 0.0
    profit_factor: float = 0.0
    current_balance: float = 0.0
    daily_drawdown_pct: float = 0.0


class TradeStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._trades: List[TradeRecord] = []
        self._by_id: Dict[str, TradeRecord] = {}
        self._listeners: List[Callable[[TradeRecord], None]] = []

    def add_listener(self, listener: Callable[[TradeRecord], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[TradeRecord], None]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def record(self, trade: TradeRecord) -> TradeRecord:
        with self._lock:
            if trade.trade_id in self._by_id:
                # Update existing record
                idx = self._trades.index(self._by_id[trade.trade_id])
                self._trades[idx] = trade
                self._by_id[trade.trade_id] = trade
            else:
                self._trades.append(trade)
                self._by_id[trade.trade_id] = trade

            callbacks = list(self._listeners)

        # Notify outside lock
        for cb in callbacks:
            try:
                cb(trade)
            except Exception:
                pass

        return trade

    def get_trades(
        self,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        status: Optional[str] = None,
        bot_name: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[TradeRecord]:
        with self._lock:
            results = self._trades
            if symbol:
                results = [t for t in results if t.symbol.lower() == symbol.lower()]
            if side:
                results = [t for t in results if t.side.lower() == side.lower()]
            if status:
                results = [t for t in results if t.status.lower() == status.lower()]
            if bot_name:
                results = [t for t in results if t.bot_name.lower() == bot_name.lower()]

            # Return newest first by default
            return list(reversed(results))[offset : offset + limit]

    def get_metrics(
        self, initial_balance: float = 100_000.0, current_balance: Optional[float] = None
    ) -> PerformanceMetrics:
        with self._lock:
            filled = [t for t in self._trades if t.status == "filled"]
            closed = [t for t in filled if abs(t.realized_pnl) > 1e-9]

            wins = [t for t in closed if t.realized_pnl > 0]
            losses = [t for t in closed if t.realized_pnl < 0]
            breakevens = [t for t in closed if abs(t.realized_pnl) < 1e-9]

            win_count = len(wins)
            loss_count = len(losses)
            total_closed = len(closed)

            win_rate = (win_count / total_closed * 100.0) if total_closed > 0 else 0.0
            gross_profit = sum(t.realized_pnl for t in wins)
            gross_loss = abs(sum(t.realized_pnl for t in losses))
            total_pnl = sum(t.realized_pnl for t in filled)
            total_vol = sum(t.notional for t in filled)

            profit_factor = (
                (gross_profit / gross_loss)
                if gross_loss > 0
                else (999.0 if gross_profit > 0 else 0.0)
            )

            curr_bal = current_balance if current_balance is not None else (initial_balance + total_pnl)
            drawdown = 0.0
            if initial_balance > 0 and curr_bal < initial_balance:
                drawdown = ((initial_balance - curr_bal) / initial_balance) * 100.0

            return PerformanceMetrics(
                total_trades=len(self._trades),
                filled_trades=len(filled),
                winning_trades=win_count,
                losing_trades=loss_count,
                breakeven_trades=len(breakevens),
                win_rate_pct=round(win_rate, 2),
                total_realized_pnl=round(total_pnl, 2),
                total_volume=round(total_vol, 2),
                profit_factor=round(profit_factor, 2),
                current_balance=round(curr_bal, 2),
                daily_drawdown_pct=round(drawdown, 2),
            )

    def export_csv(self) -> str:
        with self._lock:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Trade ID",
                "Timestamp",
                "Symbol",
                "Side",
                "Type",
                "Qty",
                "Price",
                "Notional",
                "Bot",
                "Status",
                "Realized PnL",
                "Reason",
            ])
            for t in self._trades:
                writer.writerow([
                    t.trade_id,
                    t.timestamp,
                    t.symbol,
                    t.side,
                    t.order_type,
                    t.qty,
                    t.price,
                    t.notional,
                    t.bot_name,
                    t.status,
                    t.realized_pnl,
                    t.reason,
                ])
            return output.getvalue()

    def load_from_jsonl(self, path: str) -> int:
        if not os.path.exists(path):
            return 0
        loaded = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("type") in ("order", "trade"):
                        trade = TradeRecord(
                            trade_id=str(data.get("order_id", f"hist-{loaded+1}")),
                            timestamp=str(data.get("timestamp", datetime.now(timezone.utc).isoformat())),
                            symbol=str(data.get("symbol", "BTCUSD")),
                            side=str(data.get("side", "buy")),
                            qty=float(data.get("qty", 0.0)),
                            price=float(data.get("price", 0.0)),
                            notional=float(data.get("notional", data.get("qty", 0.0) * data.get("price", 0.0))),
                            order_type=str(data.get("order_type", "limit")),
                            bot_name=str(data.get("bot_name", data.get("intent", "desk"))),
                            status=str(data.get("status", "filled")),
                            reason=str(data.get("reason", "")),
                            realized_pnl=float(data.get("realized_pnl", 0.0)),
                        )
                        self.record(trade)
                        loaded += 1
                except Exception:
                    continue
        return loaded
