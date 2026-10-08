from decimal import Decimal

import pytest

from prime.config import Params
from prime.market import PairMeta, Quote
from prime.planner import floor_qty, plan_orders
from prime.portfolio import Snapshot
from prime.risk import RiskEngine
from prime.state import State


def meta(pair, prec=2, min_order=1.0):
    return PairMeta(pair, pair.split("/")[0], prec, 4, min_order)


def quote(pair, px=10.0, spread_bps=2.0, turnover=1e6):
    h = px * spread_bps / 2e4
    return Quote(pair, px - h, px + h, px, 0.0, turnover)


def test_floor_qty_never_rounds_up():
    assert floor_qty(1.239999, 2) == Decimal("1.23")
    assert floor_qty(0.000019, 5) == Decimal("0.00001")


def test_buy_sized_to_target_and_rounded_down():
    p, m, q = Params(), {"A/USD": meta("A/USD", 2)}, {"A/USD": quote("A/USD", 10.0)}
    snap = Snapshot(usd_free=100_000, usd_total=100_000, equity=100_000)
    orders = plan_orders({"A/USD": 0.03}, snap, q, m, p, min_notional=50, band_usd=100, reason="t")
    assert len(orders) == 1 and orders[0].side == "BUY"
    assert orders[0].notional == pytest.approx(3000, rel=0.01)
    assert Decimal(orders[0].qty_str).as_tuple().exponent >= -2


def test_inside_band_no_trade_but_exit_always_sells():
    p, m, q = Params(), {"A/USD": meta("A/USD")}, {"A/USD": quote("A/USD", 10.0)}
    held = 300.0                                         # ~$3000 at the bid, target is $3000
    snap = Snapshot(usd_free=97_000, usd_total=97_000, holdings={"A/USD": held},
                    values={"A/USD": held * q["A/USD"].bid}, equity=100_000)
    assert plan_orders({"A/USD": 0.03}, snap, q, m, p, min_notional=50, band_usd=100, reason="t") == []
    exit_orders = plan_orders({}, snap, q, m, p, min_notional=50, band_usd=100, reason="t")
    assert len(exit_orders) == 1 and exit_orders[0].side == "SELL" and exit_orders[0].qty == pytest.approx(held)


def test_sells_come_before_buys_and_buys_are_capped_to_cash():
    p = Params()
    m = {"A/USD": meta("A/USD"), "B/USD": meta("B/USD")}
    q = {"A/USD": quote("A/USD"), "B/USD": quote("B/USD")}
    snap = Snapshot(usd_free=100, usd_total=100, holdings={"A/USD": 1000.0},
                    values={"A/USD": 1000 * q["A/USD"].bid}, equity=10_000)
    orders = plan_orders({"B/USD": 0.05}, snap, q, m, p, min_notional=50, band_usd=100, reason="t")
    assert [o.side for o in orders] == ["SELL", "BUY"]
    spend = sum(o.notional for o in orders if o.side == "BUY")
    assert spend <= (100 + orders[0].notional * 0.998) * p.cash_buffer + 1e-6


def test_risk_ladder_levels_and_breaker_cooloff():
    p = Params()
    r, s = RiskEngine(p), State()
    assert r.update(100, 0, s).scale == 1.0
    assert r.update(95.5, 1, s).scale == 0.5
    d = r.update(91, 2, s)
    assert d.flatten and s.breaker_until > 2
    assert r.update(120, 3, s).flatten                     # even a bounce stays flat during cool-off
    after = r.update(100, s.breaker_until + 1, s)
    assert not after.flatten and s.peak_equity == 100      # peak resets after the cool-off


def test_clamp_caps_names_and_gross():
    p = Params()
    r = RiskEngine(p)
    out = r.clamp({"A": 0.5, "B": 0.5}, 1.0)
    assert all(w <= p.max_weight + 1e-12 for w in out.values()) and sum(out.values()) <= p.gross + 1e-12
    half = r.clamp({f"c{i}": 0.03 for i in range(10)}, 0.5)
    assert sum(half.values()) == pytest.approx(0.15)
    assert r.clamp({"A": 0.03}, 0.0) == {}
