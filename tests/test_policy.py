from crokbot.config import Config
from crokbot.policy.compose import (
    JevAnswers,
    directional_policy,
    house_policy,
    market_maker_policy,
)
from crokbot.state import ComputedState


def _state() -> ComputedState:
    return ComputedState(
        symbol="BTCUSD", mid_price=100.02, spread=0.04, spread_bps=4.0,
        order_imbalance=0.0, near_imbalance=0.0, realized_vol=0.001,
        price_change_bps=0.0, reference_price=100.0, bid_depth=3.0, ask_depth=3.0,
        bid_price=100.0, ask_price=100.04,
    )


def test_market_maker_quotes_when_confident():
    cfg = Config(jev_confidence_floor=0.6)
    ans = JevAnswers(raw=["normal", "balanced", "low", "quote", "neutral"], confidence=0.9)
    intents = market_maker_policy(ans, _state(), cfg)
    sides = {i.side for i in intents}
    assert sides == {"buy", "sell"}
    buy = next(i for i in intents if i.side == "buy")
    sell = next(i for i in intents if i.side == "sell")
    assert buy.price == 100.0 + cfg.mm_tick_size   # one tick inside touch
    assert sell.price == 100.04 - cfg.mm_tick_size
    assert buy.post_only and sell.post_only


def test_market_maker_pulls_on_low_confidence():
    cfg = Config(jev_confidence_floor=0.6)
    ans = JevAnswers(raw=["normal", "balanced", "low", "quote", "neutral"], confidence=0.3)
    intents = market_maker_policy(ans, _state(), cfg)
    assert all(i.action in ("cancel", "noop") for i in intents)


def test_market_maker_pulls_when_jev_says_pull():
    cfg = Config()
    ans = JevAnswers(raw=["normal", "balanced", "low", "pull", "neutral"], confidence=0.9)
    intents = market_maker_policy(ans, _state(), cfg)
    assert all(i.action == "cancel" for i in intents)


def test_market_maker_skips_thin_spread():
    cfg = Config(mm_min_spread_bps=5.0)
    s = _state()  # spread_bps = 2.0 < 5.0
    ans = JevAnswers(raw=["normal", "balanced", "low", "quote", "neutral"], confidence=0.9)
    intents = market_maker_policy(ans, s, cfg)
    assert not any(i.action == "quote" for i in intents)


def test_house_rebalances_long():
    cfg = Config()
    ans = JevAnswers(raw=["long", "yes", "market", "yes"], confidence=0.9)
    intents = house_policy(ans, _state(), net_qty=5.0, target_qty=0.0, cfg=cfg)
    rebal = [i for i in intents if i.action == "rebalance"]
    assert rebal and rebal[0].side == "sell" and rebal[0].qty == 5.0


def test_house_holds_at_target():
    cfg = Config()
    ans = JevAnswers(raw=["at_target", "no", "market", "no"], confidence=0.9)
    intents = house_policy(ans, _state(), net_qty=0.0, target_qty=0.0, cfg=cfg)
    assert not any(i.action == "rebalance" for i in intents)


def test_directional_goes_long_on_confident_edge():
    cfg = Config()
    ans = JevAnswers(raw=["trending_up", "yes", "long", "high"], confidence=0.9)
    intents = directional_policy(ans, _state(), cfg)
    assert any(i.side == "buy" and i.action in ("buy",) for i in intents)


def test_directional_flat_without_edge():
    cfg = Config()
    ans = JevAnswers(raw=["ranging", "no", "flat", "low"], confidence=0.9)
    intents = directional_policy(ans, _state(), cfg)
    assert all(i.side is None for i in intents)