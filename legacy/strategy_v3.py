from __future__ import annotations

import pandas as pd


def score_v3(cross: pd.DataFrame) -> pd.DataFrame:
    out = cross.copy()

    # Regime-aware momentum:
    # - require positive trend
    # - reward stronger momentum relative to the current cross-section
    # - penalize high relative volatility
    # - penalize wide spreads
    momentum_rank = out["risk_adjusted_momentum"].rank(pct=True)
    trend_rank = out["trend"].rank(pct=True)
    vol_rank = out["vol_60"].rank(pct=True, ascending=True)
    spread_rank = out["spread_bps"].rank(pct=True, ascending=True)

    out["v3_score"] = (
        0.45 * momentum_rank
        + 0.30 * trend_rank
        + 0.15 * vol_rank
        + 0.10 * spread_rank
    )

    # A simple market-regime gate: only take longs when enough of the
    # cross-section has positive trend. This avoids trading aggressively
    # during broad risk-off conditions.
    breadth = float((out["trend"] > 0).mean())

    out["regime_bullish"] = breadth >= 0.50
    out["trend_breadth"] = breadth

    out = out[
        (out["regime_bullish"])
        & (out["trend"] > 0)
        & (out["spread_bps"] <= 50.0)
        & (out["vol_60"] > 0)
    ]

    return out.sort_values("v3_score", ascending=False)
