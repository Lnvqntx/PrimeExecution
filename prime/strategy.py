"""Strategies are pure functions: market state in, target weights out.

Phase 0 is a deliberately simple, declared baseline: hold an equal-weight basket of
the most liquid, tightest-spread coins at a fixed gross exposure. It makes no claim
of alpha. It exists to (a) start the active-day count, (b) produce a smooth, low
drawdown equity curve, and (c) measure real fees and slippage before any signal is
trusted with real exposure.
"""
from __future__ import annotations

from typing import Protocol

from .config import STABLE_COINS, Params
from .market import PairMeta, Quote


class Strategy(Protocol):
    name: str

    def targets(self, quotes: dict[str, Quote], metas: dict[str, PairMeta], held: set[str], params: Params) -> dict[str, float]:
        """Return {pair: target weight as a fraction of equity}. Missing pairs mean 0."""


def select_universe(quotes: dict[str, Quote], metas: dict[str, PairMeta], held: set[str], params: Params) -> list[str]:
    """Top coins by 24h USD turnover with a tight spread. Held coins get hysteresis."""
    eligible = [
        q for p, q in quotes.items()
        if metas[p].coin not in STABLE_COINS and q.spread_bps <= params.max_spread_bps and q.turnover_usd > 0
    ]
    eligible.sort(key=lambda q: q.turnover_usd, reverse=True)
    ranked = [q.pair for q in eligible]

    keep = [p for p in ranked[: params.keep_rank] if p in held]
    chosen = keep[: params.basket_size]
    for p in ranked:
        if len(chosen) >= params.basket_size:
            break
        if p not in chosen:
            chosen.append(p)
    return chosen


class LiquidBasket:
    name = "liquid_basket_v0"

    def targets(self, quotes, metas, held, params):
        universe = select_universe(quotes, metas, held, params)
        if not universe:
            return {}
        w = min(params.gross / len(universe), params.max_weight)
        return {p: w for p in universe}
