from __future__ import annotations

import numpy as np
import pandas as pd

from features import build_features, load_snapshots

HORIZONS = (15, 30, 60)


def add_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    grouped = out.groupby("pair", group_keys=False)
    for h in HORIZONS:
        out[f"fwd_{h}"] = grouped["last_price"].shift(-h) / out["last_price"] - 1.0
    return out


def cross_sectional_test(
    df: pd.DataFrame, feature: str, horizon: int, top_pct: float = 0.10
) -> dict[str, float]:
    sample = df[["timestamp", "pair", feature, f"fwd_{horizon}"]].copy()
    sample = sample.replace([np.inf, -np.inf], np.nan).dropna()

    if sample.empty:
        return {"n": 0, "ic": np.nan, "top": np.nan, "bottom": np.nan, "spread": np.nan}

    def one_timestamp(group: pd.DataFrame) -> pd.Series:
        if len(group) < 10:
            return pd.Series(dtype=float)

        ranks = group[feature].rank(method="average", pct=True)
        top = group.loc[ranks >= 1.0 - top_pct, f"fwd_{horizon}"].mean()
        bottom = group.loc[ranks <= top_pct, f"fwd_{horizon}"].mean()

        x = group[feature].rank(method="average").to_numpy(float)
        y = group[f"fwd_{horizon}"].rank(method="average").to_numpy(float)

        if x.std() == 0 or y.std() == 0:
            ic = np.nan
        else:
            ic = float(np.corrcoef(x, y)[0, 1])

        return pd.Series({"ic": ic, "top": top, "bottom": bottom})

    rows = []
    for timestamp, group in sample.groupby("timestamp", sort=True):
        result = one_timestamp(group)
        if not result.empty:
            result["timestamp"] = timestamp
            rows.append(result)

    if not rows:
        return {"n": 0, "ic": np.nan, "top": np.nan, "bottom": np.nan, "spread": np.nan}

    stats = pd.DataFrame(rows)
    return {
        "n": len(stats),
        "ic": float(stats["ic"].mean()),
        "top": float(stats["top"].mean()),
        "bottom": float(stats["bottom"].mean()),
        "spread": float((stats["top"] - stats["bottom"]).mean()),
    }


def stability_test(
    df: pd.DataFrame, feature: str, horizon: int
) -> tuple[float, float, float]:
    timestamps = sorted(df["timestamp"].dropna().unique())
    if len(timestamps) < 30:
        return np.nan, np.nan, np.nan

    thirds = np.array_split(timestamps, 3)
    values = []

    for block in thirds:
        block_df = df[df["timestamp"].isin(block)]
        values.append(cross_sectional_test(block_df, feature, horizon)["spread"])

    return tuple(float(x) if np.isfinite(x) else np.nan for x in values)


def main():
    df = load_snapshots("data/ticker_snapshots.csv")
    data = add_forward_returns(build_features(df))

    feature_map = {
        "ret_15": "15m momentum",
        "ret_60": "60m momentum",
        "trend": "EMA trend",
        "vol_60": "60m volatility",
        "spread_bps": "spread",
        "unit_trade_value": "trade value",
        "change_24h": "24h change",
        "risk_adjusted_momentum": "risk-adjusted momentum",
    }

    print("=" * 112)
    print("PRIME EXECUTION — CROSS-SECTIONAL SIGNAL DISCOVERY V2")
    print("=" * 112)
    print(f"Snapshots: {data['timestamp'].nunique()}")
    print(f"Pairs: {data['pair'].nunique()}")
    print()
    print(
        f"{'Feature':<25} {'Horizon':>8} {'Folds':>7} "
        f"{'Mean IC':>10} {'Top':>10} {'Bottom':>10} {'Spread':>10}"
    )
    print("-" * 112)

    results = []

    for feature, label in feature_map.items():
        for horizon in HORIZONS:
            r = cross_sectional_test(data, feature, horizon)
            results.append((label, horizon, r))
            print(
                f"{label:<25} {horizon:>7}m {r['n']:>7} "
                f"{r['ic']:>10.4f} {r['top']:>9.3%} "
                f"{r['bottom']:>9.3%} {r['spread']:>9.3%}"
            )

    print()
    print("TOP SIGNALS — CROSS-SECTIONAL SPREAD")
    print("-" * 80)

    ranked = sorted(
        results,
        key=lambda x: x[2]["spread"] if np.isfinite(x[2]["spread"]) else -np.inf,
        reverse=True,
    )

    for label, horizon, r in ranked[:6]:
        a, b, c = stability_test(data, next(k for k, v in feature_map.items() if v == label), horizon)
        print(
            f"{label:<25} {horizon:>3}m | IC={r['ic']:.4f} | "
            f"spread={r['spread']:.3%} | thirds={a:.3%}, {b:.3%}, {c:.3%}"
        )

    print()
    print("This test ranks assets WITHIN EACH TIMESTAMP, avoiding pooled-time bias.")
    print("RESEARCH ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
