import pytest
from fastapi.testclient import TestClient

from crokbot.config import Config
from crokbot.dashboard.server import create_app
from crokbot.dashboard.store import TradeStore
from crokbot.desk.bots import DirectionalBot, HouseBot, MarketMakerBot
from crokbot.desk.orchestrator import Desk
from crokbot.execution.broker import Order
from crokbot.execution.etoro import EToroBroker
from crokbot.execution.paper import PaperBroker
from crokbot.jev.client import _heuristic_answer
from crokbot.jev.parser import extract_lines
from crokbot.jev.questions import directional_prompt, house_prompt, market_maker_prompt
from crokbot.math.indicators import compute_state
from crokbot.policy.compose import JevAnswers, house_policy
from crokbot.risk.engine import RiskEngine
from crokbot.state import BookLevel, ComputedState, OrderBook


class FakeJev:
    def __init__(self, answer: str):
        self.answer = answer

    def ask(self, prompt: str, max_tokens: int = 0, temperature: float = 0.0, timeout: int = 30) -> str:
        return self.answer


def _sample_state(
    symbol: str = "BTCUSDT",
    mid: float = 65_000.0,
    spread_bps_val: float = 4.6,
    imbalance: float = 0.0,
    vol: float = 0.005,
    change_bps: float = 0.0,
) -> ComputedState:
    half = mid * (spread_bps_val / 20_000.0)
    return ComputedState(
        symbol=symbol,
        mid_price=mid,
        spread=half * 2,
        spread_bps=spread_bps_val,
        order_imbalance=imbalance,
        near_imbalance=imbalance,
        realized_vol=vol,
        price_change_bps=change_bps,
        reference_price=mid / (1.0 + change_bps / 10_000.0) if change_bps else mid,
        bid_depth=5.0,
        ask_depth=5.0,
        bid_price=round(mid - half, 4),
        ask_price=round(mid + half, 4),
    )


def test_market_order_notional_enforced_by_risk_engine():
    broker = PaperBroker(initial_balance=10_000.0)
    broker.set_market("BTCUSDT", 65_000.0)
    cfg = Config(max_order_notional=300.0, max_position_notional=1_000.0)
    eng = RiskEngine(cfg, broker)

    # Market order has price=0.0, but 0.01 BTC @ $65,000 = $650 > $300 max_order_notional
    mkt_buy = Order(symbol="BTCUSDT", side="buy", qty=0.01, price=0.0, order_type="market")
    decision = eng.check(mkt_buy, reference_price=65_000.0)
    assert decision.ok is False
    assert "order notional" in decision.reason


def test_risk_engine_enforces_total_portfolio_exposure_and_allows_reducing_close():
    broker = PaperBroker(initial_balance=300.0)
    broker.set_market("BTCUSDT", 65_000.0)
    broker.set_market("ETHUSDT", 3_250.0)
    # Already holding 0.003 BTC ($195 exposure) out of $300 total desk cap
    broker._pos["BTCUSDT"] = 0.003

    cfg = Config(initial_balance=300.0, max_order_notional=300.0, max_position_notional=300.0)
    eng = RiskEngine(cfg, broker)

    # Trying to buy 0.05 ETH ($162.50) pushes total portfolio exposure to $357.50 > $300 cap
    eth_buy = Order(symbol="ETHUSDT", side="buy", qty=0.05, price=3_250.0, order_type="limit")
    d_increase = eng.check(eth_buy, reference_price=3_250.0, position=0.0)
    assert d_increase.ok is False
    assert "exposure" in d_increase.reason

    # Even if BTC position is over cap (0.005 BTC = $325 > $300), selling 0.003 BTC reduces risk and MUST be allowed
    broker._pos["BTCUSDT"] = 0.005
    btc_reduce = Order(symbol="BTCUSDT", side="sell", qty=0.003, price=0.0, order_type="market")
    d_reduce = eng.check(btc_reduce, reference_price=65_000.0, position=0.005)
    assert d_reduce.ok is True


