"""
Grok Bot Desk Live Runner
Runs the Grok Bot Desk with a 300 EUR total capital risk limit,
trading BTCUSDT (Directional + MM + House) and ETHUSDT (ETH/BTC cross-signal filtered),
PaperBroker execution, optional read-only eToro portfolio check via env vars,
and starts the live reactive day-trading dashboard on http://127.0.0.1:8000.
"""

import math
import os
import signal
import sys
import threading
import time
from collections import deque

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import uvicorn

from crokbot.config import Config
from crokbot.dashboard.server import create_app
from crokbot.dashboard.store import TradeStore
from crokbot.desk.orchestrator import Desk
from crokbot.execution.etoro import EToroBroker
from crokbot.execution.paper import PaperBroker
from crokbot.jev.client import get_client
from crokbot.math.indicators import compute_state
from crokbot.state import BookLevel, OrderBook

# -------------------
# Configuration
# -------------------
MAX_TOTAL_RISK_EUR = float(os.environ.get("MAX_TOTAL_RISK_EUR", "300.0"))
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")
ETORO_API_KEY = os.environ.get("ETORO_API_KEY", os.environ.get("ETORO_APP_KEY", ""))
ETORO_USER_KEY = os.environ.get("ETORO_USER_KEY", os.environ.get("ETORO_USERNAME", ""))

cfg = Config(
    primary_symbol="BTCUSDT",
    secondary_symbol="ETHUSDT",
    initial_balance=MAX_TOTAL_RISK_EUR,
    max_position_notional=MAX_TOTAL_RISK_EUR,
    max_order_notional=MAX_TOTAL_RISK_EUR,
    mm_quote_size=0.001,
    eth_quote_size=0.02,
    trust_stage="paper",
)


