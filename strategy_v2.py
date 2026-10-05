from __future__ import annotations

import pandas as pd


def score_v2(cross: pd.DataFrame) -> pd.DataFrame:
    out = cross.copy()

    # V2 keeps the V1 risk-adjusted momentum signal, but adds two
    # cross-sectional filters that materially change the ranking:
    # 1) positive fast/slow trend confirmation;
    # 2) relative-volatility penalty, so unusually unstable names rank lower.
    out["vol_rank"] = out["vol_60"].rank(pct=True, ascending=True)
    out["trend_strength"] = out["trend"].clip(lower=0.0)

    out["v2_score"] = (
        out["risk_adjusted_momentum"]
        * (1.0 + 0.50 * out["trend_strength"].rank(pct=True))
        * (1.10 - 0.60 * out["vol_rank"])
    )

    out = out[
        (out["trend"] > 0)
        & (out["spread_bps"] <= 50.0)
        & (out["vol_60"] > 0)
    ]

    return out.sort_values("v2_score", ascending=False)
