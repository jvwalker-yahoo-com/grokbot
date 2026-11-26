"""FastAPI backend & WebSocket real-time broadcaster for the trading dashboard."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from ..execution.broker import Intent
from ..state import ComputedState
from .store import TradeRecord, TradeStore

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_HTML_PATH = BASE_DIR / "dashboard.html"


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(dead)

    def broadcast_sync(self, message: dict):
        """Thread-safe synchronous broadcast call from trading engine thread."""
        if not self.active_connections:
            return
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self._loop)


class ManualOrderRequest(BaseModel):
    symbol: str
    side: str  # buy | sell
    qty: float
    price: float = 0.0  # 0.0 = market
    order_type: str = "market"


def create_app(
    desk=None,
    trade_store: Optional[TradeStore] = None,
    html_path: Optional[str] = None,
) -> FastAPI:
    app = FastAPI(title="GrokBot Day-Trader Terminal", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = trade_store or TradeStore()
    manager = ConnectionManager()
    markets_by_symbol: Dict[str, Dict[str, object]] = {}
    pair_filter: Dict[str, object] = {
        "eth_btc_ratio": 0.05,
        "eth_btc_change_bps": 0.0,
        "eth_btc_regime": "neutral",
    }
    latest_market_state: Dict[str, object] = {
        "symbol": "BTCUSDT",
        "mid_price": 65000.0,
        "spread_bps": 2.0,
        "order_imbalance": 0.0,
        "realized_vol": 0.015,
        "bid_price": 64999.0,
        "ask_price": 65001.0,
        "markets": markets_by_symbol,
        "pair_filter": pair_filter,
    }

    # Wire store listener to broadcast new trades in real-time
    def on_trade_recorded(trade: TradeRecord):
        manager.broadcast_sync({
            "type": "trade_executed",
            "trade": trade.to_dict(),
        })

    store.add_listener(on_trade_recorded)

    # Wire desk event callback if available
    if desk:
        orig_callback = desk.event_callback

        def on_desk_event(ev: dict):
            if orig_callback:
                orig_callback(ev)
            if ev.get("type") == "tick":
                sym = str(ev.get("symbol", "BTCUSDT"))
                markets_by_symbol[sym] = {k: v for k, v in ev.items() if k not in ("markets", "pair_filter")}
                if "eth_btc_ratio" in ev:
                    pair_filter["eth_btc_ratio"] = ev.get("eth_btc_ratio")
                    pair_filter["eth_btc_change_bps"] = ev.get("eth_btc_change_bps", 0.0)
                    pair_filter["eth_btc_regime"] = ev.get("eth_btc_regime", "neutral")
                latest_market_state.update(ev)
                latest_market_state["markets"] = markets_by_symbol
                latest_market_state["pair_filter"] = pair_filter
            manager.broadcast_sync(ev)

        desk.event_callback = on_desk_event

    dashboard_file = Path(html_path) if html_path else DEFAULT_HTML_PATH

    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard():
        if dashboard_file.exists():
            return HTMLResponse(content=dashboard_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>Dashboard file not found.</h1>", status_code=404)

    @app.get("/api/health")
    @app.get("/health")
    async def get_health():
        killed = desk.risk.killed if (desk and hasattr(desk, "risk")) else False
        return {
            "status": "ok",
            "desk_status": "killed" if killed else "running",
            "markets": list(markets_by_symbol.keys()),
            "pair_filter": pair_filter,
        }

    @app.get("/api/trades")
    async def list_trades(
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        status: Optional[str] = None,
        bot_name: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ):
        trades = store.get_trades(
            symbol=symbol,
            side=side,
            status=status,
            bot_name=bot_name,
            limit=limit,
            offset=offset,
        )
        return {
            "trades": [t.to_dict() for t in trades],
            "total": len(store._trades),
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/trades/export")
    async def export_trades():
        csv_data = store.export_csv()
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=grokbot_trades.csv"},
        )

    def _calc_equity() -> float:
        cash = desk.broker.balance() if desk else 100_000.0
        equity = cash
        if desk and hasattr(desk.broker, "positions"):
            pos = desk.broker.positions()
            market_prices = getattr(desk.broker, "market_prices", {}) or {}
            fallback_price = getattr(desk.broker, "current_price", None) or 0.0
            for sym, qty in pos.items():
                px = market_prices.get(sym, fallback_price) or 0.0
                if px > 0:
                    equity += qty * px
        return equity

    @app.get("/api/summary")
    async def get_summary():
        cash = desk.broker.balance() if desk else 100_000.0
        day_start = desk.risk._day_start_balance if (desk and hasattr(desk, "risk")) else cash
        equity = _calc_equity()
        metrics = store.get_metrics(initial_balance=day_start, current_balance=equity)
        killed = desk.risk.killed if (desk and hasattr(desk, "risk")) else False
        return {
            "metrics": as_dict(metrics),
            "desk_status": "killed" if killed else "running",
            "cash_balance": cash,
            "positions": desk.broker.positions() if desk else {},
            "open_orders": len(desk.broker.open_orders()) if desk else 0,
            "trust_stage": desk.cfg.trust_stage if desk else "paper",
            "notional_cap": desk.risk.notional_cap if desk else 25000.0,
            "markets": markets_by_symbol,
            "pair_filter": pair_filter,
        }

    @app.get("/api/positions")
    async def get_positions():
        if not desk:
            return {"positions": {}}
        return {
            "positions": desk.broker.positions(),
            "cash_balance": desk.broker.balance(),
        }

    @app.get("/api/orders")
    async def get_open_orders():
        if not desk:
            return {"open_orders": []}
        return {
            "open_orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "qty": o.qty,
                    "price": o.price,
                    "notional": o.notional,
                    "order_type": o.order_type,
                    "status": o.status,
                }
                for o in desk.broker.open_orders()
            ]
        }

    @app.get("/api/market")
    async def get_market():
        return latest_market_state

    @app.post("/api/emergency/kill")
    async def emergency_kill():
        if desk:
            desk.kill()
        await manager.broadcast({
            "type": "kill_switch",
            "status": "killed",
            "message": "Emergency kill switch engaged by operator.",
        })
        return {"status": "killed", "message": "Emergency kill switch activated."}

    @app.post("/api/orders/manual")
    async def place_manual_order(req: ManualOrderRequest):
        if not desk:
            return {"status": "rejected", "reason": "No active desk connected"}
        
        intent = Intent(
            symbol=req.symbol,
            action=req.side.lower(),
            side=req.side.lower(),
            qty=req.qty,
            price=req.price if req.price > 0 else None,
            reason="manual trader intervention",
        )
        
        sym_state = markets_by_symbol.get(req.symbol, latest_market_state)
        default_mid = 3250.0 if req.symbol.upper().startswith("ETH") else 65000.0
        mid_px = float(sym_state.get("mid_price", default_mid))
        dummy_state = ComputedState(
            symbol=req.symbol,
            mid_price=mid_px,
            spread=float(sym_state.get("spread_bps", 2.0)),
            spread_bps=float(sym_state.get("spread_bps", 2.0)),
            order_imbalance=float(sym_state.get("order_imbalance", 0.0)),
            near_imbalance=0.0,
            realized_vol=float(sym_state.get("realized_vol", 0.015)),
            price_change_bps=0.0,
            reference_price=mid_px,
            bid_depth=10.0,
            ask_depth=10.0,
            bid_price=float(sym_state.get("bid_price", mid_px - 0.5)),
            ask_price=float(sym_state.get("ask_price", mid_px + 0.5)),
            extra=dict(pair_filter),
        )
        
        orders = desk.apply(intent, dummy_state, bot_name="manual")
        return {"placed": len(orders), "orders": [o.order_id for o in orders]}

    @app.websocket("/ws/stream")
    async def websocket_stream(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            # Send initial snapshot
            cash = desk.broker.balance() if desk else 100_000.0
            day_start = desk.risk._day_start_balance if (desk and hasattr(desk, "risk")) else cash
            equity = _calc_equity()
            await websocket.send_json({
                "type": "snapshot",
                "metrics": as_dict(store.get_metrics(initial_balance=day_start, current_balance=equity)),
                "market": latest_market_state,
                "trades": [t.to_dict() for t in store.get_trades(limit=50)],
                "positions": desk.broker.positions() if desk else {},
                "open_orders": len(desk.broker.open_orders()) if desk else 0,
                "desk_status": "killed" if (desk and desk.risk.killed) else "running",
            })
            while True:
                # Keep alive and receive any client messages (heartbeats or ping)
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception:
            manager.disconnect(websocket)

    return app


def as_dict(dataclass_obj) -> dict:
    from dataclasses import asdict
    return asdict(dataclass_obj)


def _create_cloud_app() -> FastAPI:
    """Module-level ASGI app for Render / Docker (`uvicorn crokbot.dashboard.server:app`)."""
    import math
    import threading
    import time
    from collections import deque
    from contextlib import asynccontextmanager

    from ..config import Config
    from ..desk.orchestrator import Desk
    from ..execution.paper import PaperBroker
    from ..math.indicators import compute_state
    from ..state import BookLevel, OrderBook

    cfg = Config()
    store = TradeStore()
    store.load_from_jsonl(cfg.events_path)
    broker = PaperBroker(initial_balance=cfg.initial_balance)
    cloud_desk = Desk(cfg=cfg, broker=broker, trade_store=store)
    stop_event = threading.Event()

    def _bg_loop():
        tick_count = 0
        btc_hist = deque([65000.0], maxlen=12)
        eth_hist = deque([3250.0], maxlen=12)
        btc_ref, eth_ref = 65000.0, 3250.0
        while not stop_event.is_set() and not cloud_desk.risk.killed:
            tick_count += 1
            wave = math.sin(tick_count * 0.45)
            btc_mid = round(65000.0 + wave * 95.0, 2)
            eth_mid = round(3250.0 + wave * 3.0 - 11.0, 2) if (tick_count % 6 in (4, 5)) else round(3250.0 + wave * 5.2, 2)
            btc_hist.append(btc_mid)
            eth_hist.append(eth_mid)
            broker.set_market(cfg.primary_symbol, btc_mid)
            broker.set_market(cfg.secondary_symbol, eth_mid)

            btc_imb = 1.35 if btc_mid >= btc_ref else 0.70
            eth_imb = 1.30 if eth_mid >= eth_ref else 0.70
            btc_book = OrderBook(
                symbol=cfg.primary_symbol,
                bids=[BookLevel(round(btc_mid - 15.0, 2), round(0.05 * btc_imb, 4)), BookLevel(round(btc_mid - 20.0, 2), 0.10)],
                asks=[BookLevel(round(btc_mid + 15.0, 2), round(0.05 / btc_imb, 4)), BookLevel(round(btc_mid + 20.0, 2), 0.10)],
            )
            eth_book = OrderBook(
                symbol=cfg.secondary_symbol,
                bids=[BookLevel(round(eth_mid - 0.8, 2), round(1.0 * eth_imb, 4)), BookLevel(round(eth_mid - 1.3, 2), 2.0)],
                asks=[BookLevel(round(eth_mid + 0.8, 2), round(1.0 / eth_imb, 4)), BookLevel(round(eth_mid + 1.3, 2), 2.0)],
            )
            btc_st = compute_state(btc_book, list(btc_hist), reference_price=btc_ref)
            eth_st = compute_state(eth_book, list(eth_hist), reference_price=eth_ref)
            cloud_desk.tick_pair(btc_st, eth_st)

            if tick_count % 3 == 0:
                broker.sweep(cfg.primary_symbol, btc_mid + 16.0)
                broker.sweep(cfg.secondary_symbol, eth_mid + 0.9)
            elif tick_count % 3 == 1:
                broker.sweep(cfg.primary_symbol, btc_mid - 16.0)
                broker.sweep(cfg.secondary_symbol, eth_mid - 0.9)
            else:
                broker.sweep(cfg.primary_symbol, btc_mid)
                broker.sweep(cfg.secondary_symbol, eth_mid)

            btc_ref, eth_ref = btc_mid, eth_mid
            stop_event.wait(3.0)

    cloud_app = create_app(desk=cloud_desk, trade_store=store)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        worker = None
        if os.environ.get("AUTO_START_DESK", "false").strip().lower() in ("1", "true", "yes", "on"):
            stop_event.clear()
            worker = threading.Thread(target=_bg_loop, daemon=True)
            worker.start()
        try:
            yield
        finally:
            stop_event.set()
            cloud_desk.close()

    cloud_app.router.lifespan_context = _lifespan
    return cloud_app


app = _create_cloud_app()
