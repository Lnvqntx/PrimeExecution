from __future__ import annotations

import numpy as np
import pandas as pd
from features import build_features, load_snapshots

FEE = 0.001
SLIPPAGE = 0.0005
TOP_N = 5
GROSS = 0.80
MAX_SPREAD_BPS = 30.0
WARMUP = 60
STEP = 5
HORIZONS = (15, 30, 60)


def evaluate(df: pd.DataFrame, horizon: int):
    work = df.sort_values(["pair", "timestamp"]).copy()
    work["future_price"] = work.groupby("pair")["last_price"].shift(-horizon)
    times = sorted(work["timestamp"].unique())

    equity = 1.0
    rows = []
    selections = 0

    # Rolling evaluation: every 5 snapshots (~5 min), not once per horizon.
    # This gives us substantially more observations without pretending
    # overlapping paper trades are independent.
    for i in range(WARMUP, len(times) - horizon, STEP):
        t = times[i]
        now = work[work["timestamp"] == t].copy()
        x = now.dropna(
            subset=["change_24h", "last_price", "future_price", "spread_bps"]
        )
        x = x[(x["spread_bps"] >= 0) & (x["spread_bps"] <= MAX_SPREAD_BPS)]

        if len(x) < TOP_N:
            continue

        # Cross-sectional losers: mean-reversion hypothesis.
        x = x.sort_values("change_24h", ascending=True).head(TOP_N)

        gross_ret = GROSS * float(
            (x["future_price"] / x["last_price"] - 1).mean()
        )

        # Approximate round-trip trading cost for paper validation.
        cost = GROSS * 2.0 * (FEE + SLIPPAGE)
        net_ret = gross_ret - cost

        equity *= max(0.0, 1.0 + net_ret)
        rows.append((t, equity, net_ret))
        selections += len(x)

    if len(rows) < 3:
        return None

    e = pd.DataFrame(rows, columns=["timestamp", "equity", "return"])
    r = e["return"]
    dd = e["equity"] / e["equity"].cummax() - 1.0
    vol = r.std()
    downside = r[r < 0].std()

    sharpe = np.sqrt(len(r)) * r.mean() / vol if vol > 0 else 0.0
    sortino = (
        np.sqrt(len(r)) * r.mean() / downside
        if downside > 0
        else 0.0
    )

    return {
        "horizon": horizon,
        "periods": len(r),
        "return": equity - 1.0,
        "max_dd": dd.min(),
        "sharpe": sharpe,
        "sortino": sortino,
        "selections": selections,
    }


def main():
    df = build_features(load_snapshots("data/ticker_snapshots.csv"))
    snapshots = df["timestamp"].nunique()

    print("=" * 78)
    print("PRIME EXECUTION — V5B ROLLING MEAN-REVERSION SCAN")
    print("=" * 78)
    print(
        f"Snapshots: {snapshots} | warmup: {WARMUP} | "
        f"step: {STEP} | top {TOP_N}"
    )
    print(
        f"Signal: cross-sectional 24h losers | "
        f"spread <= {MAX_SPREAD_BPS:.0f} bps"
    )
    print(
        f"Round-trip cost model: {2*(FEE+SLIPPAGE):.2%} | "
        f"gross exposure: {GROSS:.0%}"
    )
    print()
    print("Horizon   Periods   Return     MaxDD      Sharpe    Sortino   Selections")
    print("-" * 78)

    for horizon in HORIZONS:
        result = evaluate(df, horizon)
        if result is None:
            print(f"{horizon:>6}m   insufficient observations")
            continue
        print(
            f"{horizon:>6}m   {result['periods']:>7}   "
            f"{result['return']:+.3%}   {result['max_dd']:+.3%}   "
            f"{result['sharpe']:+.3f}   {result['sortino']:+.3f}   "
            f"{result['selections']:>9}"
        )

    print()
    print(
        "Interpretation: this is a fast research scan, not a production "
        "backtest. Overlapping horizons mean observations are correlated."
    )
    print("PAPER SIMULATION ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
