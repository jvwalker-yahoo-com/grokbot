# GrokBot Trading Desk (`crokbot`)

24/7 autonomous multi-bot crypto trading desk trading **BTC/USDT** (`BTCUSDT`) and **ETH/USDT** (`ETHUSDT`) with a cross-market **ETH/BTC relative-strength regime filter** and a real-time TradingView/Bloomberg-style WebSocket terminal.

## Architecture (5 Strictly Separated Layers)

1. **State & Math (`crokbot/math/indicators.py`, `crokbot/state.py`)**: All arithmetic runs in deterministic Python — mid price, spread (bps), L2 book & near-touch order imbalance, log-return realized volatility, and the synthetic `ETH/BTC` cross-ratio signal (`falling_sharply`, `neutral`, `rising_sharply`). Models never do arithmetic.
2. **Decision Layer (`crokbot/jev/`)**: Atomic numbered batteries answered by Jev (`openrouter/typesafe/jev-router` via Omniroute) with a quantitative microstructure heuristic engine when offline/unconfigured.
3. **Policy Layer (`crokbot/policy/compose.py`)**: Code-owned confidence gates, sizing weights, quote skews, fractional crypto inventory tolerances, and cross-asset `ETH/BTC` filtering (blocking ETH longs when `ETH/BTC` drops $\le -15\text{ bps}$ and skewing ETH market-maker quotes defensively).
4. **Deterministic Risk Gate (`crokbot/risk/engine.py`)**: Pre-trade choke-point enforcing effective market/limit order notional caps, total portfolio exposure across all held pairs, risk-reducing close exemptions, mark-to-market daily loss circuit breakers, price sanity bands, self-trade prevention, and an operator emergency kill switch.
5. **Execution & Live Dashboard (`crokbot/execution/`, `crokbot/dashboard/`)**: Interchangeable `PaperBroker` (multi-symbol pricing, resting quote sweeps, fill-listener PnL sync) and `EToroBroker` (eToro Public API v1 with ID resolution and at-most-once execution safety), streamed over FastAPI + WebSockets (`/ws/stream`, `/api/summary`, `/api/market`, `/api/trades`, `/api/health`).

## Quick Start

```bash
pip install -e ".[dev]"
pytest
python crokbot_live_run.py
```

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

## Cloud Deployment (Render)

Includes [`render.yaml`](render.yaml) Blueprint and [`Dockerfile`](Dockerfile):

```bash
uvicorn crokbot.dashboard.server:app --host 0.0.0.0 --port ${PORT:-8000}
```

When `AUTO_START_DESK=true` (enabled by default in `render.yaml`), the ASGI lifespan worker automatically starts the live `BTCUSDT` + `ETHUSDT` trading loop and streams telemetry to connected browsers.
