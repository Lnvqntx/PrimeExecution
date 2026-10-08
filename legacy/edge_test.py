from __future__ import annotations

import numpy as np
import pandas as pd
from features import build_features, load_snapshots

FEE = 0.001
SLIPPAGE = 0.0005
COST = 2 * (FEE + SLIPPAGE)
HORIZON = 60
WARMUP = 60
STEP = 5
TOP_N = 5


def main():
    df = build_features(load_snapshots("data/ticker_snapshots.csv"))
    df = df.sort_values(["pair", "timestamp"]).copy()
    df["fwd_ret"] = (
        df.groupby("pair")["last_price"].shift(-HORIZON)
        / df["last_price"] - 1.0
    )

    times = sorted(df["timestamp"].unique())
    results = []

    for i in range(WARMUP, len(times) - HORIZON, STEP):
        t = times[i]
        x = df[df["timestamp"] == t].copy()
        x = x.dropna(subset=["fwd_ret", "ret_60", "spread_bps"])
        x = x[(x["spread_bps"] >= 0) & (x["spread_bps"] <= 30)]
        if len(x) < 10:
            continue

        x["rank"] = x["ret_60"].rank(pct=True)
        top = x.nlargest(TOP_N, "rank")["fwd_ret"].mean()
        bottom = x.nsmallest(TOP_N, "rank")["fwd_ret"].mean()
        results.append((t, top, bottom, top - bottom))

    r = pd.DataFrame(results, columns=["timestamp", "top", "bottom", "spread"])

    if len(r) < 3:
        print(f"Not enough observations: {len(r)}")
        return

    top_mean = r["top"].mean()
    bottom_mean = r["bottom"].mean()
    spread_mean = r["spread"].mean()
    spread_std = r["spread"].std()
    spread_t = (
        spread_mean / (spread_std / np.sqrt(len(r)))
        if spread_std > 0 else 0.0
    )

    print("=" * 78)
    print("PRIME EXECUTION — CLEAN 60m FORWARD EDGE TEST")
    print("=" * 78)
    print(
        f"Snapshots: {len(times)} | evaluations: {len(r)} | "
        f"horizon: {HORIZON} snapshots (~60m)"
    )
    print(f"Cost assumption: {COST:.2%} round trip")
    print()
    print("60m momentum -> next 60m forward return")
    print(f"Top momentum basket:        {top_mean:+.4%}")
    print(f"Top momentum after costs:   {top_mean - COST:+.4%}")
    print(f"Bottom momentum basket:     {bottom_mean:+.4%}")
    print(f"Bottom after costs:         {bottom_mean - COST:+.4%}")
    print(f"Top-minus-bottom spread:    {spread_mean:+.4%}")
    print(f"Spread t-stat (diagnostic): {spread_t:+.3f}")
    print()
    if top_mean - COST > 0 and spread_mean > 0:
        print("VERDICT: MOMENTUM SURVIVES — investigate as next candidate.")
    elif spread_mean > 0:
        print("VERDICT: relative momentum exists, but costs kill long-only edge.")
    else:
        print("VERDICT: 60m momentum FAILED this sample — discard it.")
    print("RESEARCH ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
