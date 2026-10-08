"""Roostoo REST client.

Signing follows the official docs exactly: parameters sorted by key and joined as
raw `k=v&k=v` (NO url-encoding), HMAC-SHA256 with the secret key, signature sent in
`MSG-SIGNATURE`, key in `RST-API-KEY`. POST bodies are sent as that same raw string.

Safety rules baked in:
  * every call is throttled (`min_gap` seconds between calls)
  * GET requests retry on network errors; POSTs NEVER retry (an order may have landed)
  * a POST whose outcome is unknown raises `OrderUncertain`; callers must reconcile
  * Roostoo answers HTTP 200 even for failures, so `Success` is always checked
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import requests

from .config import BASE_URL


class ApiError(Exception):
    """The exchange answered, and the answer was a failure."""

    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


class OrderUncertain(Exception):
    """A POST may or may not have been applied (timeout, connection reset)."""


class RoostooClient:
    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        base_url: str = BASE_URL,
        min_gap: float = 0.25,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self.min_gap = min_gap
        self.timeout = timeout
        self.session = session or requests.Session()
        self._last_call = 0.0
        self.calls = 0

    # ------------------------------------------------------------- plumbing
    @staticmethod
    def timestamp() -> str:
        return str(int(time.time() * 1000))

    def _throttle(self) -> None:
        wait = self.min_gap - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        self.calls += 1

    def sign(self, params: dict[str, Any]) -> tuple[str, dict[str, str]]:
        """Return (total_params, headers) for a signed request."""
        total = "&".join(f"{k}={params[k]}" for k in sorted(params))
        sig = hmac.new(self.secret_key.encode(), total.encode(), hashlib.sha256).hexdigest()
        return total, {"RST-API-KEY": self.api_key, "MSG-SIGNATURE": sig}

    def _get(self, path: str, params: dict | None = None, signed: bool = False,
             timestamp: bool = False, retries: int = 2) -> dict:
        base = dict(params or {})
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            self._throttle()
            p = dict(base)
            if signed or timestamp:
                p["timestamp"] = self.timestamp()  # fresh on every attempt
            headers: dict[str, str] = {}
            if signed:
                total, headers = self.sign(p)
            else:
                total = "&".join(f"{k}={p[k]}" for k in p)
            url = f"{self.base_url}{path}" + (f"?{total}" if total else "")
            try:
                r = self.session.get(url, headers=headers, timeout=self.timeout)
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError) as e:
                last_exc = e
                time.sleep(min(2.0 * (attempt + 1), 5.0))
        raise ApiError(f"GET {path} failed after {retries + 1} attempts: {last_exc}")

    def _post(self, path: str, params: dict) -> dict:
        params = dict(params)
        params["timestamp"] = self.timestamp()
        total, headers = self.sign(params)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        self._throttle()
        try:
            r = self.session.post(f"{self.base_url}{path}", data=total, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise OrderUncertain(f"POST {path} outcome unknown: {e}") from e
        if r.status_code >= 500:
            raise OrderUncertain(f"POST {path} returned HTTP {r.status_code}; outcome unknown")
        try:
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            raise ApiError(f"POST {path} failed: {e}") from e

    @staticmethod
    def ok(resp: dict, what: str) -> dict:
        if not resp.get("Success", False):
            raise ApiError(f"{what} rejected: {resp.get('ErrMsg') or resp}", resp)
        return resp

    # ------------------------------------------------------------- public
    def server_time(self) -> int:
        return int(self._get("/v3/serverTime")["ServerTime"])

    def exchange_info(self) -> dict:
        return self._get("/v3/exchangeInfo")

    def ticker(self, pair: str | None = None) -> dict:
        params = {"pair": pair} if pair else {}
        return self.ok(self._get("/v3/ticker", params, timestamp=True), "ticker")

    # ------------------------------------------------------------- account
    def balance(self) -> dict:
        return self.ok(self._get("/v3/balance", signed=True), "balance")

    def pending_count(self) -> dict:
        # Success=false just means "no pending orders", so no `ok` check here.
        return self._get("/v3/pending_count", signed=True)

    # ------------------------------------------------------------- spot orders
    def place_order(self, pair: str, side: str, quantity: str, order_type: str = "MARKET", price: str | None = None) -> dict:
        body = {"pair": pair, "side": side.upper(), "type": order_type.upper(), "quantity": str(quantity)}
        if body["type"] == "LIMIT":
            if price is None:
                raise ValueError("LIMIT orders require a price")
            body["price"] = str(price)
        return self.ok(self._post("/v3/place_order", body), f"{side} {quantity} {pair}")

    def query_order(self, order_id: str | None = None, pair: str | None = None, pending_only: bool | None = None) -> dict:
        body: dict[str, str] = {}
        if order_id is not None:
            body["order_id"] = str(order_id)
        elif pair is not None:
            body["pair"] = pair
            if pending_only is not None:
                body["pending_only"] = "TRUE" if pending_only else "FALSE"
        return self._post("/v3/query_order", body)

    def cancel_order(self, order_id: str | None = None, pair: str | None = None) -> dict:
        if order_id is not None and pair is not None:
            raise ValueError("Pass either order_id or pair, not both")
        body: dict[str, str] = {}
        if order_id is not None:
            body["order_id"] = str(order_id)
        elif pair is not None:
            body["pair"] = pair
        return self._post("/v3/cancel_order", body)

    # ------------------------------------------------------------- shorts (/v6)
    # Phase 0 does not use these; they are here so later phases do not need a new client.
    def short_open(self, pair: str, collateral: float, price: float | None = None) -> dict:
        body = {"pair": pair, "collateral": str(collateral)}
        if price is not None:
            body["order_type"] = "LIMIT"
            body["price"] = str(price)
        return self.ok(self._post("/v6/short_open", body), f"short_open {pair}")

    def short_close(self, pair: str, close_qty: float | None = None, close_pct: float | None = None) -> dict:
        body = {"pair": pair}
        if close_qty is not None:
            body["close_qty"] = str(close_qty)
        elif close_pct is not None:
            body["close_pct"] = str(close_pct)
        return self.ok(self._post("/v6/short_close", body), f"short_close {pair}")

    def short_positions(self) -> dict:
        return self.ok(self._get("/v6/short_positions", signed=True), "short_positions")
