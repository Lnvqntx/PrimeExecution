from __future__ import annotations

import pandas as pd


def score_v2(cross: pd.DataFrame) -> pd.DataFrame:
    out = cross.copy()

    # V2: momentum must agree with the fast/slow trend.
    trend_confirmation = (out["trend"] > 0).astype(float)

    # Penalize unstable/high-volatility names rather than simply rewarding
    # raw momentum.  Spread remains a hard execution-quality filter.
    volatility_penalty = 1.0 / (1.0 + out["vol_60"].clip(lower=0.0))

    out["v2_score"] = (
        out["risk_adjusted_momentum"]
        * (0.5 + 0.5 * trend_confirmation)
        * volatility_penalty
    )

    out = out[
        (out["trend"] > 0)
        & (out["spread_bps"] <= 50.0)
        & (out["vol_60"] > 0)
    ]

    return out.sort_values("v2_score", ascending=False)