def main() -> int:
    trade_store = TradeStore()
    trade_store.load_from_jsonl(cfg.events_path)

    if ETORO_API_KEY and ETORO_USER_KEY:
        etoro_broker = EToroBroker(api_key=ETORO_API_KEY, user_key=ETORO_USER_KEY)
        try:
            print("[Desk] Checking eToro open orders...")
            for order in etoro_broker.open_orders():
                print(f"[Desk] Open eToro order: {order.order_id} ({order.side} {order.qty} {order.symbol})")
        except Exception as e:
            print(f"[Desk] eToro connection note: {e}")

    paper_broker = PaperBroker(initial_balance=MAX_TOTAL_RISK_EUR)
    desk = Desk(cfg=cfg, broker=paper_broker, trade_store=trade_store)
    app = create_app(desk=desk, trade_store=trade_store)

    def start_server():
        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    print(f"[Desk] Pro Day-Trader Dashboard running at: http://{HOST}:{PORT}")

    running = True

    def handle_signal(sig, frame):
        nonlocal running
        print("\n[Desk] Shutting down...")
        running = False

    signal.signal(signal.SIGINT, handle_signal)

    print(f"[Desk] Starting Grok Bot Desk with max total risk: {MAX_TOTAL_RISK_EUR} EUR")
    print(f"[Desk] Markets: {cfg.primary_symbol} (Directional + MM + House) & {cfg.secondary_symbol} (ETH/BTC Filtered)")
    print(f"[Desk] Running PaperBroker with Jev AI decision router (confidence floor {cfg.jev_confidence_floor})")

    tick_count = 0
    btc_history = deque([65000.0], maxlen=12)
    eth_history = deque([3250.0], maxlen=12)
    btc_ref_price = 65000.0
    eth_ref_price = 3250.0

    while running and not desk.risk.killed:
        tick_count += 1
        print(f"\n[Desk] ---------------- Tick {tick_count} ----------------")

        # Multi-regime price path: smooth trend wave + periodic ETH/BTC relative drawdown
        wave = math.sin(tick_count * 0.45)
        btc_mid = round(65000.0 + wave * 95.0, 2)
        if tick_count % 6 in (4, 5):
            # Sharp ETH underperformance vs BTC -> triggers ETH/BTC falling_sharply filter
            eth_mid = round(3250.0 + wave * 3.0 - 11.0, 2)
        else:
            eth_mid = round(3250.0 + wave * 5.2, 2)

        btc_history.append(btc_mid)
        eth_history.append(eth_mid)
        paper_broker.set_market("BTCUSDT", btc_mid)
        paper_broker.set_market("ETHUSDT", eth_mid)

        # Book depth skews lightly with short-term momentum
        btc_imb_factor = 1.35 if btc_mid >= btc_ref_price else 0.70
        eth_imb_factor = 1.30 if eth_mid >= eth_ref_price else 0.70

        btc_spread_half = 15.0
        btc_book = OrderBook(
            symbol="BTCUSDT",
            bids=[
                BookLevel(price=round(btc_mid - btc_spread_half, 2), qty=round(0.05 * btc_imb_factor, 4)),
                BookLevel(price=round(btc_mid - btc_spread_half - 5.0, 2), qty=0.10),
            ],
            asks=[
                BookLevel(price=round(btc_mid + btc_spread_half, 2), qty=round(0.05 / btc_imb_factor, 4)),
                BookLevel(price=round(btc_mid + btc_spread_half + 5.0, 2), qty=0.10),
            ],
        )

        eth_spread_half = 0.80
        eth_book = OrderBook(
            symbol="ETHUSDT",
            bids=[
                BookLevel(price=round(eth_mid - eth_spread_half, 2), qty=round(1.0 * eth_imb_factor, 4)),
                BookLevel(price=round(eth_mid - eth_spread_half - 0.5, 2), qty=2.0),
            ],
            asks=[
                BookLevel(price=round(eth_mid + eth_spread_half, 2), qty=round(1.0 / eth_imb_factor, 4)),
                BookLevel(price=round(eth_mid + eth_spread_half + 0.5, 2), qty=2.0),
            ],
        )

        btc_state = compute_state(book=btc_book, prices=list(btc_history), reference_price=btc_ref_price)
        eth_state = compute_state(book=eth_book, prices=list(eth_history), reference_price=eth_ref_price)

        jev = get_client()
        mode = "Omniroute Live" if jev.is_live() else "Quantitative Heuristic / Standby"
        print(f"[Desk] Jev Model Connected: {jev.enabled()} ({mode})")

        orders = desk.tick_pair(btc_state, eth_state)

        ratio = eth_state.extra.get("eth_btc_ratio", 0.0)
        ratio_bps = eth_state.extra.get("eth_btc_change_bps", 0.0)
        regime = eth_state.extra.get("eth_btc_regime", "neutral")
        print(f"[Pair] BTCUSDT=${btc_mid:.2f} | ETHUSDT=${eth_mid:.2f} | ETH/BTC={ratio:.6f} ({ratio_bps:+.1f} bps, {regime})")

        if tick_count % 3 == 0:
            filled_btc = paper_broker.sweep("BTCUSDT", btc_mid + btc_spread_half + 1.0)
            filled_eth = paper_broker.sweep("ETHUSDT", eth_mid + eth_spread_half + 0.1)
        elif tick_count % 3 == 1:
            filled_btc = paper_broker.sweep("BTCUSDT", btc_mid - btc_spread_half - 1.0)
            filled_eth = paper_broker.sweep("ETHUSDT", eth_mid - eth_spread_half - 0.1)
        else:
            filled_btc = paper_broker.sweep("BTCUSDT", btc_mid)
            filled_eth = paper_broker.sweep("ETHUSDT", eth_mid)

        filled_count = filled_btc + filled_eth
        print(f"[Desk] Cash Balance: €{paper_broker.balance():.2f}")
        print(f"[Desk] Positions: {paper_broker.positions()}")
        print(f"[Desk] Orders Placed This Tick: {len(orders)} (Fills: {filled_count})")

        btc_ref_price = btc_state.mid_price
        eth_ref_price = eth_state.mid_price
        time.sleep(3)

    desk.close()
    print("[Desk] Exit complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
