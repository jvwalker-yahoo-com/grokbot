"""Policy layer: compose Jev's answers into intents. All thresholds in CODE.

Jev answers the battery; code turns those answers into action. The article's
rule — "code applies policy" — means the weights, spread floors, skew sizes and
confidence gates all live here, so re-tuning never touches a Jev question.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..config import Config
from ..execution.broker import Intent
from ..state import ComputedState


@dataclass
class JevAnswers:
    """Positional answers from a Jev battery + parsed confidence."""
    raw: List[str]
    confidence: float = 0.0
    used: bool = True

    def word(self, i: int, default: str = "") -> str:
        return (self.raw[i] if i < len(self.raw) else "").strip().lower() or default

    @classmethod
    def none(cls) -> "JevAnswers":
        return cls(raw=[], confidence=0.0, used=False)


def _gated(ans: JevAnswers, floor: float) -> bool:
    """Act only if Jev actually answered and clears the confidence floor."""
    return ans.used and ans.confidence >= floor


def _base_qty(symbol: str, cfg: Config) -> float:
    """Select base order size for symbol (ETH uses eth_quote_size, others use mm_quote_size)."""
    if symbol.upper().startswith("ETH"):
        return cfg.eth_quote_size
    return cfg.mm_quote_size


def _eth_btc_falling_sharply(s: ComputedState, cfg: Config) -> bool:
    """True when ETH/BTC cross-pair signal indicates a sharp drop."""
    if not s.extra:
        return False
    regime = str(s.extra.get("eth_btc_regime", "")).lower()
    if regime == "falling_sharply":
        return True
    change = float(s.extra.get("eth_btc_change_bps", 0.0) or 0.0)
    return change <= cfg.eth_btc_drop_threshold_bps


def _eth_btc_rising_sharply(s: ComputedState, cfg: Config) -> bool:
    """True when ETH/BTC cross-pair signal indicates a sharp rally."""
    if not s.extra:
        return False
    regime = str(s.extra.get("eth_btc_regime", "")).lower()
    if regime == "rising_sharply":
        return True
    change = float(s.extra.get("eth_btc_change_bps", 0.0) or 0.0)
    return change >= cfg.eth_btc_rise_threshold_bps


# --- Market maker -----------------------------------------------------------

def market_maker_policy(ans: JevAnswers, s: ComputedState, cfg: Config) -> List[Intent]:
    """Quote both sides one tick inside the touch, unless Jev says pull.

    Q1 spread  Q2 pressure  Q3 vol  Q4 quote/pull  Q5 skew  Q6 confidence
    """
    floor = cfg.jev_confidence_floor
    if not ans.used:
        return [Intent(symbol=s.symbol, action="noop", reason="jev unavailable")]

    if ans.word(0) == "thin" or s.spread_bps < cfg.mm_min_spread_bps:
        return [Intent(symbol=s.symbol, action="noop", reason="spread too thin to quote")]

    if s.order_imbalance > 0.8 or s.order_imbalance < -0.8:
        # extreme one-sided book: refuse to quote into it
        return [Intent(symbol=s.symbol, action="cancel", reason="extreme book imbalance")]

    if not _gated(ans, floor):
        return [Intent(symbol=s.symbol, action="cancel", reason=f"confidence {ans.confidence:.2f} < floor {floor}")]

    if ans.word(3) != "quote":
        return [Intent(symbol=s.symbol, action="cancel", reason="jev: pull quotes")]

    tick = cfg.mm_tick_size
    buy_price = round(s.bid_price + tick, 8)
    sell_price = round(s.ask_price - tick, 8)
    if buy_price >= sell_price:
        return [Intent(symbol=s.symbol, action="cancel", reason="touch crossed")]

    base_q = _base_qty(s.symbol, cfg)
    buy_qty = sell_qty = base_q
    skew = ans.word(4)
    if s.symbol.upper().startswith("ETH") and _eth_btc_falling_sharply(s, cfg):
        skew = "sell"
    elif s.symbol.upper().startswith("ETH") and _eth_btc_rising_sharply(s, cfg) and skew == "sell":
        skew = "neutral"

    if skew == "buy":
        buy_qty *= 1.5
        sell_qty *= 0.5
    elif skew == "sell":
        sell_qty *= 1.5
        buy_qty *= 0.5

    return [
        Intent(symbol=s.symbol, action="quote", side="buy", price=buy_price, qty=buy_qty,
               post_only=cfg.mm_post_only, reason="jev quote"),
        Intent(symbol=s.symbol, action="quote", side="sell", price=sell_price, qty=sell_qty,
               post_only=cfg.mm_post_only, reason="jev quote"),
    ]


# --- The House (delta-neutral) ----------------------------------------------

def house_policy(ans: JevAnswers, s: ComputedState, net_qty: float, target_qty: float,
                 cfg: Config) -> List[Intent]:
    """Drive net inventory toward zero; direction-agnostic by construction.

    Q1 imbalance  Q2 rebalance?  Q3 market/quote  Q4 spread worth it  Q5 confidence
    """
    floor = cfg.jev_confidence_floor
    if not ans.used:
        return [Intent(symbol=s.symbol, action="noop", reason="jev unavailable")]

    base_q = _base_qty(s.symbol, cfg)
    tol = max(1e-9, abs(target_qty) * 0.2 if target_qty else base_q * 2.0)
    at_target = abs(net_qty - target_qty) <= tol

    if at_target:
        # Still capture spread opportunistically if Jev says it's worth it.
        if ans.word(3) == "yes" and _gated(ans, floor):
            tick = cfg.mm_tick_size
            buy_p = round(s.bid_price + tick, 8)
            sell_p = round(s.ask_price - tick, 8)
            if buy_p >= sell_p:
                return [Intent(symbol=s.symbol, action="noop", reason="touch too tight to farm")]
            return [
                Intent(symbol=s.symbol, action="quote", side="buy", price=buy_p,
                       qty=base_q, post_only=True, reason="house spread farm"),
                Intent(symbol=s.symbol, action="quote", side="sell", price=sell_p,
                       qty=base_q, post_only=True, reason="house spread farm"),
            ]
        return [Intent(symbol=s.symbol, action="noop", reason="at target, no spread edge")]

    if not _gated(ans, floor):
        return [Intent(symbol=s.symbol, action="noop", reason=f"confidence {ans.confidence:.2f} < floor")]

    if ans.word(1) != "yes":
        return [Intent(symbol=s.symbol, action="noop", reason="jev: hold inventory")]

    # Rebalance toward target. Direction strictly reduces |net - target|.
    side = "sell" if net_qty > target_qty else "buy"
    size = abs(net_qty - target_qty)
    price = 0.0  # market
    if ans.word(2) == "quote":
        price = s.bid_price if side == "sell" else s.ask_price
    return [Intent(symbol=s.symbol, action="rebalance", side=side, price=price, qty=size,
                   reason="house rebalance to target")]


# --- Directional ------------------------------------------------------------

def directional_policy(ans: JevAnswers, s: ComputedState, cfg: Config) -> List[Intent]:
    """Take a directional bet only on a clean edge + confidence gate.

    Q1 regime  Q2 edge?  Q3 long/short/flat  Q4 conviction  Q5 confidence
    """
    floor = cfg.jev_confidence_floor
    if not ans.used:
        return [Intent(symbol=s.symbol, action="noop", reason="jev unavailable")]

    if ans.word(1) != "yes":
        return [Intent(symbol=s.symbol, action="noop", reason="no clean edge")]

    direction = ans.word(2)
    if direction not in ("long", "short"):
        return [Intent(symbol=s.symbol, action="noop", reason="no direction")]

    # Cross-market ETH/BTC filter: avoid ETH longs when ETH/BTC is falling sharply
    if s.symbol.upper().startswith("ETH"):
        if direction == "long" and _eth_btc_falling_sharply(s, cfg):
            return [Intent(symbol=s.symbol, action="noop",
                           reason="eth/btc falling sharply: avoid eth long")]
        if direction == "short" and _eth_btc_rising_sharply(s, cfg):
            return [Intent(symbol=s.symbol, action="noop",
                           reason="eth/btc rising sharply: avoid eth short")]

    # conviction scales size; hard floor on confidence before any risk capital.
    conviction = {"low": 0.5, "medium": 1.0, "high": 1.0}.get(ans.word(3), 1.0)
    threshold = floor + (0.10 if conviction >= 1.0 else 0.0)
    if not (ans.used and ans.confidence >= threshold):
        return [Intent(symbol=s.symbol, action="noop",
                       reason=f"confidence {ans.confidence:.2f} < {threshold:.2f}")]

    side = "buy" if direction == "long" else "sell"
    qty = _base_qty(s.symbol, cfg) * conviction  # base size; notional capped by risk engine
    return [Intent(symbol=s.symbol, action="buy" if side == "buy" else "sell", side=side,
                   price=0.0, qty=qty, reason=f"directional {direction} conviction {ans.word(3)}")]