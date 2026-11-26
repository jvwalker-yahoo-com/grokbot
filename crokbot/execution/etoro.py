"""EToroBroker — eToro Public API v1 broker implementation.

Follows docs/etoro/{api-conventions,account-snapshot,building-client,id-resolution}.md:
  - Header auth: EITHER Authorization: Bearer OR x-api-key + x-user-key (never both),
    plus a fresh UUIDv4 x-request-id per request.
  - Instrument ID resolution: static KNOWN_INSTRUMENTS map + live /market-data/search cache.
  - Account snapshot: /trading/info/{env}/pnl (`clientPortfolio`) for Available Cash & positions.
  - Execution safety: at-most-once POST discipline (never resend on timeout/5xx; backoff only on 429),
    explicit Leverage: 1, and positive SL/TP bounds on limit orders.
"""
from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

import requests

from .broker import Broker, Order

KNOWN_INSTRUMENTS: Dict[str, str] = {
    "BTC": "100000",
    "BTCUSD": "100000",
    "BTCUSDT": "100000",
    "BTCGBP": "100000",
    "BTCEUR": "100000",
    "ETH": "100001",
    "ETHUSD": "100001",
    "ETHUSDT": "100001",
    "ETHGBP": "100001",
    "ETHEUR": "100001",
}


