import os
import json
import tempfile
import pytest
from datetime import datetime, timezone

from crokbot.dashboard.store import TradeRecord, TradeStore, PerformanceMetrics
from crokbot.execution.broker import Order
from crokbot.execution.paper import PaperBroker


def test_trade_record_creation():
    trade = TradeRecord(
        trade_id="T-100",
        timestamp="2026-10-28T12:00:00Z",
        symbol="BTCUSD",
        side="buy",
        qty=0.5,
        price=60000.0,
        notional=30000.0,
        order_type="limit",
        bot_name="market_maker",
        status="filled",
        reason="quote hit",
        realized_pnl=0.0
    )
    assert trade.trade_id == "T-100"
    assert trade.is_buy is True
    assert trade.notional == 30000.0


def test_trade_store_record_and_filter():
    store = TradeStore()
    store.record(TradeRecord(
        trade_id="T-1",
        timestamp=datetime.now(timezone.utc).isoformat(),
        symbol="BTCUSD",
        side="buy",
        qty=1.0,
        price=100.0,
        notional=100.0,
        order_type="limit",
        bot_name="market_maker",
        status="filled"
    ))
    store.record(TradeRecord(
        trade_id="T-2",
        timestamp=datetime.now(timezone.utc).isoformat(),
        symbol="BTCUSD",
        side="sell",
        qty=1.0,
        price=105.0,
        notional=105.0,
        order_type="market",
        bot_name="directional",
        status="filled",
        realized_pnl=5.0
    ))
    store.record(TradeRecord(
        trade_id="T-3",
        timestamp=datetime.now(timezone.utc).isoformat(),
        symbol="ETHUSD",
        side="buy",
        qty=2.0,
        price=2000.0,
        notional=4000.0,
        order_type="limit",
        bot_name="market_maker",
        status="rejected",
        reason="risk limit exceeded"
    ))

    # All trades
    all_trades = store.get_trades()
    assert len(all_trades) == 3

    # Filter by side
    buys = store.get_trades(side="buy")
    assert len(buys) == 2

    # Filter by status
    filled = store.get_trades(status="filled")
    assert len(filled) == 2

    # Filter by bot
    mm_trades = store.get_trades(bot_name="market_maker")
    assert len(mm_trades) == 2

    # Filter by symbol
    eth_trades = store.get_trades(symbol="ETHUSD")
    assert len(eth_trades) == 1
    assert eth_trades[0].trade_id == "T-3"


def test_trade_store_metrics():
    store = TradeStore()
    # Trade 1: Win (+10.0)
    store.record(TradeRecord(
        trade_id="1", timestamp="t1", symbol="BTC", side="sell", qty=1.0, price=110.0,
        notional=110.0, order_type="market", bot_name="bot", status="filled", realized_pnl=10.0
    ))
    # Trade 2: Loss (-4.0)
    store.record(TradeRecord(
        trade_id="2", timestamp="t2", symbol="BTC", side="sell", qty=1.0, price=96.0,
        notional=96.0, order_type="market", bot_name="bot", status="filled", realized_pnl=-4.0
    ))
    # Trade 3: Open buy (pnl = 0)
    store.record(TradeRecord(
        trade_id="3", timestamp="t3", symbol="BTC", side="buy", qty=1.0, price=100.0,
        notional=100.0, order_type="limit", bot_name="bot", status="new", realized_pnl=0.0
    ))

    metrics = store.get_metrics(initial_balance=1000.0, current_balance=1006.0)
    assert metrics.total_trades == 3
    assert metrics.filled_trades == 2
    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 1
    assert metrics.win_rate_pct == 50.0
    assert metrics.total_realized_pnl == 6.0
    assert metrics.profit_factor == 2.5  # 10.0 / 4.0


def test_trade_store_csv_export():
    store = TradeStore()
    store.record(TradeRecord(
        trade_id="TX1", timestamp="2026-10-28T10:00:00Z", symbol="BTCUSD",
        side="buy", qty=0.1, price=65000.0, notional=6500.0, order_type="limit",
        bot_name="market_maker", status="filled", reason="fill", realized_pnl=0.0
    ))
    csv_data = store.export_csv()
    assert "Trade ID,Timestamp,Symbol,Side,Type,Qty,Price,Notional,Bot,Status,Realized PnL,Reason" in csv_data
    assert "TX1,2026-10-28T10:00:00Z,BTCUSD,buy,limit,0.1,65000.0,6500.0,market_maker,filled,0.0,fill" in csv_data


def test_trade_store_reload_from_jsonl():
    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".jsonl") as f:
        path = f.name
        f.write(json.dumps({
            "type": "order",
            "timestamp": "2026-10-28T12:00:00Z",
            "order_id": "P-1",
            "symbol": "BTCUSD",
            "side": "buy",
            "qty": 1.0,
            "price": 100.0,
            "notional": 100.0,
            "order_type": "limit",
            "bot_name": "market_maker",
            "status": "filled",
            "reason": "quote",
            "realized_pnl": 0.0
        }) + "\n")
        f.write(json.dumps({
            "type": "order",
            "timestamp": "2026-10-28T12:05:00Z",
            "order_id": "P-2",
            "symbol": "BTCUSD",
            "side": "sell",
            "qty": 1.0,
            "price": 105.0,
            "notional": 105.0,
            "order_type": "market",
            "bot_name": "house",
            "status": "filled",
            "reason": "delta hedge",
            "realized_pnl": 5.0
        }) + "\n")

    store = TradeStore()
    store.load_from_jsonl(path)
    os.remove(path)

    trades = store.get_trades()
    assert len(trades) == 2
    assert trades[0].trade_id == "P-2"
    assert trades[1].trade_id == "P-1"
    assert trades[0].realized_pnl == 5.0


def test_paper_broker_fill_tracking_and_pnl():
    broker = PaperBroker(initial_balance=10000.0)
    broker.set_market("BTC", 100.0)
    
    # Buy 2 units at 100.0
    o1 = Order(symbol="BTC", side="buy", qty=2.0, price=100.0, order_type="market")
    broker.place(o1)
    assert len(broker.fills) == 1
    assert broker.fills[0]["realized_pnl"] == 0.0
    
    # Sell 1 unit at 110.0 (realized pnl should be +10.0)
    broker.set_market("BTC", 110.0)
    o2 = Order(symbol="BTC", side="sell", qty=1.0, price=110.0, order_type="market")
    broker.place(o2)
    assert len(broker.fills) == 2
    assert broker.fills[1]["realized_pnl"] == 10.0
    assert broker.positions()["BTC"] == 1.0
