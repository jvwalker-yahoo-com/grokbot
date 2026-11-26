# Graph Report - grokbot  (2026-11-26)

## Corpus Check
- 51 files · ~24,291 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 3, .example 1)

## Summary
- 480 nodes · 1398 edges · 28 communities (13 shown, 15 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 195 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Desk & Sizing Configuration
- TradeStore
- Desk
- Order
- indicators.py
- EToroBroker
- test_trading_audit_fixes.py
- Jev Battery Parsing & Types
- Real-time WebSocket Connection Manager
- eToro Account Snapshot Docs
- eToro Instrument ID Resolution Docs
- Package Metadata
- Project Milestones & Progress
- PaperBroker
- target_url
- crokbot_live_run.py
- create_app
- steps
- server.py

## God Nodes (most connected - your core abstractions)
1. `Config` - 64 edges
2. `Order` - 50 edges
3. `PaperBroker` - 49 edges
4. `Desk` - 44 edges
5. `compute_state()` - 40 edges
6. `ComputedState` - 39 edges
7. `create_app()` - 36 edges
8. `TradeStore` - 36 edges
9. `OrderBook` - 33 edges
10. `RiskEngine` - 28 edges

## Surprising Connections (you probably didn't know these)
- `eToro Public API Conventions` --references--> `EToroBroker`  [INFERRED]
  docs/etoro/api-conventions.md → crokbot/execution/etoro.py
- `Architecture (5 Strictly Separated Layers)` --references--> `PaperBroker`  [INFERRED]
  README.md → crokbot/execution/paper.py
- `ETH/BTC Cross-Pair Filter Signal Display` --conceptually_related_to--> `compute_pair_signal()`  [INFERRED]
  dashboard.html → crokbot/math/indicators.py
- `GrokBot Day-Trader Terminal UI` --references--> `create_app()`  [EXTRACTED]
  dashboard.html → crokbot/dashboard/server.py
- `Trading Dashboard Architecture Plan` --references--> `create_app()`  [EXTRACTED]
  docs/superpowers/plans/2026-10-28-trading-dashboard.md → crokbot/dashboard/server.py

## Import Cycles
- None detected.

## Communities (28 total, 15 thin omitted)

### Community 0 - "Desk & Sizing Configuration"
Cohesion: 0.13
Nodes (27): Config, compute_pair_ratio(), compute_pair_signal(), _base_qty(), directional_policy(), _eth_btc_falling_sharply(), _eth_btc_rising_sharply(), _gated() (+19 more)

### Community 1 - "TradeStore"
Cohesion: 0.20
Nodes (9): PerformanceMetrics, TradeRecord, TradeStore, Pro Day-Trader Dashboard Milestone, test_setup(), test_trade_record_creation(), test_trade_store_csv_export(), test_trade_store_metrics() (+1 more)

### Community 2 - "Desk"
Cohesion: 0.07
Nodes (33): build_desk(), cmd_dashboard(), run_loop(), cmd_etoro_ping(), cmd_jev_ping(), _demo_book(), FakeJev, main() (+25 more)

### Community 3 - "Order"
Cohesion: 0.09
Nodes (18): Broker, Fill, Order, Side, gate_and_place(), RiskDecision, RiskEngine, _broker() (+10 more)

### Community 4 - "indicators.py"
Cohesion: 0.11
Nodes (14): mid_price(), order_imbalance(), price_change_bps(), realized_vol(), realized_vol_from_log(), _returns(), spread(), spread_bps() (+6 more)

### Community 5 - "EToroBroker"
Cohesion: 0.08
Nodes (20): EToroBroker, eToro Public API Conventions, eToro API Client Architecture, Architecture (5 Strictly Separated Layers), Cloud Deployment (Render), GrokBot Trading Desk (`crokbot`), Quick Start, key (+12 more)

### Community 6 - "test_trading_audit_fixes.py"
Cohesion: 0.09
Nodes (15): place_manual_order(), Intent, get_client(), _heuristic_answer(), JevClient, _parse_prompt_state(), directional_prompt(), house_prompt() (+7 more)

### Community 7 - "Jev Battery Parsing & Types"
Cohesion: 0.17
Nodes (15): answers_to_dict(), as_bool(), as_float(), as_int(), extract_line(), extract_lines(), _flatten(), parse_answers() (+7 more)

### Community 21 - "PaperBroker"
Cohesion: 0.20
Nodes (10): cmd_demo(), PaperBroker, main(), test_paper_broker_fill_tracking_and_pnl(), test_paper_broker_multi_symbol_prices_and_risk_equity(), test_cancel(), test_limit_rests_then_sweeps(), test_market_buy_fills() (+2 more)

### Community 22 - "target_url"
Cohesion: 0.09
Nodes (21): DEFAULT_URL, INPUT_URL, SECRET_URL, target_url, jobs, keepalive, runs-on, steps (+13 more)

### Community 24 - "create_app"
Cohesion: 0.13
Nodes (8): as_dict(), create_app(), _calc_equity(), get_summary(), on_trade_recorded(), websocket_stream(), GrokBot Day-Trader Terminal UI, Trading Dashboard Architecture Plan

### Community 25 - "steps"
Cohesion: 0.13
Nodes (14): jobs, test, name, on, pull_request, push, branches, name (+6 more)

### Community 27 - "server.py"
Cohesion: 0.20
Nodes (4): _create_cloud_app(), _bg_loop(), _lifespan(), ManualOrderRequest

## Knowledge Gaps
- **10 isolated node(s):** `crokbot-trading`, `Pro Day-Trader Dashboard Milestone`, `GrokBot Day-Trader Terminal UI`, `Trading Dashboard Architecture Plan`, `eToro Account Snapshot & Portfolio Balance` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 181 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PaperBroker` connect `PaperBroker` to `Desk & Sizing Configuration`, `TradeStore`, `Desk`, `Order`, `EToroBroker`, `test_trading_audit_fixes.py`, `crokbot_live_run.py`, `config.py`, `server.py`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `Config` (e.g. with `Bot` and `Desk`) actually correct?**
  _`Config` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `crokbot-trading`, `Pro Day-Trader Dashboard Milestone`, `GrokBot Day-Trader Terminal UI` to the rest of the system?**
  _10 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Desk & Sizing Configuration` be split into smaller, more focused modules?**
  _Cohesion score 0.12525252525252525 - nodes in this community are weakly interconnected._
- **Why does `Config` connect `Desk & Sizing Configuration` to `TradeStore`, `Desk`, `Order`, `test_trading_audit_fixes.py`, `PaperBroker`, `crokbot_live_run.py`, `config.py`, `server.py`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `Order` (e.g. with `Desk` and `EToroBroker`) actually correct?**
  _`Order` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `Desk` be split into smaller, more focused modules?**
  _Cohesion score 0.0669753086419753 - nodes in this community are weakly interconnected._