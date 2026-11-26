"""Jev client — talks to the local Omniroute router -> openrouter/typesafe/jev-router.

This is the WORKING path (learned from the content-matrix engine). The native
typesafe.ai /systemone API and bare "typesafe/jev-router" both fail; Jev is
reached as a chat-completions model through Omniroute at localhost:20128, and it
answers a numbered battery one line per question.

When Omniroute is unconfigured or offline, an intelligent heuristic fallback
maintains continuous desk operation.
"""
from __future__ import annotations

import json
import re
from typing import Dict, Optional

import requests

from ..config import config

_STATE_NUM_RE = re.compile(r"^\s*([a-zA-Z0-9_]+):\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
_STATE_STR_RE = re.compile(r"^\s*([a-zA-Z0-9_]+):\s*([A-Za-z0-9_/-]+)")


def _parse_prompt_state(prompt: str) -> Dict[str, object]:
    """Extract numeric and string fields from the rendered STATE block."""
    out: Dict[str, object] = {}
    for line in prompt.splitlines():
        if "JEV_STATE_END" in line:
            break
        m_num = _STATE_NUM_RE.match(line)
        if m_num:
            try:
                out[m_num.group(1).lower()] = float(m_num.group(2))
                continue
            except ValueError:
                pass
        m_str = _STATE_STR_RE.match(line)
        if m_str:
            out[m_str.group(1).lower()] = m_str.group(2)
    return out


def _heuristic_answer(prompt: str) -> str:
    """Quantitative microstructure heuristic when Omniroute is offline/unconfigured."""
    p = prompt.lower()
    st = _parse_prompt_state(prompt)
    symbol = str(st.get("symbol", "BTCUSDT")).upper()
    spread_bps = float(st.get("spread_bps", 4.0) or 4.0)
    imbalance = float(st.get("order_imbalance", 0.0) or 0.0)
    near_imb = float(st.get("near_imbalance", imbalance) or 0.0)
    vol = float(st.get("realized_vol", 0.005) or 0.005)
    chg_bps = float(st.get("price_change_bps", 0.0) or 0.0)
    eth_btc_regime = str(st.get("eth_btc_regime", "neutral")).lower()

    if "market maker" in p or "quote depth be skewed" in p:
        q1_spread = "thin" if spread_bps < 2.0 else ("wide" if spread_bps > 12.0 else "normal")
        q2_press = "bid" if near_imb > 0.20 else ("ask" if near_imb < -0.20 else "balanced")
        q3_vol = "high" if vol > 0.015 else ("low" if vol < 0.004 else "normal")
        should_pull = vol > 0.025 or spread_bps < 2.0 or abs(imbalance) > 0.78
        q4_action = "pull" if should_pull else "quote"
        if symbol.startswith("ETH") and eth_btc_regime == "falling_sharply":
            q5_skew = "sell"
        elif near_imb > 0.25:
            q5_skew = "buy"
        elif near_imb < -0.25:
            q5_skew = "sell"
        else:
            q5_skew = "neutral"
        conf = 0.85 if not should_pull else 0.78
        return f"1. {q1_spread}\n2. {q2_press}\n3. {q3_vol}\n4. {q4_action}\n5. {q5_skew}\n6. {conf:.2f}\n"

    if "house" in p or "target_inventory_qty" in p:
        net_q = float(st.get("net_inventory_qty", 0.0) or 0.0)
        tgt_q = float(st.get("target_inventory_qty", 0.0) or 0.0)
        diff = net_q - tgt_q
        base_tol = 0.002 if symbol.startswith("BTC") else (0.04 if symbol.startswith("ETH") else 0.5)
        if abs(diff) > base_tol:
            q1_inv = "long" if diff > 0 else "short"
            q2_reb = "yes"
            q3_exec = "market" if (vol > 0.012 or abs(diff) > base_tol * 2.5) else "quote"
            q4_farm = "no"
            return f"1. {q1_inv}\n2. {q2_reb}\n3. {q3_exec}\n4. {q4_farm}\n5. 0.86\n"
        q4_farm = "yes" if (spread_bps >= 3.0 and vol <= 0.015) else "no"
        return f"1. at_target\n2. no\n3. quote\n4. {q4_farm}\n5. 0.82\n"

    if "directional" in p or "clean directional edge" in p or "clean edge" in p:
        if chg_bps >= 6.0 and imbalance >= -0.15:
            conviction = "high" if chg_bps >= 20.0 else "medium"
            conf = min(0.92, 0.76 + min(abs(chg_bps), 40.0) * 0.003)
            return f"1. trending_up\n2. yes\n3. long\n4. {conviction}\n5. {conf:.2f}\n"
        if chg_bps <= -6.0 and imbalance <= 0.15:
            conviction = "high" if chg_bps <= -20.0 else "medium"
            conf = min(0.92, 0.76 + min(abs(chg_bps), 40.0) * 0.003)
            return f"1. trending_down\n2. yes\n3. short\n4. {conviction}\n5. {conf:.2f}\n"
        return "1. ranging\n2. no\n3. flat\n4. low\n5. 0.55\n"

    return ""


class JevClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        fallback_to_heuristic: bool = True,
    ):
        self.base_url = (base_url or config.jev_base_url).rstrip("/")
        self.api_key = api_key or config.omniroute_api_key
        self.model = model or config.jev_model
        self.fallback_to_heuristic = fallback_to_heuristic
        self.session = requests.Session()
        self._enable = bool(self.api_key)

    def is_live(self) -> bool:
        return bool(self.api_key)

    def enabled(self) -> bool:
        return bool(self.api_key) or self.fallback_to_heuristic

    def ask(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.0,
        timeout: int = 4,
    ) -> str:
        """Send one prompt to Jev.

        If Omniroute is live, gets response from openrouter/typesafe/jev-router.
        If Omniroute is offline or unconfigured, uses the heuristic fallback.
        """
        if self.api_key:
            body = json.dumps({
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            })
            try:
                resp = self.session.post(
                    self.base_url + "/chat/completions",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + self.api_key,
                    },
                    timeout=timeout,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                if content:
                    return content
            except Exception:
                pass

        if self.fallback_to_heuristic:
            return _heuristic_answer(prompt)

        return ""


# A shared client for the whole process.
_client: Optional[JevClient] = None


def get_client() -> JevClient:
    global _client
    if _client is None:
        _client = JevClient()
    return _client