def test_heuristic_jev_is_state_driven_not_blindly_long():
    # 1. Bearish momentum + ask pressure -> trending_down & short
    bear_state = _sample_state(change_bps=-35.0, imbalance=-0.35)
    bear_ans = extract_lines(_heuristic_answer(directional_prompt(bear_state)))
    assert bear_ans[0] == "trending_down"
    assert bear_ans[1] == "yes"
    assert bear_ans[2] == "short"

    # 2. Choppy / flat noise -> ranging & no clean edge (avoids overtrading)
    flat_state = _sample_state(change_bps=1.5, imbalance=0.02)
    flat_ans = extract_lines(_heuristic_answer(directional_prompt(flat_state)))
    assert flat_ans[0] == "ranging"
    assert flat_ans[1] == "no"
    assert flat_ans[2] == "flat"

    # 3. High realized vol -> market maker pulls quotes
    vol_state = _sample_state(vol=0.035)
    mm_ans = extract_lines(_heuristic_answer(market_maker_prompt(vol_state)))
    assert mm_ans[2] == "high"
    assert mm_ans[3] == "pull"

    # 4. Non-zero inventory -> house bot flags imbalance & rebalances
    inv_state = _sample_state(symbol="BTCUSDT")
    house_ans = extract_lines(_heuristic_answer(house_prompt(inv_state, net_qty=0.01, target_qty=0.0)))
    assert house_ans[0] == "long"
    assert house_ans[1] == "yes"


def test_parser_ignores_preamble_and_bot_rejects_truncated_battery():
    cfg = Config()
    raw_with_preamble = (
        "Sure, reading the state below:\n"
        "1. trending_up\n"
        "2. yes\n"
        "3. long\n"
        "4. high\n"
        "5. 0.88\n"
    )
    bot = DirectionalBot(cfg, client=FakeJev(raw_with_preamble))
    intents = bot.step(_sample_state(change_bps=25.0))
    assert any(i.side == "buy" and i.action == "buy" for i in intents)

    # Truncated battery (only 2 lines instead of 5) -> safely noop, never misread line 2 as confidence
    truncated_bot = DirectionalBot(cfg, client=FakeJev("1. trending_up\n2. 0.95\n"))
    trunc_intents = truncated_bot.step(_sample_state(change_bps=25.0))
    assert len(trunc_intents) == 1 and trunc_intents[0].action == "noop"


def test_house_policy_scales_tolerance_for_fractional_crypto():
    cfg = Config(mm_quote_size=0.001)
    ans = JevAnswers(raw=["long", "yes", "market", "no"], confidence=0.9)
    s = _sample_state(symbol="BTCUSDT", mid=65_000.0)
    # 0.005 BTC ($325) is 5x quote size -> must rebalance, not treat < 1.0 BTC as at_target
    intents = house_policy(ans, s, net_qty=0.005, target_qty=0.0, cfg=cfg)
    assert any(i.action == "rebalance" and i.side == "sell" for i in intents)


def test_desk_replaces_stale_quotes_and_updates_store_on_sweep_fills():
    cfg = Config(mm_quote_size=0.001, max_open_orders=6)
    broker = PaperBroker(initial_balance=10_000.0)
    store = TradeStore()
    bots = [
        MarketMakerBot(cfg, client=FakeJev("1. normal\n2. balanced\n3. low\n4. quote\n5. neutral\n6. 0.9\n")),
    ]
    desk = Desk(cfg=cfg, broker=broker, bots=bots, trade_store=store)

    # Run 5 ticks without sweeps -> open orders should stay bounded (2 active quotes), NOT pile up to 10!
    for i in range(5):
        mid = 65_000.0 + i * 2.0
        broker.set_market("BTCUSDT", mid)
        book = OrderBook(
            symbol="BTCUSDT",
            bids=[BookLevel(mid - 15.0, 1.0)],
            asks=[BookLevel(mid + 15.0, 1.0)],
        )
        st = compute_state(book, [65_000.0, mid], reference_price=65_000.0)
        desk.tick(st)

    assert len(broker.open_orders()) == 2

    # Now sweep the bid and then sweep the ask -> store should reflect filled trades and realized PnL
    latest_bid_quote = min(o.price for o in broker.open_orders() if o.is_buy)
    latest_ask_quote = max(o.price for o in broker.open_orders() if not o.is_buy)
    assert broker.sweep("BTCUSDT", latest_bid_quote - 1.0) == 1
    assert broker.sweep("BTCUSDT", latest_ask_quote + 1.0) == 1

    desk.close()
    metrics = store.get_metrics(initial_balance=10_000.0, current_balance=broker.balance())
    assert metrics.filled_trades >= 2
    assert metrics.total_realized_pnl > 0.0


def test_etoro_symbol_resolution_and_health_endpoint():
    etoro = EToroBroker(api_key="", user_key="")
    assert etoro.resolve_instrument_id("BTCUSDT") == "100000"
    assert etoro.resolve_instrument_id("ETHUSDT") == "100001"
    assert etoro.resolve_instrument_id("100000") == "100000"

    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
