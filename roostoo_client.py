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
        response = self.session.get(f"{self.BASE_URL}/v3/serverTime", timeout=10)
        response.raise_for_status()
        return response.json()

    def exchange_info(self):
        response = self.session.get(f"{self.BASE_URL}/v3/exchangeInfo", timeout=10)
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
