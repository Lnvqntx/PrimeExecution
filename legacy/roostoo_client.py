from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests


class RoostooClient:
    BASE_URL = "https://mock-api.roostoo.com"

    def __init__(self, api_key: str = "", secret_key: str = ""):
        self.api_key = api_key
        self.secret_key = secret_key
        self.session = requests.Session()

    def _timestamp(self) -> str:
        return str(int(time.time() * 1000))

    def server_time(self):
        response = self.session.get(
            f"{self.BASE_URL}/v3/serverTime", timeout=10
        )
        response.raise_for_status()
        return response.json()

    def exchange_info(self):
        response = self.session.get(
            f"{self.BASE_URL}/v3/exchangeInfo", timeout=10
        )
        response.raise_for_status()
        return response.json()

    def ticker(self, pair: str | None = None):
        params = {"timestamp": self._timestamp()}
        if pair is not None:
            params["pair"] = pair

        response = self.session.get(
            f"{self.BASE_URL}/v3/ticker",
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def _signed_headers(self, params: dict):
        payload = urlencode(sorted(params.items()))
        signature = hmac.new(
            self.secret_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {
            "RST-API-KEY": self.api_key,
            "MSG-SIGNATURE": signature,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def signed_get(self, path: str, params: dict | None = None):
        params = dict(params or {})
        params["timestamp"] = self._timestamp()
        headers = self._signed_headers(params)

        response = self.session.get(
            f"{self.BASE_URL}{path}",
            params=params,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def signed_post(self, path: str, params: dict | None = None):
        params = dict(params or {})
        params["timestamp"] = self._timestamp()

        encoded = urlencode(sorted(params.items()))
        headers = self._signed_headers(params)

        response = self.session.post(
            f"{self.BASE_URL}{path}",
            data=encoded,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def balance(self):
        return self.signed_get("/v3/balance")

    def pending_count(self):
        return self.signed_get("/v3/pending_count")

    def place_order(
        self,
        pair: str,
        side: str,
        quantity: str,
        order_type: str = "MARKET",
        price: str | None = None,
    ):
        payload = {
            "pair": pair,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": str(quantity),
        }

        if payload["type"] == "LIMIT":
            if price is None:
                raise ValueError("LIMIT orders require price")
            payload["price"] = str(price)

        return self.signed_post("/v3/place_order", payload)

    def query_order(
        self,
        order_id: str | None = None,
        pair: str | None = None,
        pending_only: bool | None = None,
    ):
        if order_id is not None:
            params = {"order_id": str(order_id)}
        elif pair is not None:
            params = {"pair": pair}
            if pending_only is not None:
                params["pending_only"] = (
                    "TRUE" if pending_only else "FALSE"
                )
        else:
            params = {}

        return self.signed_post("/v3/query_order", params)

    def cancel_order(
        self,
        order_id: str | None = None,
        pair: str | None = None,
    ):
        if order_id is not None and pair is not None:
            raise ValueError("Pass either order_id or pair, not both")

        params = {}
        if order_id is not None:
            params["order_id"] = str(order_id)
        elif pair is not None:
            params["pair"] = pair

        return self.signed_post("/v3/cancel_order", params)
