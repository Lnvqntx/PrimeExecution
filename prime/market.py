"""Exchange metadata and quote parsing, with validation."""
from __future__ import annotations

from dataclasses import dataclass

from .config import QUOTE


@dataclass(frozen=True)
class PairMeta:
    pair: str
    coin: str
    amount_prec: int
    price_prec: int
    min_order: float


@dataclass(frozen=True)
class Quote:
    pair: str
    bid: float
    ask: float
    last: float
    change: float          # 24h change as a fraction (0.01 = +1%)
    turnover_usd: float    # 24h USD traded value

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        return (self.ask - self.bid) / self.mid * 1e4


def _f(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_exchange_info(resp: dict) -> dict[str, PairMeta]:
    """USD-quoted, tradable pairs only."""
    out: dict[str, PairMeta] = {}
    for pair, m in (resp.get("TradePairs") or {}).items():
        if m.get("Unit", QUOTE) != QUOTE or not m.get("CanTrade", True):
            continue
        out[pair] = PairMeta(
            pair=pair,
            coin=m.get("Coin") or pair.split("/")[0],
            amount_prec=int(m.get("AmountPrecision", 4)),
            price_prec=int(m.get("PricePrecision", 4)),
            min_order=_f(m.get("MiniOrder"), 1.0),
        )
    return out


def parse_ticker(resp: dict, metas: dict[str, PairMeta]) -> dict[str, Quote]:
    """Quotes for known pairs. Anything non-positive or crossed is dropped."""
    out: dict[str, Quote] = {}
    for pair, v in (resp.get("Data") or {}).items():
        if pair not in metas:
            continue
        bid, ask, last = _f(v.get("MaxBid")), _f(v.get("MinAsk")), _f(v.get("LastPrice"))
        if bid <= 0 or ask <= 0 or last <= 0 or ask < bid:
            continue
        out[pair] = Quote(
            pair=pair, bid=bid, ask=ask, last=last,
            change=_f(v.get("Change")), turnover_usd=_f(v.get("UnitTradeValue")),
        )
    return out
