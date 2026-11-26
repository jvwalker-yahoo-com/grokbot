# Pro Day-Trader Full Trading Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a professional institutional-grade trading dashboard that streams, displays, filters, and analyzes all trades, positions, order books, Jev AI decisions, and risk controls in real time.

**Architecture:** A thread-safe, event-sourced Trade Store (`crokbot/dashboard/store.py`) that syncs with `Desk`, `PaperBroker`, and `events.jsonl`, backed by a lightweight FastAPI + WebSocket server (`crokbot/dashboard/server.py`) delivering reactive sub-second state to a high-contrast Bloomberg/TradingView-style day trading terminal (`dashboard.html` / `crokbot/dashboard/static/`). Includes REST API endpoints for trade history, CSV export, live positions, PnL analytics, and desk kill-switch control.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, WebSockets, Pydantic, Chart.js / Canvas, HTML5/CSS3.

**Spec:** Professional day trading terminal requirements: comprehensive trade blotter with execution filtering, millisecond timestamps, side/type badges, realized PnL calculations, live order book depth, Jev AI confidence telemetry, portfolio risk gauges, CSV export, and emergency kill-switch controls.

## Global Constraints

- Preserve all existing 34 passing tests and desk behavior (`tests/`).
- Hard-coded deterministic risk checks remain inviolate; dashboard cannot bypass risk gates.
- Event sourcing compatibility: all trades and executions must persist to `data/events.jsonl` and reload cleanly on restart.
- No external heavy frontend node build steps required: self-contained single-page web app runnable on any browser without npm install.

## Review Focus

1. **Trade Filtering & Volume Handling**: Trade table must smoothly handle hundreds of trades with real-time updates without DOM freezing or stutter.
2. **Realized & Unrealized PnL Accuracy**: Proper FIFO or average-cost matching for buys/sells to calculate real trade PnL without drifting from broker cash balance.
3. **WebSocket Disconnect & Reconnect**: Client UI must auto-reconnect with exponential backoff and backfill missed trades if the connection drops.
4. **Safety & Kill Switch Responsiveness**: Kill switch endpoint must trigger `desk.kill()`, cancel all resting orders immediately, and broadcast state change to all connected clients.
5. **Cold-start Rehydration**: Starting the dashboard when previous events exist in `data/events.jsonl` must restore trade history and performance metrics accurately.

---

### Task 1: Trade Data Model, PnL Engine & Event Store

**Files:**
- Create: `crokbot/dashboard/store.py`
- Create: `tests/test_dashboard_store.py`
- Modify: `crokbot/execution/paper.py` (ensure fills carry timestamps, order references, and realized PnL)

- [x] Write failing unit tests in `tests/test_dashboard_store.py` testing trade recording, PnL calculation, filtering, pagination, and persistence reload from JSONL.
- [x] Run `python -m pytest tests/test_dashboard_store.py` to confirm test failures.
- [x] Implement `TradeRecord`, `PerformanceMetrics`, and `TradeStore` in `crokbot/dashboard/store.py`.
- [x] Update `crokbot/execution/paper.py` to compute realized PnL and attach timestamp/metadata on fills.
- [x] Run `python -m pytest tests/test_dashboard_store.py` and ensure all tests pass.
- [x] Verify existing test suite: `python -m pytest`.

---

### Task 2: Desk Instrumentation & Live Event Streaming

**Files:**
- Modify: `crokbot/desk/orchestrator.py`
- Create: `tests/test_desk_instrumentation.py`

- [x] Write unit tests in `tests/test_desk_instrumentation.py` verifying that `Desk` registers trade store callbacks, attaches timestamps, bot attribution, and execution status to every event.
- [x] Run `python -m pytest tests/test_desk_instrumentation.py` to confirm failure.
- [x] Update `crokbot/desk/orchestrator.py` to accept an optional `trade_store` or event listener, enrich order events with timestamps, bot names, notional values, and broadcast fills/decisions.
- [x] Run `python -m pytest tests/test_desk_instrumentation.py` and ensure tests pass.
- [x] Verify entire test suite remains green: `python -m pytest`.

---

### Task 3: FastAPI Backend Server & WebSocket Broadcaster

**Files:**
- Create: `crokbot/dashboard/server.py`
- Create: `tests/test_dashboard_api.py`

- [x] Write tests in `tests/test_dashboard_api.py` covering endpoints:
  - `GET /api/trades` (with side, bot, status filters)
  - `GET /api/trades/export` (CSV export format)
  - `GET /api/summary` (metrics, balance, win rate)
  - `GET /api/positions` & `GET /api/orders`
  - `POST /api/emergency/kill`
- [x] Run `python -m pytest tests/test_dashboard_api.py` to confirm failure.
- [x] Implement FastAPI app, REST routes, CSV streaming, and WebSocket broadcast manager in `crokbot/dashboard/server.py`.
- [x] Run `python -m pytest tests/test_dashboard_api.py` and ensure all tests pass.

---

### Task 4: Professional Day-Trader Frontend Terminal

**Files:**
- Overwrite/Enhance: `dashboard.html`
- Create: `crokbot/dashboard/static/app.js` (or embedded modular script in `dashboard.html`)
- Create: `crokbot/dashboard/static/styles.css`

- [x] Build the complete day-trading UI layout:
  - High-visibility header: Desk status, paper/live mode indicator, trust stage, risk budget meter, and emergency Kill Switch button.
  - Performance Metrics cards: Realized PnL, Unrealized PnL, Win/Loss Ratio, Profit Factor, Daily Loss vs 300 EUR Cap, Total Volume.
  - Interactive Trade Blotter ("Showing all trades"):
    - Sortable & filterable table by symbol, side, order type, bot, and execution status.
    - Status pills: FILLED (green), REJECTED (red), CANCELLED (yellow), OPEN (blue).
    - Detailed trade inspection modal/drawer.
    - Export to CSV button.
  - L2 Order Book & Imbalance visualizer (bids/asks ladder with depth bars).
  - Jev AI Reasoning stream with confidence score gauge (red < 0.60, green >= 0.60).
  - Live Price & Execution Chart: Candlestick/line chart with trade execution markers.
  - Manual quick-order execution pad.
- [x] Implement robust WebSocket client with auto-reconnect and real-time DOM updates.

---

### Task 5: End-to-End CLI Integration & Live Runner Verification

**Files:**
- Modify: `crokbot/cli.py`
- Modify: `crokbot_live_run.py`
- Create: `tests/test_e2e_dashboard.py`

- [x] Add `python -m crokbot dashboard` command in `crokbot/cli.py` with flags for port, host, live-jev, and simulated feed.
- [x] Update `crokbot_live_run.py` to integrate seamlessly with the dashboard store and server so live running immediately reflects on the web UI.
- [x] Write and run `tests/test_e2e_dashboard.py` to test full tick generation, order placement, fill recording, and dashboard WebSocket broadcast.
- [x] Run complete test suite: `python -m pytest`.
