from __future__ import annotations

import numpy as np
import pandas as pd
from features import build_features, load_snapshots

FEE = 0.001
SLIPPAGE = 0.0005
TOP_N = 5
GROSS = 0.80
REBALANCE = 30
MAX_SPREAD_BPS = 30.0

def run():
    df = build_features(load_snapshots("data/ticker_snapshots.csv"))
    df["signal"] = -df["change_24h"]  # cross-sectional mean reversion
    times = sorted(df["timestamp"].unique())
    equity = 1.0
    peak = 1.0
    rows = []
    trades = 0
    prev = {}

    for i in range(60, len(times) - 1, REBALANCE):
        t = times[i]
        nt = times[i + 1]
        snap = df[df.timestamp == t].copy()
        nxt = df[df.timestamp == nt][["pair", "last_price"]].rename(columns={"last_price":"next_price"})
        snap = snap.merge(nxt, on="pair", how="inner")
        snap = snap.dropna(subset=["signal","last_price","next_price","spread_bps","unit_trade_value"])
        snap = snap[(snap.spread_bps >= 0) & (snap.spread_bps <= MAX_SPREAD_BPS)]
        snap = snap.sort_values("signal", ascending=False).head(TOP_N)
        if snap.empty:
            rows.append((t, equity))
            continue

        w = GROSS / len(snap)
        gross_ret = float((w * (snap.next_price / snap.last_price - 1.0)).sum())
        turnover = GROSS if not prev else GROSS
        cost = turnover * (FEE + SLIPPAGE)
        equity *= max(0.0, 1.0 + gross_ret - cost)
        trades += len(snap)
        prev = {p:w for p in snap.pair}
        peak = max(peak, equity)
        rows.append((nt, equity))

    if not rows:
        print("Not enough data.")
        return

    e = pd.DataFrame(rows, columns=["timestamp","equity"])
    r = e.equity.pct_change().dropna()
    dd = e.equity / e.equity.cummax() - 1
    sharpe = np.sqrt(len(r)) * r.mean() / r.std() if r.std() > 0 else 0.0
    downside = r[r < 0].std()
    sortino = np.sqrt(len(r)) * r.mean() / downside if downside and downside > 0 else 0.0

    print("="*72)
    print("PRIME EXECUTION — V5 24H MEAN-REVERSION PAPER BACKTEST")
    print("="*72)
    print(f"Signal: inverse 24h change | top {TOP_N} losers")
    print(f"Gross exposure: {GROSS:.0%} | rebalance: {REBALANCE}m")
    print(f"Fee: {FEE:.2%} | slippage: {SLIPPAGE:.2%} | spread cap: {MAX_SPREAD_BPS:.0f} bps")
    print(f"Return: {(equity-1)*100:.3f}%")
    print(f"Max drawdown: {dd.min()*100:.3f}%")
    print(f"Sharpe-like: {sharpe:.3f}")
    print(f"Sortino-like: {sortino:.3f}")
    print(f"Simulated selections: {trades}")
    print("PAPER SIMULATION ONLY — NO ORDERS ARE GENERATED.")

if __name__ == "__main__":
    run()