class EToroBroker(Broker):
    def __init__(
        self,
        api_key: str = "",
        user_key: str = "",
        bearer_token: str = "",
        env: str = "real",
        base_url: str = "https://public-api.etoro.com/api/v1",
    ):
        self.api_key = api_key.strip()
        self.user_key = user_key.strip()
        self.bearer_token = bearer_token.strip()
        self.env = env.lower() if env.lower() in ("real", "demo") else "real"
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._instrument_cache: Dict[str, str] = dict(KNOWN_INSTRUMENTS)
        self._ready = bool(self.bearer_token or (self.api_key and self.user_key))

    def ready(self) -> bool:
        return self._ready

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "x-request-id": str(uuid.uuid4()),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Never mix Bearer and x-api-key / x-user-key headers
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
            return headers

        ak, uk = self.api_key, self.user_key
        if ak.startswith("ey") and not uk.startswith("ey"):
            ak, uk = uk, ak
        headers["x-api-key"] = ak
        headers["x-user-key"] = uk
        return headers

    def resolve_instrument_id(self, symbol: str) -> str:
        """Resolve ticker symbol (e.g. BTCUSDT, ETHUSDT) to eToro numeric instrumentID."""
        clean = symbol.strip().upper().replace("/", "").replace("-", "")
        if clean.isdigit():
            return clean
        if clean in self._instrument_cache:
            return self._instrument_cache[clean]

        if not self._ready:
            return clean

        try:
            resp = self.session.get(
                f"{self.base_url}/market-data/search?internalSymbolFull={clean}",
                headers=self._headers(),
                timeout=8,
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                for item in items:
                    if str(item.get("internalSymbolFull", "")).upper() == clean:
                        resolved = str(item.get("instrumentId", item.get("instrumentID", "")))
                        if resolved:
                            self._instrument_cache[clean] = resolved
                            return resolved
        except Exception:
            pass
        return clean

    def place(self, order: Order) -> Order:
        if not self._ready:
            order.status = "rejected"
            order.reason = "eToro credentials not configured"
            return order

        instrument_id = self.resolve_instrument_id(order.symbol)
        if not instrument_id.isdigit():
            order.status = "rejected"
            order.reason = f"unresolved eToro instrument ID for {order.symbol}"
            return order

        side_mapped = "Buy" if order.is_buy else "Sell"
        eff_amount = order.effective_notional()
        if order.order_type == "market" and eff_amount <= 0:
            order.status = "rejected"
            order.reason = "market order requires positive notional/reference price"
            return order

        if order.order_type == "market":
            path = f"trading/execution/{self.env}/market-open-orders/by-amount"
            payload: Dict[str, object] = {
                "InstrumentID": int(instrument_id),
                "IsBuy": order.is_buy,
                "Leverage": 1,
                "Amount": round(eff_amount, 2),
            }
        else:
            path = f"trading/execution/{self.env}/limit-orders"
            sl_rate = round(order.price * 0.5, 4) if order.is_buy else round(order.price * 1.5, 4)
            tp_rate = round(order.price * 2.0, 4) if order.is_buy else round(max(0.0001, order.price * 0.5), 4)
            payload = {
                "InstrumentID": int(instrument_id),
                "IsBuy": order.is_buy,
                "Leverage": 1,
                "Units": order.qty,
                "Rate": order.price,
                "StopLossRate": max(0.0001, sl_rate),
                "TakeProfitRate": max(0.0001, tp_rate),
            }

        # At-most-once POST discipline: retry ONLY on explicit 429 rate-limit responses
        backoffs = (15, 30)
        for attempt in range(len(backoffs) + 1):
            try:
                resp = self.session.post(
                    f"{self.base_url}/{path}",
                    json=payload,
                    headers=self._headers(),
                    timeout=10,
                )
            except Exception as e:
                # Ambiguous network/timeout outcome: NEVER resend POST (prevents duplicate positions)
                order.status = "rejected"
                order.reason = f"ambiguous network error (do not auto-retry): {e}"
                return order

            if resp.status_code in (200, 201):
                data = resp.json() if resp.text else {}
                order.order_id = str(
                    data.get("orderID", data.get("orderId", data.get("positionID", data.get("positionId", ""))))
                )
                order.status = "new" if order.order_type == "limit" else "filled"
                return order

            if resp.status_code == 429 and attempt < len(backoffs):
                time.sleep(backoffs[attempt])
                continue

            order.status = "rejected"
            order.reason = f"eToro API error {resp.status_code}: {resp.text[:200]}"
            return order

        return order

    def cancel(self, order_id: str) -> bool:
        if not self._ready:
            return False
        try:
            resp = self.session.delete(
                f"{self.base_url}/trading/execution/{self.env}/limit-orders/{order_id}",
                headers=self._headers(),
                timeout=10,
            )
            return resp.status_code in (200, 204)
        except Exception:
            return False

    def _fetch_portfolio(self) -> Optional[Dict]:
        if not self._ready:
            return None
        for url in (
            f"{self.base_url}/trading/info/{self.env}/pnl",
            f"{self.base_url}/trading/info/portfolio",
        ):
            try:
                resp = self.session.get(url, headers=self._headers(), timeout=10)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue
        return None

    def positions(self) -> Dict[str, float]:
        data = self._fetch_portfolio()
        if not data:
            return {}
        positions: Dict[str, float] = {}
        pf = data.get("clientPortfolio", {})
        # Use clientPortfolio.positions[] only (avoid double-counting mirrors[].positions[])
        for pos in pf.get("positions", []):
            symbol = str(pos.get("instrumentID", pos.get("instrumentId", "")))
            qty = float(pos.get("units", pos.get("amount", 0.0)))
            if pos.get("isBuy") is False or pos.get("action") == "Sell":
                qty = -qty
            positions[symbol] = positions.get(symbol, 0.0) + qty
        return positions

    def balance(self) -> float:
        """Compute Available Cash per eToro Account Snapshot §1 formula."""
        if not self._ready:
            return 0.0
        data = self._fetch_portfolio()
        if data and "clientPortfolio" in data:
            pf = data["clientPortfolio"]
            credit = float(pf.get("credit", 0.0) or 0.0)
            pending_open = sum(
                float(o.get("amount", 0.0) or 0.0)
                for o in pf.get("ordersForOpen", [])
                if int(o.get("mirrorID", o.get("mirrorId", 0)) or 0) == 0
            )
            pending_orders = sum(float(o.get("amount", 0.0) or 0.0) for o in pf.get("orders", []))
            return max(0.0, credit - pending_open - pending_orders)

        try:
            resp = self.session.get(
                f"{self.base_url}/balances?expand=equityDetails",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                b = resp.json()
                if isinstance(b, dict):
                    return float(b.get("availableBalance", b.get("balance", b.get("cash", 0.0))))
        except Exception:
            pass
        return 0.0

    def open_orders(self) -> List[Order]:
        data = self._fetch_portfolio()
        if not data:
            return []
        pf = data.get("clientPortfolio", {})
        orders: List[Order] = []
        for o in pf.get("ordersForOpen", []) + pf.get("orders", []):
            is_buy = o.get("isBuy") if "isBuy" in o else (o.get("action") == "Buy")
            orders.append(
                Order(
                    symbol=str(o.get("instrumentID", o.get("instrumentId", ""))),
                    side="buy" if is_buy else "sell",
                    qty=float(o.get("units", o.get("amount", 0.0))),
                    price=float(o.get("rate", o.get("openRate", 0.0))),
                    order_type="limit",
                    order_id=str(o.get("orderID", o.get("orderId", ""))),
                    status="new",
                )
            )
        return orders
