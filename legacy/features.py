from __future__ import annotations

import numpy as np
import pandas as pd


def load_snapshots(path: str = "data/ticker_snapshots.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["last_price"] = pd.to_numeric(df["last_price"], errors="coerce")
    df["bid"] = pd.to_numeric(df["bid"], errors="coerce")
    df["ask"] = pd.to_numeric(df["ask"], errors="coerce")
    df["unit_trade_value"] = pd.to_numeric(
        df["unit_trade_value"], errors="coerce"
    )
    return df.sort_values(["pair", "timestamp"])


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    grouped = out.groupby("pair", group_keys=False)

    out["ret_1"] = grouped["last_price"].pct_change(1)
    out["ret_5"] = grouped["last_price"].pct_change(5)
    out["ret_15"] = grouped["last_price"].pct_change(15)
    out["ret_60"] = grouped["last_price"].pct_change(60)

    out["vol_15"] = grouped["ret_1"].transform(
        lambda s: s.rolling(15, min_periods=8).std()
    )
    out["vol_60"] = grouped["ret_1"].transform(
        lambda s: s.rolling(60, min_periods=30).std()
    )

    out["ema_fast"] = grouped["last_price"].transform(
        lambda s: s.ewm(span=15, adjust=False).mean()
    )
    out["ema_slow"] = grouped["last_price"].transform(
        lambda s: s.ewm(span=60, adjust=False).mean()
    )

    out["trend"] = out["ema_fast"] / out["ema_slow"] - 1.0

    midpoint = (out["bid"] + out["ask"]) / 2.0
    out["spread_bps"] = (
        (out["ask"] - out["bid"]) / midpoint * 10_000
    ).replace([np.inf, -np.inf], np.nan)

    out["momentum"] = (
        0.50 * out["ret_15"]
        + 0.30 * out["ret_60"]
        + 0.20 * out["trend"]
    )

    out["risk_adjusted_momentum"] = (
        out["momentum"] / out["vol_60"].clip(lower=1e-8)
    )

    return out


def latest_cross_section(df: pd.DataFrame) -> pd.DataFrame:
    latest_time = df["timestamp"].max()
    latest = df[df["timestamp"] == latest_time].copy()

    latest = latest.replace([np.inf, -np.inf], np.nan)
    latest = latest.dropna(
        subset=["last_price", "momentum", "vol_60", "spread_bps"]
    )

    latest["momentum_rank"] = latest["risk_adjusted_momentum"].rank(
        ascending=False, pct=True
    )

    return latest.sort_values(
        "risk_adjusted_momentum", ascending=False
    )
