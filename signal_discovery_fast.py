from __future__ import annotations

import numpy as np
import pandas as pd
from features import build_features, load_snapshots

HORIZONS = (5, 10, 15, 30)

def forward_returns(df):
    out = df.copy()
    g = out.groupby("pair", group_keys=False)
    for h in HORIZONS:
        out[f"fwd_{h}"] = g["last_price"].shift(-h) / out["last_price"] - 1.0
    return out

def test(df, feature, h):
    cols = ["timestamp", feature, f"fwd_{h}"]
    x = df[cols].replace([np.inf, -np.inf], np.nan).dropna()
    rows = []
    for _, g in x.groupby("timestamp"):
        if len(g) < 20:
            continue
        r = g[feature].rank(pct=True)
        top = g.loc[r >= .9, f"fwd_{h}"].mean()
        bot = g.loc[r <= .1, f"fwd_{h}"].mean()
        xr = g[feature].rank().to_numpy(float)
        yr = g[f"fwd_{h}"].rank().to_numpy(float)
        ic = np.corrcoef(xr, yr)[0,1] if xr.std() and yr.std() else np.nan
        rows.append((ic, top, bot))
    if not rows:
        return np.nan, np.nan, np.nan, 0
    a = np.array(rows, float)
    return np.nanmean(a[:,0]), np.nanmean(a[:,1]), np.nanmean(a[:,2]), len(a)

def main():
    df = load_snapshots("data/ticker_snapshots.csv")
    d = forward_returns(build_features(df))
    features = {
        "ret_15":"15m momentum",
        "ret_60":"60m momentum",
        "trend":"EMA trend",
        "vol_60":"60m volatility",
        "unit_trade_value":"trade value",
        "change_24h":"24h change",
        "risk_adjusted_momentum":"risk-adjusted momentum",
    }
    results=[]
    print("="*100)
    print("PRIME EXECUTION — FAST EDGE SCAN")
    print("="*100)
    print(f"Snapshots: {d.timestamp.nunique()} | Pairs: {d.pair.nunique()}")
    print(f"{'Feature':<25}{'H':>5}{'N':>6}{'IC':>10}{'Top':>11}{'Bottom':>11}{'Spread':>11}")
    print("-"*100)
    for f,label in features.items():
        for h in HORIZONS:
            ic,top,bot,n=test(d,f,h)
            spread=top-bot if np.isfinite(top) and np.isfinite(bot) else np.nan
            results.append((label,h,ic,top,bot,spread,n))
            print(f"{label:<25}{h:>4}m{n:>6}{ic:>10.4f}{top:>10.3%}{bot:>10.3%}{spread:>10.3%}")
    print("\nBEST EDGES")
    for r in sorted(results,key=lambda z: z[5] if np.isfinite(z[5]) else -999,reverse=True)[:8]:
        print(f"{r[0]:<25} {r[1]:>2}m  IC={r[2]:+.4f} spread={r[5]:+.3%} N={r[6]}")
    print("\nRESEARCH ONLY — NO ORDERS ARE GENERATED.")

if __name__ == "__main__":
    main()
