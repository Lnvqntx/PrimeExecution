"""Portfolio snapshot built from the exchange's own balance, never from local memory."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import QUOTE, Params
from .market import PairMeta, Quote


@dataclass
class Snapshot:
    usd_free: float
    usd_total: float
    holdings: dict[str, float] = field(default_factory=dict)   # pair -> quantity (free + locked)
    values: dict[str, float] = field(default_factory=dict)     # pair -> USD value at the bid
    equity: float = 0.0
    unknown_coins: list[str] = field(default_factory=list)

    @property
    def invested(self) -> float:
        return sum(self.values.values())


def build_snapshot(balance: dict, metas: dict[str, PairMeta], quotes: dict[str, Quote], params: Params) -> Snapshot:
    wallet = balance.get("Wallet") or balance.get("SpotWallet") or {}
    coin_to_pair = {m.coin: p for p, m in metas.items()}

    def total(entry) -> float:
        if isinstance(entry, dict):
            return float(entry.get("Free", 0) or 0) + float(entry.get("Lock", 0) or 0)
        return float(entry or 0)

    usd = wallet.get(QUOTE, {})
    usd_free = float(usd.get("Free", 0) or 0) if isinstance(usd, dict) else float(usd or 0)
    snap = Snapshot(usd_free=usd_free, usd_total=total(usd))

    for coin, entry in wallet.items():
        if coin == QUOTE:
            continue
        qty = total(entry)
        if qty <= 0:
            continue
        pair = coin_to_pair.get(coin)
        quote = quotes.get(pair) if pair else None
        if quote is None:
            snap.unknown_coins.append(coin)
            continue
        value = qty * quote.bid
        if value < params.dust_usd:
            continue
        snap.holdings[pair] = qty
        snap.values[pair] = value

    snap.equity = snap.usd_total + snap.invested
    return snap
