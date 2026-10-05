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


def rank_series(s: pd.Series) -> pd.Series:
    return s.rank(method="average")


def evaluate_feature(df: pd.DataFrame, feature: str, horizon: int) -> dict[str, float]:
    cols = [feature, f"fwd_{horizon}"]
    sample = df[cols].replace([np.inf, -np.inf], np.nan).dropna()

    if len(sample) < 100:
        return {"n": len(sample), "ic": np.nan, "top": np.nan, "bottom": np.nan, "spread": np.nan}

    sample["decile"] = pd.qcut(
        sample[feature], 10, labels=False, duplicates="drop"
    )

    # Spearman IC without scipy: Pearson correlation of ranks.
    x = rank_series(sample[feature]).to_numpy(dtype=float)
    y = rank_series(sample[f"fwd_{horizon}"]).to_numpy(dtype=float)
    x_std = x.std()
    y_std = y.std()
    ic = float(np.corrcoef(x, y)[0, 1]) if x_std > 0 and y_std > 0 else np.nan

    top = sample.loc[
        sample["decile"] == sample["decile"].max(), f"fwd_{horizon}"
    ].mean()
    bottom = sample.loc[
        sample["decile"] == sample["decile"].min(), f"fwd_{horizon}"
    ].mean()

    return {
        "n": len(sample),
        "ic": ic,
        "top": float(top),
        "bottom": float(bottom),
        "spread": float(top - bottom),
    }


def main():
    df = load_snapshots("data/ticker_snapshots.csv")
    features = build_features(df)
    data = add_forward_returns(features)

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

    print("=" * 110)
    print("PRIME EXECUTION — SIGNAL DISCOVERY")
    print("=" * 110)
    print(f"Snapshots: {data['timestamp'].nunique()}")
    print(f"Pairs: {data['pair'].nunique()}")
    print()
    print(
        f"{'Feature':<25} {'Horizon':>8} {'N':>8} "
        f"{'IC':>10} {'Top':>12} {'Bottom':>12} {'Spread':>12}"
    )
    print("-" * 110)

    results = []
    for feature, label in feature_map.items():
        if feature not in data.columns:
            continue
        for horizon in HORIZONS:
            result = evaluate_feature(data, feature, horizon)
            result["feature"] = label
            result["horizon"] = horizon
            results.append(result)
            print(
                f"{label:<25} {horizon:>7}m {result['n']:>8} "
                f"{result['ic']:>10.4f} {result['top']:>11.3%} "
                f"{result['bottom']:>11.3%} {result['spread']:>11.3%}"
            )

    result_df = pd.DataFrame(results).dropna(subset=["spread"])
    print()
    print("BEST SIGNALS BY TOP-BOTTOM SPREAD")
    print("-" * 70)
    print(
        result_df.sort_values("spread", ascending=False)[
            ["feature", "horizon", "ic", "spread"]
        ].head(10).to_string(index=False)
    )

    print()
    print("Interpretation: positive IC/spread supports momentum-like behavior;")
    print("negative values support mean-reversion-like behavior.")
    print("RESEARCH ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
