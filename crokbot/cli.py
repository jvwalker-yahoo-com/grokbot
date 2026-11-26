"""Command-line entrypoint.

  python -m crokbot demo       # one desk tick against a synthetic book (offline)
  python -m crokbot demo --live-jev   # same, but call the real Jev via Omniroute
  python -m crokbot jev-ping   # test the Jev connection
"""
from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .config import config


def _demo_book():
    from .state import BookLevel, OrderBook

    return OrderBook(
        symbol="BTCUSD",
        bids=[
            BookLevel(100.00, 1.0),
            BookLevel(99.99, 2.0),
            BookLevel(99.98, 3.0),
            BookLevel(99.95, 5.0),
        ],
        asks=[
            BookLevel(100.04, 1.0),
            BookLevel(100.05, 2.0),
            BookLevel(100.07, 3.0),
            BookLevel(100.10, 5.0),
        ],
    )


class FakeJev:
    """Scripted Jev for offline demos/tests — returns a fixed battery."""

    def __init__(self, answer: str):
        self.answer = answer

    def ask(self, prompt: str, max_tokens: int = 0, temperature: float = 0.0,
            timeout: int = 30) -> str:
        return self.answer


MARKETMAKER_YES = (
    "1. normal\n2. balanced\n3. low\n4. quote\n5. neutral\n6. 0.9\n"
)
HOUSE_HOLD = (
    "1. at_target\n2. no\n3. market\n4. yes\n5. 0.9\n"
)
DIRECTIONAL_LONG = (
    "1. trending_up\n2. yes\n3. long\n4. high\n5. 0.9\n"
)


def build_desk(broker, use_fake_jev: bool, trade_store=None):
    from .desk.bots import DirectionalBot, HouseBot, MarketMakerBot
    from .desk.orchestrator import Desk

    bots: list = []
    if use_fake_jev:
        bots = [
            MarketMakerBot(config, client=FakeJev(MARKETMAKER_YES)),
            HouseBot(config, client=FakeJev(HOUSE_HOLD)),
            DirectionalBot(config, client=FakeJev(DIRECTIONAL_LONG)),
        ]
    return Desk(config, broker, bots=bots if use_fake_jev else None, trade_store=trade_store)


def cmd_demo(args):
    from .execution.paper import PaperBroker
    from .math.indicators import compute_state

    broker = PaperBroker(config.initial_balance)
    book = _demo_book()
    prices = [99.80, 99.85, 99.90, 99.95, 100.00, 100.00, 99.98, 100.01]
    state = compute_state(book, prices, reference_price=100.0)
    broker.set_market(state.symbol, state.mid_price)  # mark before tick so market orders fill

    desk = build_desk(broker, use_fake_jev=not args.live_jev)
    print(f"[desk] trust stage={config.trust_stage} broker={config.broker} mode={config.execution_mode}")
    print(f"[state] mid={state.mid_price} spread={state.spread_bps}bps "
          f"imbalance={state.order_imbalance} vol={state.realized_vol}")
    print(f"[jev ] {'live (Omniroute)' if args.live_jev else 'fake (offline)'} "
          f"model={config.jev_model}")

    orders = desk.tick(state)
    broker.set_market(state.symbol, 100.0)
    broker.sweep(state.symbol, 100.0)

    print(f"[desk] emitted {len(orders)} order(s):")
    for o in orders:
        print(f"   {o.side:4s} qty={o.qty} @ {o.price} post_only={o.post_only} "
              f"-> {o.status} {o.reason or ''}")
    print(f"[pos ] {broker.positions()}")
    print(f"[cash] {broker.balance():.2f}")
    print(f"[fills] {len(broker.fills)}")
    desk.close()
    return 0


def cmd_jev_ping(args):
    from .jev.client import get_client

    if not config.omniroute_api_key:
        print("[jev] OMNIROUTE_API_KEY not set — set it (or copy .env) to enable Jev.")
        return 1
    client = get_client()
    raw = client.ask("Answer exactly one line: what is 2 + 2?")
    print(f"[jev] enabled={client.enabled()} model={client.model} base={client.base_url}")
    if raw:
        print(f"[jev] response: {raw.strip()[:200]}")
        return 0
    print("[jev] no response (Omniroute down, key rejected, or 401).")
    return 1


