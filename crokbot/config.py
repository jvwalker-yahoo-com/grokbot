"""Configuration. Single source of truth, loaded from env / .env with paper defaults.

Convention: every *_pct field is an ACTUAL PERCENTAGE (1.2 = 1.2%), matching the
risk_engine math which divides by 100.0.
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv optional
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Jev runs through the local Omniroute router. Bare "typesafe/jev-router"
# returns 401; the OpenRouter-qualified name is the one that works.
JEVE_BASE_URL = os.environ.get("JEVE_BASE_URL", "http://127.0.0.1:20128/v1")
JEVE_MODEL = os.environ.get("JEVE_MODEL", "openrouter/typesafe/jev-router")


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("true", "1", "yes", "on")


class Config(BaseModel):
    # ---- decision layer ----
    omniroute_api_key: str = os.environ.get("OMNIROUTE_API_KEY", "")
    jev_model: str = JEVE_MODEL
    jev_base_url: str = JEVE_BASE_URL
    jev_confidence_floor: float = float(os.environ.get("JEV_CONFIDENCE_FLOOR", "0.6"))

    # ---- execution ----
    execution_mode: str = os.environ.get("EXECUTION_MODE", "paper").lower()  # paper | live
    broker: str = os.environ.get("BROKER", "paper").lower()  # paper | etoro

    # ---- eToro (wired when credentials arrive) ----
    etoro_username: str = os.environ.get("ETORO_USERNAME", "")
    etoro_password: str = os.environ.get("ETORO_PASSWORD", "")
    etoro_app_key: str = os.environ.get("ETORO_APP_KEY", "")
    etoro_account_id: str = os.environ.get("ETORO_ACCOUNT_ID", "")

    # ---- risk & sizing (percentages) ----
    initial_balance: float = float(os.environ.get("INITIAL_BALANCE", "100000.0"))
    max_order_notional: float = float(os.environ.get("MAX_ORDER_NOTIONAL", "5000.0"))
    max_position_notional: float = float(os.environ.get("MAX_POSITION_NOTIONAL", "25000.0"))
    max_open_orders: int = int(os.environ.get("MAX_OPEN_ORDERS", "8"))
    max_daily_loss_pct: float = float(os.environ.get("MAX_DAILY_LOSS_PCT", "5.0"))
    price_band_pct: float = float(os.environ.get("PRICE_BAND_PCT", "0.5"))
    self_trade_prevention: bool = _env_bool("SELF_TRADE_PREVENTION", True)

    # ---- market making & pair configuration ----
    primary_symbol: str = os.environ.get("PRIMARY_SYMBOL", "BTCUSDT")
    secondary_symbol: str = os.environ.get("SECONDARY_SYMBOL", "ETHUSDT")
    mm_tick_size: float = float(os.environ.get("MM_TICK_SIZE", "0.01"))
    mm_quote_size: float = float(os.environ.get("MM_QUOTE_SIZE", "1.0"))
    eth_quote_size: float = float(os.environ.get("ETH_QUOTE_SIZE", "0.03"))
    mm_post_only: bool = _env_bool("MM_POST_ONLY", True)
    mm_min_spread_bps: float = float(os.environ.get("MM_MIN_SPREAD_BPS", "2"))
    eth_btc_drop_threshold_bps: float = float(os.environ.get("ETH_BTC_DROP_THRESHOLD_BPS", "-15.0"))
    eth_btc_rise_threshold_bps: float = float(os.environ.get("ETH_BTC_RISE_THRESHOLD_BPS", "15.0"))

    # ---- trust ladder ----
    trust_stage: str = os.environ.get("TRUST_STAGE", "paper").lower()  # paper|small|scale

    # ---- persistence ----
    state_path: str = str(DATA_DIR / "trading_state.json")
    events_path: str = str(DATA_DIR / "events.jsonl")

    def is_paper(self) -> bool:
        return self.execution_mode == "paper"

    def is_live(self) -> bool:
        return self.execution_mode == "live"


config = Config()