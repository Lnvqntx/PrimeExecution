from __future__ import annotations

import numpy as np
import pandas as pd
from features import build_features, load_snapshots

FEE = 0.001
SLIPPAGE = 0.0005
TOP_N = 5
GROSS = 0.80
HORIZON = 60
MAX_SPREAD_BPS = 30.0


def main():
    df = build_features(load_snapshots("data/ticker_snapshots.csv"))

    # Roostoo collector produces a complete cross-section every ~60 seconds.
    # Align the future price by snapshot position, not exact timestamp equality.
    df = df.sort_values(["pair", "timestamp"]).copy()
    df["future_price"] = df.groupby("pair")["last_price"].shift(-HORIZON)

    times = sorted(df["timestamp"].unique())
    equity = 1.0
    rows = []
    trades = 0

    # Evaluate every 60 snapshots = approximately one hour.
    for i in range(60, len(times) - HORIZON, HORIZON):
        t = times[i]
        now = df[df["timestamp"] == t].copy()
        x = now.dropna(
            subset=["change_24h", "last_price", "future_price", "spread_bps"]
        )
        x = x[(x["spread_bps"] >= 0) & (x["spread_bps"] <= MAX_SPREAD_BPS)]

        # Long the cross-sectional losers (mean reversion).
        x = x.sort_values("change_24h", ascending=True).head(TOP_N)
        if len(x) < TOP_N:
            continue

        gross_ret = GROSS * float(
            (x["future_price"] / x["last_price"] - 1).mean()
        )
        cost = GROSS * (FEE + SLIPPAGE)
        equity *= max(0.0, 1.0 + gross_ret - cost)
        trades += len(x)
        rows.append((t, equity))

    if len(rows) < 2:
        print(
            f"Not enough aligned horizon observations: "
            f"{len(rows)} periods from {len(times)} snapshots."
        )
        return

    e = pd.DataFrame(rows, columns=["timestamp", "equity"])
    r = e["equity"].pct_change().dropna()
    dd = e["equity"] / e["equity"].cummax() - 1
    vol = r.std()
    downside = r[r < 0].std()
    sharpe = np.sqrt(len(r)) * r.mean() / vol if vol > 0 else 0.0
    sortino = (
        np.sqrt(len(r)) * r.mean() / downside if downside > 0 else 0.0
    )

    print("=" * 72)
    print("PRIME EXECUTION — V5B HORIZON-ALIGNED MEAN REVERSION")
    print("=" * 72)
    print(f"Signal: 24h losers | hold: {HORIZON} snapshots (~60m) | top {TOP_N}")
    print(f"Gross: {GROSS:.0%} | fee: {FEE:.2%} | slippage: {SLIPPAGE:.2%}")
    print(f"Return: {(equity - 1) * 100:+.3f}%")
    print(f"Max drawdown: {dd.min() * 100:.3f}%")
    print(f"Sharpe-like: {sharpe:.3f}")
    print(f"Sortino-like: {sortino:.3f}")
    print(f"Simulated selections: {trades}")
    print("PAPER SIMULATION ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
