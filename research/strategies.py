"""The three pre-declared candidates (declared before any backtest was run).

Each is a pure function: (close, quote_volume) panels -> target weights per date, using
only rolling/backward-looking operations, so the row for date t depends only on data up
to and including t. Long-only, weights sum to <= 1 (no leverage).

Grids are deliberately small and fixed up front; the walk-forward picks a member of the
grid per month using only past data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _alive(close: pd.DataFrame) -> pd.DataFrame:
    return close.notna()


def ts_trend(close: pd.DataFrame, volume: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Time-series trend: each pair gets 1/N of equity when its close is above its
    `lookback`-day simple moving average, otherwise that slice stays in cash."""
    sma = close.rolling(lookback, min_periods=lookback).mean()
    n = _alive(close).sum(axis=1).replace(0, np.nan)
    on = (close > sma).astype(float).where(sma.notna())
    return on.div(n, axis=0)


def xs_momentum(close: pd.DataFrame, volume: pd.DataFrame, lookback: int, top_k: int) -> pd.DataFrame:
    """Cross-sectional momentum: hold the `top_k` pairs with the highest `lookback`-day
    return, equal weight, fully invested."""
    mom = close / close.shift(lookback) - 1
    rank = mom.rank(axis=1, ascending=False, method="first")
    valid = mom.notna().sum(axis=1) >= top_k
    return ((rank <= top_k).astype(float) / top_k).where(valid, axis=0)


def vol_basket(close: pd.DataFrame, volume: pd.DataFrame, lookback: int, target_vol: float) -> pd.DataFrame:
    """Volatility-scaled basket: inverse-volatility weights across all pairs, then the
    whole basket scaled so its trailing `lookback`-day volatility hits `target_vol`
    (annualised), capped at 100% gross."""
    rets = close.pct_change(fill_method=None)
    vol = rets.rolling(lookback, min_periods=lookback).std()
    inv = (1 / vol).replace([np.inf, -np.inf], np.nan)
    base = inv.div(inv.sum(axis=1), axis=0)
    # trailing volatility of the inverse-vol basket using today's weights (no look-ahead)
    port = pd.Series(np.nan, index=close.index)
    r = rets.fillna(0.0).to_numpy()
    b = base.fillna(0.0).to_numpy()
    for t in range(lookback, len(close)):
        if b[t].sum() > 0:
            port.iloc[t] = (r[t - lookback + 1: t + 1] @ b[t]).std(ddof=1) * np.sqrt(365)
    scale = (target_vol / port).clip(upper=1.0)
    return base.mul(scale, axis=0)


CANDIDATES = {
    "ts_trend": (ts_trend, [{"lookback": L} for L in (20, 50, 100)]),
    "xs_momentum": (xs_momentum, [{"lookback": L, "top_k": k} for L in (14, 28, 56) for k in (5, 10)]),
    "vol_basket": (vol_basket, [{"lookback": L, "target_vol": v} for L in (20, 60) for v in (0.3, 0.6)]),
}


# ---- reference benchmarks (not candidates; never selected) ----

def equal_weight(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    n = _alive(close).sum(axis=1).replace(0, np.nan)
    return _alive(close).astype(float).div(n, axis=0)


def btc_hold(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    w["BTCUSDT"] = 1.0
    return w


def phase0_proxy(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """Rough stand-in for the live Phase 0 basket: 30% gross, equal weight across the 10
    pairs with the highest trailing 7-day quote volume (spread filter not modelled)."""
    vol7 = volume.rolling(7, min_periods=7).mean()
    rank = vol7.rank(axis=1, ascending=False, method="first")
    valid = vol7.notna().sum(axis=1) >= 10
    return ((rank <= 10).astype(float) * 0.03).where(valid, axis=0)


BENCHMARKS = {"btc_hold": btc_hold, "equal_weight": equal_weight, "phase0_proxy": phase0_proxy}
