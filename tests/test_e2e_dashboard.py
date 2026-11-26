import pytest
from fastapi.testclient import TestClient

from crokbot.config import Config
from crokbot.dashboard.server import create_app
from crokbot.dashboard.store import TradeStore
from crokbot.desk.bots import DirectionalBot, HouseBot, MarketMakerBot
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
    "market_maker": "1. normal\n2. balanced\n3. low\n4. quote\n5. neutral\n6. 0.95\n",
    "house": "1. at_target\n2. no\n3. market\n4. yes\n5. 0.90\n",
    "directional": "1. trending_up\n2. yes\n3. long\n4. high\n5. 0.90\n",
}


def test_full_e2e_trading_and_dashboard_blotter():
    cfg = Config()
    broker = PaperBroker(initial_balance=100_000.0)
    store = TradeStore()

    bots = [
        MarketMakerBot(cfg, client=FakeJev(BATTERY["market_maker"])),
        HouseBot(cfg, client=FakeJev(BATTERY["house"])),
        DirectionalBot(cfg, client=FakeJev(BATTERY["directional"])),
    ]
    desk = Desk(cfg=cfg, broker=broker, bots=bots, trade_store=store)
    app = create_app(desk=desk, trade_store=store)
    client = TestClient(app)

    # Tick 1: Mid = 100.0
    broker.set_market("BTCUSD", 100.0)
    book1 = OrderBook(
        symbol="BTCUSD",
        bids=[BookLevel(100.0, 2.0)],
        asks=[BookLevel(100.04, 2.0)],
    )
    s1 = compute_state(book1, [99.8, 99.9, 100.0], reference_price=100.0)
    orders1 = desk.tick(s1)
    broker.sweep("BTCUSD", 100.0)

    # Check blotter has trades recorded
    resp = client.get("/api/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["trades"]) >= len(orders1)
    assert data["total"] >= len(orders1)

    # Verify summary
    summary_resp = client.get("/api/summary")
    assert summary_resp.status_code == 200
    sum_data = summary_resp.json()
    assert sum_data["desk_status"] == "running"
    assert sum_data["metrics"]["total_trades"] >= len(orders1)

    # Verify CSV export
    csv_resp = client.get("/api/trades/export")
    assert csv_resp.status_code == 200
    assert "BTCUSD" in csv_resp.text

    # Test emergency kill via dashboard API
    kill_resp = client.post("/api/emergency/kill")
    assert kill_resp.status_code == 200
    assert desk.risk.killed is True

    # Next tick should reject orders
    orders_after_kill = desk.tick(s1)
    assert all(o.status == "rejected" for o in orders_after_kill)

    desk.close()
