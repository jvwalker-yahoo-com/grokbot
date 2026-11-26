from crokbot.execution.broker import Order
from crokbot.execution.paper import PaperBroker


def test_market_buy_fills():
    b = PaperBroker(initial_balance=100_000.0)
    b.set_market("X", 100.0)
    o = b.place(Order(symbol="X", side="buy", qty=2.0, price=0.0, order_type="market"))
    assert o.status == "filled"
    assert b.positions()["X"] == 2.0
    assert b.balance() == 100_000.0 - 200.0


def test_market_sell_adds_cash():
    b = PaperBroker(initial_balance=100_000.0)
    b._pos["X"] = 2.0
    b._avg["X"] = 100.0
    b.set_market("X", 100.0)
    o = b.place(Order(symbol="X", side="sell", qty=2.0, price=0.0, order_type="market"))
    assert o.status == "filled"
    assert b.positions().get("X", 0.0) == 0.0
    assert b.balance() == 100_000.0 + 200.0


def test_limit_rests_then_sweeps():
    b = PaperBroker(initial_balance=100_000.0)
    b.set_market("X", 101.0)
    o = b.place(Order(symbol="X", side="buy", qty=1.0, price=100.0, order_type="limit"))
    assert o.status == "new"  # resting, market above limit
    assert b.sweep("X", 100.0) == 1  # market drops to 100, crosses limit
    assert b.positions().get("X") == 1.0


def test_cancel():
    b = PaperBroker(initial_balance=100_000.0)
    o = b.place(Order(symbol="X", side="buy", qty=1.0, price=99.0))
    assert b.cancel(o.order_id) is True
    assert b.open_orders() == []