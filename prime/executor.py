"""Order execution. Sends orders one at a time, validates every response, and
measures realized slippage against the quote used for sizing."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .client import ApiError, OrderUncertain
from .journal import Journal
from .planner import Order

log = logging.getLogger("prime")


@dataclass
class Fill:
    order: Order
    ok: bool
    filled_qty: float = 0.0
    avg_price: float = 0.0
    commission_pct: float | None = None
    role: str = ""
    status: str = ""
    slippage_bps: float | None = None
    error: str = ""


@dataclass
class ExecResult:
    fills: list[Fill]
    uncertain: bool = False     # an order's outcome is unknown; reconcile before trading again
    rejects: int = 0

    @property
    def traded(self) -> bool:
        return any(f.ok and f.filled_qty > 0 for f in self.fills)


class Executor:
    def __init__(self, client, journal: Journal, live: bool, reject_stop: int = 3):
        self.client = client
        self.journal = journal
        self.live = live
        self.reject_stop = reject_stop

    def run(self, orders: list[Order], tag: str) -> ExecResult:
        result = ExecResult(fills=[])
        streak = 0
        for o in orders:
            base = dict(tag=tag, pair=o.pair, side=o.side, qty=o.qty_str, notional=round(o.notional, 2),
                        ref_price=o.ref_price, reason=o.reason, live=self.live)
            if not self.live:
                log.info("[DRY] %s %s %s ~$%.0f (%s)", o.side, o.qty_str, o.pair, o.notional, o.reason)
                self.journal.write("orders", **base, outcome="dry")
                result.fills.append(Fill(o, ok=True, filled_qty=0.0, status="DRY"))
                continue
            try:
                resp = self.client.place_order(o.pair, o.side, o.qty_str, "MARKET")
            except OrderUncertain as e:
                log.error("ORDER UNCERTAIN %s %s: %s", o.side, o.pair, e)
                self.journal.write("orders", **base, outcome="uncertain", error=str(e))
                result.uncertain = True
                result.fills.append(Fill(o, ok=False, error=str(e)))
                break                     # stop: we must reconcile before sending more
            except ApiError as e:
                log.error("ORDER REJECTED %s %s %s: %s", o.side, o.qty_str, o.pair, e)
                self.journal.write("orders", **base, outcome="rejected", error=str(e))
                result.rejects += 1
                streak += 1
                result.fills.append(Fill(o, ok=False, error=str(e)))
                if streak >= self.reject_stop:
                    log.error("%d rejects in a row; stopping this batch", streak)
                    break
                continue
            streak = 0
            d = resp.get("OrderDetail") or {}
            filled = float(d.get("FilledQuantity", 0) or 0)
            avg = float(d.get("FilledAverPrice", 0) or 0)
            slip = None
            if avg > 0 and o.ref_price > 0:
                slip = ((avg / o.ref_price - 1.0) if o.side == "BUY" else (1.0 - avg / o.ref_price)) * 1e4
            fill = Fill(o, ok=True, filled_qty=filled, avg_price=avg,
                        commission_pct=d.get("CommissionPercent"), role=d.get("Role", ""),
                        status=d.get("Status", ""), slippage_bps=slip)
            log.info("FILLED %s %s %s @ %s status=%s fee=%s slip_bps=%s", o.side, o.qty_str, o.pair,
                     avg, fill.status, fill.commission_pct, None if slip is None else round(slip, 2))
            self.journal.write("orders", **base, outcome="filled", order_id=d.get("OrderID"), status=fill.status,
                               filled_qty=filled, avg_price=avg, role=fill.role,
                               commission_pct=fill.commission_pct,
                               commission_value=d.get("CommissionChargeValue"), slippage_bps=slip)
            result.fills.append(fill)
        return result
