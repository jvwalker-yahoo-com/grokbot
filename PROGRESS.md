# CrokBotTrading Progress

## Completed Milestones

### 1. End-to-End Core Architecture & Pro Day-Trader Dashboard
- **5-Layer Architecture**: Strictly separated pipeline (`state -> Jev -> policy -> risk -> execution`) so models never perform arithmetic and deterministic code owns all thresholds and risk gates.
- **State & Math (`crokbot/math/indicators.py`)**: Computes mid price, spread (bps), L2 and near-touch order book imbalance, and log-return realized volatility.
- **Pro Day-Trader Terminal (`crokbot/dashboard/`, `dashboard.html`)**:
  - Thread-safe `TradeStore` tracking every order/fill, status, execution reason, realized PnL, win rate %, profit factor, portfolio drawdown, and CSV export.
  - FastAPI + WebSocket real-time broadcaster (`/ws/stream`, `/api/trades`, `/api/summary`, `/api/market`, `/api/trades/export`, `/api/emergency/kill`, `/api/orders/manual`, `/api/health`).
  - Institutional dark UI with real-time execution chart, L2 depth telemetry, Jev reasoning cards, portfolio exposure panel, market/side/bot/status filters, and emergency kill switch.

### 2. Multi-Asset BTC/ETH Trading with Cross-Pair `ETH/BTC` Regime Filter
- **Separate Tradeable Markets**: Configured `BTCUSDT` (Directional + Market Maker + House) and `ETHUSDT` as independent books with per-symbol quote sizing (`mm_quote_size` and `eth_quote_size`) and per-symbol mark-to-market pricing in `PaperBroker` and `RiskEngine`.
- **Cross-Market `ETH/BTC` Signal (`compute_pair_ratio`, `compute_pair_signal`, `Desk.tick_pair`)**:
  - Computes synthetic `ETH/BTC` ratio and basis-point momentum in deterministic Python.
  - Blocks `ETHUSDT` directional longs whenever `ETH/BTC` is `falling_sharply` ($\le -15\text{ bps}$), blocks `ETHUSDT` shorts when `ETH/BTC` is `rising_sharply` ($\ge +15\text{ bps}$), and applies defensive sell-skew to `ETHUSDT` market-making quotes during sharp `ETH/BTC` drops.
  - Surfaced live `ETH/BTC` filter state across WebSocket snapshots, REST endpoints, and dashboard KPI/status badges.

### 3. Design Review, Decision-Layer Hardening & Trading Risk Fixes (2026-11-26)
- **Quantitative State-Driven Heuristic Engine (`crokbot/jev/client.py`)**:
  - Replaced static placeholder fallback responses (which previously went blindly long every tick regardless of market drops) with a microstructure-aware quantitative heuristic that parses the `STATE` block (`price_change_bps`, `order_imbalance`, `near_imbalance`, `realized_vol`, `spread_bps`, `net_inventory_qty`, `eth_btc_regime`).
  - `DirectionalBot` now requires momentum + book-pressure confluence (going `long` on bullish momentum, `short` on bearish momentum, and `flat`/`no` edge in choppy/ranging noise).
  - `MarketMakerBot` automatically pulls quotes during volatility spikes (`realized_vol > 2.5%`) or extreme book imbalance, and skews with near-touch flow.
  - `HouseBot` detects real inventory drift and triggers delta-neutral rebalancing.
- **Jev Battery Parser Hardening (`crokbot/jev/parser.py`, `crokbot/desk/bots.py`)**:
  - Filters out LLM preamble/chatter lines when numbered answers (`1. ... N.`) are present so positional answer indices never shift.
  - Rejects truncated batteries (`len(lines) < n`) cleanly via `JevAnswers.none()` so partial responses can never be misread as confidence scores.
- **Critical Risk & Execution Fixes (`crokbot/risk/engine.py`, `crokbot/desk/orchestrator.py`, `crokbot/policy/compose.py`, `crokbot/execution/paper.py`)**:
  - **Market Order Notional Gate**: Fixed `Order` / `RiskEngine.check` where market orders (`price=0.0`) previously evaluated `notional == 0.0` and bypassed `max_order_notional` and `notional_cap`. Market orders now compute effective notional against reference/mark price.
  - **Portfolio-Wide Gross Exposure & Risk-Reducing Close Exemption**: Enforced aggregate exposure across all open symbols (`BTCUSDT` + `ETHUSDT`) against `notional_cap` while explicitly permitting exposure-reducing/closing trades even when an account is at or above cap.
  - **Fractional Crypto Inventory Tolerance**: Scaled `house_policy` target tolerance dynamically (`2x` symbol base quote size) instead of a hardcoded `1.0` unit (which previously ignored any BTC position under 1 BTC / ~$65k).
  - **Quote Replacement & Fill PnL Sync**: `Desk.tick` now cancels stale resting quotes per bot/symbol before placing refreshed quotes (preventing `max_open_orders` lockouts), and `PaperBroker` notifies `Desk`/`TradeStore` via fill listeners whenever resting limit orders fill during market sweeps.
- **eToro Public API v1 Alignment & Secret Hygiene (`crokbot/execution/etoro.py`, `crokbot_live_run.py`)**:
  - Added static + search-backed `resolve_instrument_id` (`BTCUSDT -> 100000`, `ETHUSDT -> 100001`), `/trading/info/{env}/pnl` Available Cash formula, non-mixed auth headers, and at-most-once POST execution safety (backoff on 429 only; never auto-resend ambiguous timeouts).
  - Removed hardcoded credentials from `crokbot_live_run.py` in favor of environment variables.
- **Cloud & Render Deployment (`render.yaml`, `Dockerfile`, `requirements.txt`, `.github/workflows/`)**:
  - Added module-level ASGI `crokbot.dashboard.server:app` with lifespan background desk loop (`AUTO_START_DESK=true`), `/api/health` endpoint, GitHub Actions CI + Render keep-alive cron, and knowledge graph updates (`graft` & `graphify`).
  - **Automated Verification**: **63 automated tests passing** across unit, risk, policy, pair-filter, parser, broker, and end-to-end dashboard suites.
