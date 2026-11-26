import pytest

from crokbot.config import Config
from crokbot.desk.bots import DirectionalBot, HouseBot, MarketMakerBot
from crokbot.desk.orchestrator import Desk
from crokbot.execution.broker import Order
from crokbot.execution.paper import PaperBroker
from crokbot.math.indicators import (
    compute_pair_ratio,
    compute_pair_signal,
    compute_state,
)
from crokbot.policy.compose import JevAnswers, directional_policy, market_maker_policy
from crokbot.risk.engine import RiskEngine
from crokbot.state import BookLevel, ComputedState, OrderBook


class FakeJev:
    def __init__(self, answer: str):
        self.answer = answer

    def ask(self, prompt: str, max_tokens: int = 0, temperature: float = 0.0, timeout: int = 30) -> str:
        return self.answer


def _eth_state(regime: str = "neutral", change_bps: float = 0.0) -> ComputedState:
    return ComputedState(
        symbol="ETHUSDT",
        mid_price=3250.0,
        spread=1.0,
        spread_bps=3.08,
        order_imbalance=0.0,
        near_imbalance=0.0,
        realized_vol=0.002,
        price_change_bps=change_bps,
        reference_price=3250.0,
        bid_depth=10.0,
        ask_depth=10.0,
        bid_price=3249.5,
        ask_price=3250.5,
        extra={
            "eth_btc_ratio": 0.05,
            "eth_btc_change_bps": change_bps,
            "eth_btc_regime": regime,
        },
    )


def test_compute_pair_ratio_and_signal():
    assert compute_pair_ratio(3250.0, 65000.0) == pytest.approx(0.05)
    assert compute_pair_ratio(3250.0, 0.0) == 0.0

    # ETH drops from 3250 to 3230 while BTC holds 65000 (-61.5 bps on ETH/BTC)
    sig_falling = compute_pair_signal(
        eth_prices=[3250.0, 3240.0, 3230.0],
        btc_prices=[65000.0, 65000.0, 65000.0],
        drop_threshold_bps=-15.0,
    )
    assert sig_falling["eth_btc_regime"] == "falling_sharply"
    assert sig_falling["eth_btc_change_bps"] < -15.0

    # ETH rises from 3250 to 3270 while BTC holds 65000 (+61.5 bps on ETH/BTC)
    sig_rising = compute_pair_signal(
        eth_prices=[3250.0, 3260.0, 3270.0],
        btc_prices=[65000.0, 65000.0, 65000.0],
        rise_threshold_bps=15.0,
    )
    assert sig_rising["eth_btc_regime"] == "rising_sharply"
    assert sig_rising["eth_btc_change_bps"] > 15.0

    # Flat ratio
    sig_neutral = compute_pair_signal(
        eth_prices=[3250.0, 3250.0],
        btc_prices=[65000.0, 65000.0],
    )
    assert sig_neutral["eth_btc_regime"] == "neutral"


def test_eth_long_blocked_when_eth_btc_falling_sharply():
    cfg = Config()
    ans = JevAnswers(raw=["trending_up", "yes", "long", "high"], confidence=0.9)

    eth_falling = _eth_state(regime="falling_sharply", change_bps=-35.0)
    intents = directional_policy(ans, eth_falling, cfg)
    assert len(intents) == 1
    assert intents[0].action == "noop"
    assert "eth/btc" in intents[0].reason.lower()

    # BTC long is unaffected by ETH/BTC falling
    btc_state = _eth_state(regime="falling_sharply", change_bps=-35.0)
    btc_state.symbol = "BTCUSDT"
    btc_intents = directional_policy(ans, btc_state, cfg)
    assert any(i.side == "buy" and i.action == "buy" for i in btc_intents)


def test_eth_long_allowed_when_eth_btc_neutral_or_rising():
    cfg = Config()
    ans = JevAnswers(raw=["trending_up", "yes", "long", "high"], confidence=0.9)

    eth_ok = _eth_state(regime="neutral", change_bps=2.0)
    intents = directional_policy(ans, eth_ok, cfg)
    assert any(i.side == "buy" and i.action == "buy" for i in intents)


def test_eth_mm_skews_defensively_when_eth_btc_falling_sharply():
    cfg = Config(mm_quote_size=1.0, eth_quote_size=1.0)
    ans = JevAnswers(raw=["normal", "balanced", "low", "quote", "neutral"], confidence=0.9)

    eth_falling = _eth_state(regime="falling_sharply", change_bps=-30.0)
    intents = market_maker_policy(ans, eth_falling, cfg)
    buy_intent = next(i for i in intents if i.side == "buy")
    sell_intent = next(i for i in intents if i.side == "sell")
    # Defensive skew reduces ETH bid size relative to ask size when ETH/BTC is falling sharply
    assert buy_intent.qty < sell_intent.qty


