import pytest

from crokbot.config import Config
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


@pytest.fixture
def book():
    return OrderBook(
        symbol="BTCUSD",
        bids=[BookLevel(100.0, 1.5), BookLevel(99.9, 2.0)],
        asks=[BookLevel(100.04, 1.5), BookLevel(100.1, 2.0)],
    )


# market maker says "quote", house holds, directional flat
BATTERY = {
    "market_maker": "1. normal\n2. balanced\n3. low\n4. quote\n5. neutral\n6. 0.9\n",
    "house": "1. at_target\n2. no\n3. market\n4. yes\n5. 0.9\n",
    "directional": "1. trending_up\n2. yes\n3. long\n4. high\n5. 0.9\n",
}


def _desk(book, broker):
    cfg = Config()
    fake = FakeJev("")
    bots = [
        MarketMakerBot(cfg, client=FakeJev(BATTERY["market_maker"])),
        HouseBot(cfg, client=FakeJev(BATTERY["house"])),
        DirectionalBot(cfg, client=FakeJev(BATTERY["directional"])),
    ]
    desk = Desk(cfg, broker, bots=bots)
    state = compute_state(book, [99.8, 99.9, 100.0], reference_price=100.0)
    return desk, state


def test_desk_tick_places_all_three_bots(book):
    broker = PaperBroker(initial_balance=100_000.0)
    desk, state = _desk(book, broker)
    orders = desk.tick(state)
    desk.close()

    sides = [o.side for o in orders if o.status != "rejected"]
    assert "buy" in sides and "sell" in sides  # market maker quoted both sides
    # direction bot went long with a market buy
    assert any(o.side == "buy" and o.order_type == "market" for o in orders)


def test_risk_gate_blocks_in_desk(book):
    from crokbot.config import Config as Cfg

    broker = PaperBroker(initial_balance=100_000.0)
    cfg = Cfg(max_order_notional=1.0)  # tiny cap -> everything rejected
    bots = [
        MarketMakerBot(cfg, client=FakeJev(BATTERY["market_maker"])),
        HouseBot(cfg, client=FakeJev(BATTERY["house"])),
        DirectionalBot(cfg, client=FakeJev(BATTERY["directional"])),
    ]
    desk = Desk(cfg, broker, bots=bots)
    state = compute_state(book, [99.8, 99.9, 100.0], reference_price=100.0)
    orders = desk.tick(state)
    desk.close()
    assert all(o.status == "rejected" for o in orders)