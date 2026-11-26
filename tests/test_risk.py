from crokbot.config import Config
from crokbot.execution.broker import Order
from crokbot.execution.paper import PaperBroker
from crokbot.risk.engine import RiskEngine, gate_and_place


def _broker() -> PaperBroker:
    return PaperBroker(initial_balance=100_000.0)


def test_order_notional_cap():
    cfg = Config(max_order_notional=100.0)
    eng = RiskEngine(cfg, _broker())
    o = Order(symbol="X", side="buy", qty=2.0, price=100.0)  # 200 notional
    assert eng.check(o).ok is False


def test_exposure_cap():
    cfg = Config(max_position_notional=1000.0)
    eng = RiskEngine(cfg, _broker())
    o = Order(symbol="X", side="buy", qty=6.0, price=100.0)  # 600 notional
    # position already 5 units @ 100 = 500 -> projected 1100 > 1000
    assert eng.check(o, reference_price=100.0, position=5.0).ok is False


def test_price_band():
    cfg = Config(price_band_pct=1.0)
    eng = RiskEngine(cfg, _broker())
    o = Order(symbol="X", side="buy", qty=1.0, price=105.0)  # 5% off reference
    assert eng.check(o, reference_price=100.0).ok is False


def test_self_trade_prevention():
    cfg = Config(self_trade_prevention=True)
    eng = RiskEngine(cfg, _broker())
    buy = Order(symbol="X", side="buy", qty=1.0, price=100.2)
    assert eng.check(buy, best_ask=100.0).ok is False  # buy above ask
    sell = Order(symbol="X", side="sell", qty=1.0, price=99.0)
    assert eng.check(sell, best_bid=100.0).ok is False  # sell below bid


def test_daily_loss_limit():
    b = _broker()
    cfg = Config(max_daily_loss_pct=5.0)
    eng = RiskEngine(cfg, b)
    b._balance = 94_000.0  # -6% from 100k start
    o = Order(symbol="X", side="buy", qty=1.0, price=100.0)
    assert eng.check(o).ok is False


def test_daily_loss_accounts_for_position_equity():
    b = _broker()  # 100k start
    cfg = Config(max_daily_loss_pct=5.0)
    eng = RiskEngine(cfg, b)
    # Cash down by 10k (10%), but holding 100 units of asset @ 100 = 10k equity
    b._balance = 90_000.0
    b._pos["BTCUSD"] = 100.0
    b.current_price = 100.0
    o = Order(symbol="BTCUSD", side="buy", qty=0.1, price=100.0)
    # Total equity is 100k, so daily loss is 0%, order should NOT be rejected for daily loss
    decision = eng.check(o, reference_price=100.0)
    assert "daily loss limit" not in decision.reason


def test_kill_switch():
    cfg = Config()
    eng = RiskEngine(cfg, _broker())
    eng.kill()
    o = Order(symbol="X", side="buy", qty=1.0, price=100.0)
    assert eng.check(o).ok is False


def test_gate_and_place_rejects():
    b = _broker()
    cfg = Config(max_order_notional=10.0)
    eng = RiskEngine(cfg, b)
    o = Order(symbol="X", side="buy", qty=1.0, price=100.0)  # 100 > 10
    result = gate_and_place(eng, b, o)
    assert result.status == "rejected"
    assert result.reason