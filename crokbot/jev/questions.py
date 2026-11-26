"""Jev decision battery for the three desk bots.

Each bot sends its computed state as a text block and asks a small set of atomic
questions answered in order, one short answer per line. Policy/thresholds live
in `crokbot.policy`, NOT here — questions are pure judgment.
"""
from __future__ import annotations

from ..state import ComputedState, Inventory


def _render_state(s: ComputedState) -> str:
    base = (
        f"  SYMBOL: {s.symbol}\n"
        f"  mid_price: {s.mid_price}\n"
        f"  spread_bps: {s.spread_bps}\n"
        f"  order_imbalance: {s.order_imbalance}   (positive = more bid depth, negative = more ask depth)\n"
        f"  near_imbalance: {s.near_imbalance}\n"
        f"  realized_vol: {s.realized_vol}\n"
        f"  price_change_bps: {s.price_change_bps}   (vs reference {s.reference_price})\n"
        f"  bid_depth: {s.bid_depth}   ask_depth: {s.ask_depth}\n"
    )
    if s.extra and "eth_btc_ratio" in s.extra:
        base += (
            f"  eth_btc_ratio: {s.extra.get('eth_btc_ratio')}\n"
            f"  eth_btc_change_bps: {s.extra.get('eth_btc_change_bps')}\n"
            f"  eth_btc_regime: {s.extra.get('eth_btc_regime')}\n"
        )
    return base


_HEADER = (
    "You are Jev, a judgment model. Read the STATE below (numbers are already computed; "
    "do NOT do arithmetic). Answer the {n} numbered questions IN ORDER, with EXACTLY one "
    "short answer per question on its own line. Do not add any other text.\n\n"
)


def market_maker_prompt(s: ComputedState) -> str:
    return _HEADER.format(n=6) + (
        "STATE:\n" + _render_state(s) + "  JEV_STATE_END\n\n"
        "QUESTIONS (one short answer per line):\n"
        "1. Is the current spread wide, normal, or thin? Answer with ONE word: wide, normal, thick, or thin.\n"
        "2. Is near-term order book pressure biased to the bid side, ask side, or balanced? (bid, ask, balanced)\n"
        "3. Is realized volatility right now high, normal, or low? (high, normal, low)\n"
        "4. Given the state, should the market maker keep quoting or pull quotes? (quote, pull)\n"
        "5. Should quote depth be skewed toward the buy side, sell side, or neutral? (buy, sell, neutral)\n"
        "6. Your confidence in all of the above, one number 0.0 to 1.0.\n"
    )


def house_prompt(s: ComputedState, net_qty: float, target_qty: float) -> str:
    return _HEADER.format(n=5) + (
        "STATE:\n" + _render_state(s) +
        f"  net_inventory_qty: {net_qty}\n"
        f"  target_inventory_qty: {target_qty}\n"
        "  JEV_STATE_END\n\n"
        "QUESTIONS (one short answer per line):\n"
        "1. Is current inventory imbalanced long, short, or at target? (long, short, at_target)\n"
        "2. Should the desk rebalance toward target now? (yes, no)\n"
        "3. If rebalancing, should it trade at the market or quote patiently? (market, quote)\n"
        "4. Is the spread worth capturing right now? (yes, no)\n"
        "5. Your confidence in all of the above, one number 0.0 to 1.0.\n"
    )


def directional_prompt(s: ComputedState) -> str:
    return _HEADER.format(n=5) + (
        "STATE:\n" + _render_state(s) + "  JEV_STATE_END\n\n"
        "QUESTIONS (one short answer per line):\n"
        "1. Current regime: trending_up, trending_down, or ranging? (one word)\n"
        "2. Is there a clean directional edge right now? (yes, no)\n"
        "3. Favored direction, one word: long, short, flat.\n"
        "4. Conviction magnitude: low, medium, high (one word).\n"
        "5. Your confidence in all of the above, one number 0.0 to 1.0.\n"
    )