def test_paper_broker_multi_symbol_prices_and_risk_equity():
    broker = PaperBroker(initial_balance=10_000.0)
    broker.set_market("BTCUSDT", 65_000.0)
    broker.set_market("ETHUSDT", 3_250.0)

    # Buy 0.05 BTC ($3,250) and 1.0 ETH ($3,250)
    o_btc = broker.place(Order(symbol="BTCUSDT", side="buy", qty=0.05, price=0.0, order_type="market"))
    o_eth = broker.place(Order(symbol="ETHUSDT", side="buy", qty=1.0, price=0.0, order_type="market"))

    assert o_btc.status == "filled"
    assert o_eth.status == "filled"
    assert broker.balance() == pytest.approx(10_000.0 - 3_250.0 - 3_250.0)

    cfg = Config(initial_balance=10_000.0, max_daily_loss_pct=5.0)
    eng = RiskEngine(cfg, broker)
    eng.update_day_start(10_000.0)
    # Total equity is still 10,000 (cash 3,500 + BTC 3,250 + ETH 3,250), so daily loss is 0%
    assert eng.daily_loss_pct == pytest.approx(0.0)


def test_desk_tick_pair_filters_eth_long_on_sharp_eth_btc_drop():
    broker = PaperBroker(initial_balance=100_000.0)
    broker.set_market("BTCUSDT", 65_000.0)
    broker.set_market("ETHUSDT", 3_200.0)

    cfg = Config(mm_quote_size=0.01, eth_quote_size=0.1)
    bots = [
        MarketMakerBot(cfg, client=FakeJev("1. normal\n2. balanced\n3. low\n4. quote\n5. neutral\n6. 0.9\n")),
        HouseBot(cfg, client=FakeJev("1. at_target\n2. no\n3. market\n4. no\n5. 0.9\n")),
        DirectionalBot(cfg, client=FakeJev("1. trending_up\n2. yes\n3. long\n4. high\n5. 0.9\n")),
    ]
    desk = Desk(cfg, broker, bots=bots)

    btc_book = OrderBook(
        symbol="BTCUSDT",
        bids=[BookLevel(64_990.0, 1.0)],
        asks=[BookLevel(65_010.0, 1.0)],
    )
    eth_book = OrderBook(
        symbol="ETHUSDT",
        bids=[BookLevel(3_199.0, 5.0)],
        asks=[BookLevel(3_201.0, 5.0)],
    )

    # Reference BTC was 65,000 (0 bps change), Reference ETH was 3,250 (-153.8 bps drop!)
    btc_state = compute_state(btc_book, [65_000.0, 65_000.0], reference_price=65_000.0)
    eth_state = compute_state(eth_book, [3_250.0, 3_200.0], reference_price=3_250.0)

    orders = desk.tick_pair(btc_state, eth_state)
    desk.close()

    # BTC directional market buy should be placed and filled
    btc_market_buys = [o for o in orders if o.symbol == "BTCUSDT" and o.order_type == "market" and o.side == "buy"]
    assert len(btc_market_buys) == 1
    assert btc_market_buys[0].status == "filled"

    # ETH directional market buy should be blocked by the ETH/BTC falling filter
    eth_market_buys = [o for o in orders if o.symbol == "ETHUSDT" and o.order_type == "market" and o.side == "buy"]
    assert len(eth_market_buys) == 0
    assert eth_state.extra.get("eth_btc_regime") == "falling_sharply"


def test_dashboard_tracks_both_markets_and_pair_filter():
    from fastapi.testclient import TestClient
    from crokbot.dashboard.server import create_app
    from crokbot.dashboard.store import TradeStore

    broker = PaperBroker(initial_balance=10_000.0)
    broker.set_market("BTCUSDT", 65_000.0)
    broker.set_market("ETHUSDT", 3_200.0)
    cfg = Config(initial_balance=10_000.0, mm_quote_size=0.01, eth_quote_size=0.1)
    bots = [
        MarketMakerBot(cfg, client=FakeJev("1. normal\n2. balanced\n3. low\n4. quote\n5. neutral\n6. 0.9\n")),
        HouseBot(cfg, client=FakeJev("1. at_target\n2. no\n3. market\n4. no\n5. 0.9\n")),
        DirectionalBot(cfg, client=FakeJev("1. trending_up\n2. yes\n3. long\n4. high\n5. 0.9\n")),
    ]
    store = TradeStore()
    desk = Desk(cfg, broker, bots=bots, trade_store=store)
    app = create_app(desk=desk, trade_store=store)
    client = TestClient(app)

    btc_book = OrderBook(symbol="BTCUSDT", bids=[BookLevel(64_990.0, 1.0)], asks=[BookLevel(65_010.0, 1.0)])
    eth_book = OrderBook(symbol="ETHUSDT", bids=[BookLevel(3_199.0, 5.0)], asks=[BookLevel(3_201.0, 5.0)])
    btc_state = compute_state(btc_book, [65_000.0, 65_000.0], reference_price=65_000.0)
    eth_state = compute_state(eth_book, [3_250.0, 3_200.0], reference_price=3_250.0)

    desk.tick_pair(btc_state, eth_state)
    desk.close()

    res_mkt = client.get("/api/market").json()
    assert "BTCUSDT" in res_mkt.get("markets", {})
    assert "ETHUSDT" in res_mkt.get("markets", {})
    assert res_mkt.get("pair_filter", {}).get("eth_btc_regime") == "falling_sharply"

    res_sum = client.get("/api/summary").json()
    assert res_sum["pair_filter"]["eth_btc_regime"] == "falling_sharply"
    # Equity should remain ~10,000 despite BTC purchase
    assert res_sum["metrics"]["current_balance"] == pytest.approx(10_000.0, abs=5.0)

