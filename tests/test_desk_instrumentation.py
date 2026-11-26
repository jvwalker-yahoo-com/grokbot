import pytest
from datetime import datetime
from crokbot.config import Config
from crokbot.dashboard.store import TradeStore
from crokbot.desk.bots import MarketMakerBot, HouseBot, DirectionalBot
from crokbot.desk.orchestrator import Desk
from crokbot.execution.paper import PaperBroker
from crokbot.math.indicators import compute_state
from crokbot.state import BookLevel, OrderBook


class FakeJev:
    def __init__(self, answer):
        self.answer = answer

    def ask(self, prompt, max_tokens=0, temperature=0.0, timeout=30):
        return self.answer


BATTERY = {
    "market_maker": "1. normal\n2. balanced\n3. low\n4. quote\n5. neutral\n6. 0.9\n",
    "house": "1. at_target\n2. no\n3. market\n4. yes\n5. 0.9\n",
    "directional": "1. trending_up\n2. yes\n3. long\n4. high\n5. 0.9\n",
}


def test_desk_records_to_trade_store():
    store = TradeStore()
    cfg = Config()
    broker = PaperBroker(initial_balance=100_000.0)
    broker.set_market("BTCUSD", 100.0)

    bots = [
        MarketMakerBot(cfg, client=FakeJev(BATTERY["market_maker"])),
        HouseBot(cfg, client=FakeJev(BATTERY["house"])),
        DirectionalBot(cfg, client=FakeJev(BATTERY["directional"])),
    ]
    desk = Desk(cfg, broker, bots=bots, trade_store=store)

    book = OrderBook(
        symbol="BTCUSD",
        bids=[BookLevel(100.0, 1.5), BookLevel(99.9, 2.0)],
        asks=[BookLevel(100.04, 1.5), BookLevel(100.1, 2.0)],
    )
    state = compute_state(book, [99.8, 99.9, 100.0], reference_price=100.0)

    orders = desk.tick(state)
    desk.close()

    trades = store.get_trades()
    assert len(trades) > 0

    # Ensure orders recorded have timestamps, bot attribution, and IDs
    for t in trades:
        assert t.timestamp is not None
        assert t.bot_name in ("market_maker", "house", "directional", "desk")
        assert t.trade_id != ""


def test_desk_broadcasts_market_and_decisions():
    events_captured = []
    def on_event(ev):
        events_captured.append(ev)

    store = TradeStore()
    cfg = Config()
    broker = PaperBroker(initial_balance=100_000.0)
    bots = [
        MarketMakerBot(cfg, client=FakeJev(BATTERY["market_maker"])),
    ]
    desk = Desk(cfg, broker, bots=bots, trade_store=store, event_callback=on_event)

    book = OrderBook(
        symbol="BTCUSD",
        bids=[BookLevel(100.0, 1.5)],
        asks=[BookLevel(100.04, 1.5)],
    )
    state = compute_state(book, [100.0], reference_price=100.0)
    desk.tick(state)
    desk.close()

    assert any(ev.get("type") in ("order", "tick", "market") for ev in events_captured)
