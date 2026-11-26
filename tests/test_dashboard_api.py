import pytest
from fastapi.testclient import TestClient

from crokbot.config import Config
from crokbot.dashboard.server import create_app
from crokbot.dashboard.store import TradeRecord, TradeStore
from crokbot.execution.paper import PaperBroker
from crokbot.desk.orchestrator import Desk


@pytest.fixture
def test_setup():
    store = TradeStore()
    cfg = Config()
    broker = PaperBroker(initial_balance=50000.0)
    broker.set_market("BTCUSD", 65000.0)
    desk = Desk(cfg=cfg, broker=broker, bots=[], trade_store=store)

    # Seed a trade
    store.record(TradeRecord(
        trade_id="T-API-1",
        timestamp="2026-10-28T10:00:00Z",
        symbol="BTCUSD",
        side="buy",
        qty=0.5,
        price=65000.0,
        notional=32500.0,
        order_type="limit",
        bot_name="market_maker",
        status="filled",
        reason="test fill",
        realized_pnl=0.0
    ))

    app = create_app(desk=desk, trade_store=store)
    client = TestClient(app)
    return client, store, desk


def test_get_trades_endpoint(test_setup):
    client, store, _ = test_setup
    resp = client.get("/api/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert "trades" in data
    assert len(data["trades"]) == 1
    assert data["trades"][0]["trade_id"] == "T-API-1"


def test_get_trades_filtering(test_setup):
    client, store, _ = test_setup
    # Filter by side
    resp_buy = client.get("/api/trades?side=buy")
    assert resp_buy.status_code == 200
    assert len(resp_buy.json()["trades"]) == 1

    resp_sell = client.get("/api/trades?side=sell")
    assert resp_sell.status_code == 200
    assert len(resp_sell.json()["trades"]) == 0


def test_export_csv_endpoint(test_setup):
    client, _, _ = test_setup
    resp = client.get("/api/trades/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "T-API-1,2026-10-28T10:00:00Z,BTCUSD,buy" in resp.text


def test_summary_endpoint(test_setup):
    client, _, _ = test_setup
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "metrics" in data
    assert "desk_status" in data
    assert data["metrics"]["total_trades"] == 1


def test_emergency_kill_endpoint(test_setup):
    client, _, desk = test_setup
    resp = client.post("/api/emergency/kill")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "killed"
    assert desk.risk.killed is True
