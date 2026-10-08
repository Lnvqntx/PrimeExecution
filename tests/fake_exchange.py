"""In-memory stand-in for the Roostoo API, used by the tests. It speaks the same
interface as `RoostooClient` and applies realistic fills and fees."""
from __future__ import annotations

import random

from prime.client import ApiError, OrderUncertain

COINS = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "DOT", "LTC", "BNB", "TRX", "SUI", "NEAR", "APT",
         "ARB", "OP", "FIL", "ATOM", "UNI", "USDC"]


class FakeExchange:
    def __init__(self, usd=100_000.0, seed=1, fee=0.001):
        rnd = random.Random(seed)
        self.usd = usd
        self.coins: dict[str, float] = {}
        self.fee = fee
        self.time_ms = 1_790_000_000_000
        self.pairs = [f"{c}/USD" for c in COINS]
        self.px = {p: rnd.uniform(0.5, 500) for p in self.pairs}
        self.px["USDC/USD"] = 1.0
        self.spread = {p: rnd.uniform(1, 8) for p in self.pairs}           # bps
        self.volume = {p: rnd.uniform(1e6, 1e9) for p in self.pairs}
        self.volume["USDC/USD"] = 5e9                                        # biggest, but stable: must be skipped
        self.orders: list[dict] = []
        self.fail_next: list[str] = []         # "reject" or "uncertain"
        self.calls = 0

    # --------------------------------------------------------------- helpers
    def bid(self, p): return self.px[p] * (1 - self.spread[p] / 2e4)
    def ask(self, p): return self.px[p] * (1 + self.spread[p] / 2e4)
    def equity(self):
        return self.usd + sum(q * self.bid(f"{c}/USD") for c, q in self.coins.items())

    def move(self, factor: float):
        for p in self.pairs:
            if p != "USDC/USD":
                self.px[p] *= factor

    # --------------------------------------------------------------- client interface
    def server_time(self): return self.time_ms

    def exchange_info(self):
        return {"IsRunning": True, "TradePairs": {
            p: {"Coin": p.split("/")[0], "Unit": "USD", "CanTrade": True,
                "PricePrecision": 4, "AmountPrecision": 3, "MiniOrder": 1.0} for p in self.pairs}}

    def ticker(self, pair=None):
        self.calls += 1
        return {"Success": True, "Data": {
            p: {"MaxBid": self.bid(p), "MinAsk": self.ask(p), "LastPrice": self.px[p], "Change": 0.01,
                "CoinTradeValue": 1.0, "UnitTradeValue": self.volume[p]} for p in self.pairs}}

    def balance(self):
        self.calls += 1
        w = {"USD": {"Free": self.usd, "Lock": 0.0}}
        for c, q in self.coins.items():
            w[c] = {"Free": q, "Lock": 0.0}
        return {"Success": True, "Wallet": w}

    def place_order(self, pair, side, quantity, order_type="MARKET", price=None):
        self.calls += 1
        if self.fail_next:
            mode = self.fail_next.pop(0)
            if mode == "reject":
                raise ApiError("insufficient balance", {"Success": False})
            if mode == "uncertain-applied":     # order lands, but the reply is lost
                self._apply(pair, side, float(quantity))
                raise OrderUncertain("timeout after send")
            if mode == "uncertain":
                raise OrderUncertain("timeout")
        return self._apply(pair, side, float(quantity))

    def _apply(self, pair, side, qty):
        coin = pair.split("/")[0]
        if side == "BUY":
            px = self.ask(pair)
            cost = qty * px * (1 + self.fee)
            if cost > self.usd + 1e-9:
                raise ApiError("insufficient balance", {"Success": False})
            self.usd -= cost
            self.coins[coin] = self.coins.get(coin, 0.0) + qty
        else:
            px = self.bid(pair)
            if qty > self.coins.get(coin, 0.0) + 1e-9:
                raise ApiError("insufficient coin balance", {"Success": False})
            self.usd += qty * px * (1 - self.fee)
            self.coins[coin] -= qty
        self.orders.append({"pair": pair, "side": side, "qty": qty, "px": px})
        return {"Success": True, "OrderDetail": {
            "OrderID": len(self.orders), "Status": "FILLED", "Role": "TAKER", "FilledQuantity": qty,
            "FilledAverPrice": px, "CommissionPercent": self.fee, "CommissionChargeValue": qty * px * self.fee}}
