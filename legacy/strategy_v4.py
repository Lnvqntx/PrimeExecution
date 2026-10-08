from __future__ import annotations

import pandas as pd


def score_v4(cross: pd.DataFrame) -> pd.DataFrame:
    out = cross.copy()

    momentum = out["risk_adjusted_momentum"].rank(pct=True)
    medium_term = out["ret_60"].rank(pct=True)
    trend = out["trend"].rank(pct=True)
    low_vol = out["vol_60"].rank(pct=True, ascending=True)
    tight_spread = out["spread_bps"].rank(pct=True, ascending=True)

    # Avoid chasing names whose short-term move is already extreme.
    short_term = out["ret_15"].abs().rank(pct=True, ascending=True)

    out["v4_score"] = (
        0.30 * momentum
        + 0.25 * medium_term
        + 0.20 * trend
        + 0.10 * low_vol
        + 0.10 * tight_spread
        + 0.05 * short_term
    )

    out = out[
        (out["ret_60"] > 0)
        & (out["trend"] > 0)
        & (out["spread_bps"] <= 50.0)
        & (out["vol_60"] > 0)
    ]

    return out.sort_values("v4_score", ascending=False)