def cmd_etoro_ping(args):
    from .execution.etoro import EToroBroker
    from .execution.broker import Order
    import time

    if not config.etoro_username and not args.api_key:
        print("[etoro] Please provide credentials via .env (ETORO_APP_KEY) or --api-key and --user-key.")
        return 1
        
    # Use args or fall back to env variables
    api_key = args.api_key or config.etoro_app_key
    user_key = args.user_key or config.etoro_username
    
    print(f"Testing eToro connection with API key: {api_key[:10]}...")
    broker = EToroBroker(api_key=api_key, user_key=user_key)
    
    print("Testing balance endpoint...")
    balance = broker.balance()
    print(f"[etoro] Balance: {balance}")
    
    print("Testing positions endpoint...")
    positions = broker.positions()
    print(f"[etoro] Positions: {positions}")
    
    print("Testing open orders endpoint...")
    orders = broker.open_orders()
    print(f"[etoro] Open Orders: {len(orders)}")

    if args.place_trade:
        # BTC Instrument ID = 100000
        print("Placing test market order (Buy 10 EUR of BTC)...")
        order = Order(symbol="100000", side="buy", notional=10.0, price=0.0, order_type="market")
        placed_order = broker.place(order)
        print(f"[etoro] Placed order: {placed_order.status}, Reason: {placed_order.reason}")
    
    return 0


def cmd_dashboard(args):
    import threading
    import time
    import uvicorn
    from .dashboard.server import create_app
    from .dashboard.store import TradeStore
    from .execution.paper import PaperBroker
    from .math.indicators import compute_state
    from .state import BookLevel, OrderBook

    store = TradeStore()
    store.load_from_jsonl(config.events_path)

    broker = PaperBroker(config.initial_balance)
    desk = build_desk(broker, use_fake_jev=not args.live_jev, trade_store=store)

    app = create_app(desk=desk, trade_store=store)

    # Start live trading loop in background thread
    def run_loop():
        tick_count = 0
        btc_ref = 65000.0
        eth_ref = 3250.0
        btc_spread_half = 15.0
        eth_spread_half = 0.80
        while not desk.risk.killed:
            time.sleep(args.interval)
            tick_count += 1
            btc_mid = 65000.0 + (tick_count % 15) * 5.0
            eth_mid = 3250.0 - 12.0 if (tick_count % 5 in (3, 4)) else (3250.0 + (tick_count % 8) * 0.5)
            broker.set_market("BTCUSDT", btc_mid)
            broker.set_market("ETHUSDT", eth_mid)
            btc_book = OrderBook(
                symbol="BTCUSDT",
                bids=[BookLevel(btc_mid - btc_spread_half, 2.0), BookLevel(btc_mid - btc_spread_half - 5.0, 5.0)],
                asks=[BookLevel(btc_mid + btc_spread_half, 2.0), BookLevel(btc_mid + btc_spread_half + 5.0, 5.0)],
            )
            eth_book = OrderBook(
                symbol="ETHUSDT",
                bids=[BookLevel(eth_mid - eth_spread_half, 5.0), BookLevel(eth_mid - eth_spread_half - 0.5, 10.0)],
                asks=[BookLevel(eth_mid + eth_spread_half, 5.0), BookLevel(eth_mid + eth_spread_half + 0.5, 10.0)],
            )
            btc_state = compute_state(btc_book, [btc_ref, btc_mid], reference_price=btc_ref)
            eth_state = compute_state(eth_book, [eth_ref, eth_mid], reference_price=eth_ref)
            desk.tick_pair(btc_state, eth_state)
            broker.sweep("BTCUSDT", btc_mid)
            broker.sweep("ETHUSDT", eth_mid)
            btc_ref = btc_mid
            eth_ref = eth_mid

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()

    print(f"[Desk] GrokBot Day-Trader Terminal running at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="crokbot", description="CrokBotTrading desk")
    sub = ap.add_subparsers(dest="cmd")

    d = sub.add_parser("demo", help="one desk tick against a synthetic book")
    d.add_argument("--live-jev", action="store_true", help="call real Jev via Omniroute")
    d.set_defaults(func=cmd_demo)

    dash = sub.add_parser("dashboard", help="start real-time day trading dashboard")
    dash.add_argument("--host", type=str, default="127.0.0.1", help="host to bind")
    dash.add_argument("--port", type=int, default=8000, help="port to bind")
    dash.add_argument("--interval", type=float, default=2.0, help="seconds per tick")
    dash.add_argument("--live-jev", action="store_true", help="call real Jev via Omniroute")
    dash.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("jev-ping", help="test the Jev connection")
    p.set_defaults(func=cmd_jev_ping)
    
    e = sub.add_parser("etoro-ping", help="test the eToro connection")
    e.add_argument("--api-key", type=str, help="eToro x-api-key")
    e.add_argument("--user-key", type=str, help="eToro x-user-key")
    e.set_defaults(func=cmd_etoro_ping)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)