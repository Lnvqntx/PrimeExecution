"""Turn target weights into a concrete, exchange-valid order list."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from .config import Params
from .market import PairMeta, Quote
from .portfolio import Snapshot


@dataclass(frozen=True)
class Order:
    pair: str
    side: str            # "BUY" or "SELL"
    qty: float
    qty_str: str
    notional: float      # approximate USD value
    ref_price: float     # quote used for sizing and for slippage measurement
    reason: str


def floor_qty(qty: float, prec: int) -> Decimal:
    return Decimal(repr(qty)).quantize(Decimal(1).scaleb(-prec), rounding=ROUND_DOWN)


def plan_orders(
    targets: dict[str, float],
    snap: Snapshot,
    quotes: dict[str, Quote],
    metas: dict[str, PairMeta],
    params: Params,
    *,
    min_notional: float,
    band_usd: float,
    reason: str,
    band_frac: float | None = None,
) -> list[Order]:
    """Sells first, then buys. Small drifts inside the no-trade band are left alone,
    except full exits (a coin that left the target set is always sold)."""
    equity = snap.equity
    frac = params.band_frac if band_frac is None else band_frac
    band = max(band_usd, frac * equity)
    sells: list[Order] = []
    buys: list[Order] = []

    for pair in sorted(set(targets) | set(snap.holdings)):
        quote, meta = quotes.get(pair), metas.get(pair)
        if quote is None or meta is None:
            continue
        held_qty = snap.holdings.get(pair, 0.0)
        target_w = targets.get(pair, 0.0)
        current_value = held_qty * quote.bid
        delta = target_w * equity - current_value

        if target_w <= 0 and held_qty > 0:                     # full exit
            qty = floor_qty(held_qty, meta.amount_prec)
            notional = float(qty) * quote.bid
            if qty > 0 and notional >= max(meta.min_order, 1.0):
                sells.append(Order(pair, "SELL", float(qty), format(qty, "f"), notional, quote.bid, f"exit: {reason}"))
            continue

        if abs(delta) < band:
            continue
        if delta < 0:                                          # trim
            qty = floor_qty(min(held_qty, -delta / quote.bid), meta.amount_prec)
            notional = float(qty) * quote.bid
            if qty > 0 and notional >= max(min_notional, meta.min_order):
                sells.append(Order(pair, "SELL", float(qty), format(qty, "f"), notional, quote.bid, f"trim: {reason}"))
        else:                                                  # add
            qty = floor_qty(delta / quote.ask, meta.amount_prec)
            notional = float(qty) * quote.ask
            if qty > 0 and notional >= max(min_notional, meta.min_order):
                buys.append(Order(pair, "BUY", float(qty), format(qty, "f"), notional, quote.ask, f"add: {reason}"))

    # Never spend more than the cash we will actually have after the sells settle.
    available = (snap.usd_free + sum(o.notional for o in sells) * 0.998) * params.cash_buffer
    need = sum(o.notional for o in buys)
    if need > available and need > 0:
        scale = available / need
        scaled: list[Order] = []
        for o in buys:
            q = floor_qty(o.qty * scale, metas[o.pair].amount_prec)
            n = float(q) * o.ref_price
            if q > 0 and n >= max(min_notional, metas[o.pair].min_order):
                scaled.append(Order(o.pair, "BUY", float(q), format(q, "f"), n, o.ref_price, o.reason + " (scaled to cash)"))
        buys = scaled
    return sells + buys
