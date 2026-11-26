"""The three desk bots and the base they share."""
from __future__ import annotations

from typing import List, Optional

from ..config import Config
from ..execution.broker import Intent
from ..jev.client import JevClient, get_client
from ..jev.parser import as_float, extract_lines
from ..jev.questions import directional_prompt, house_prompt, market_maker_prompt
from ..policy.compose import (
    JevAnswers,
    directional_policy,
    house_policy,
    market_maker_policy,
)
from ..state import ComputedState


class Bot:
    """A seat at the desk. owns one Jev battery -> one policy."""

    name = "bot"
    enabled = True

    def __init__(self, cfg: Config, client: Optional[JevClient] = None):
        self.cfg = cfg
        self.client = client or get_client()

    def _ask(self, prompt: str, n: int) -> JevAnswers:
        """Call Jev, parse `n` answers, confidence = the last line."""
        raw = self.client.ask(prompt)
        if not raw:
            return JevAnswers.none()
        lines = extract_lines(raw)
        if len(lines) < n:
            return JevAnswers.none()
        lines = lines[:n]
        confidence = as_float(lines[-1], default=0.0)
        answers = lines[:-1] if n > 1 else []
        return JevAnswers(raw=answers, confidence=confidence, used=True)

    def step(self, s: ComputedState, **ctx) -> List[Intent]:
        raise NotImplementedError


class MarketMakerBot(Bot):
    """Bot 1: quotes both sides one tick inside the touch (post-only)."""

    name = "market_maker"

    def step(self, s: ComputedState, **ctx) -> List[Intent]:
        ans = self._ask(market_maker_prompt(s), 6)
        return market_maker_policy(ans, s, self.cfg)


class HouseBot(Bot):
    """Bot 2: the house. Direction-agnostic; drives inventory toward target."""

    name = "house"

    def step(self, s: ComputedState, net_qty: float = 0.0, target_qty: float = 0.0,
             **ctx) -> List[Intent]:
        ans = self._ask(house_prompt(s, net_qty, target_qty), 5)
        return house_policy(ans, s, net_qty, target_qty, self.cfg)


class DirectionalBot(Bot):
    """Bot 3: takes a directional bet only on a clean, confident edge."""

    name = "directional"

    def step(self, s: ComputedState, **ctx) -> List[Intent]:
        ans = self._ask(directional_prompt(s), 5)
        return directional_policy(ans, s, self.cfg)