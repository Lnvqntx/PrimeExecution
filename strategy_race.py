from __future__ import annotations

import numpy as np
import pandas as pd

from features import build_features, load_snapshots

FEE = 0.0010
SLIPPAGE = 0.0005
COST_PER_TURNOVER = FEE + SLIPPAGE

WARMUP = 60
STEP = 5
GROSS = 0.80
TOP_N = 5
MAX_SPREAD_BPS = 30.0


def zscore(s):
    s = s.replace([np.inf, -np.inf], np.nan)
    std = s.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def select_weights(x, strategy, side_mode):
    x = x.copy()

    # Cross-sectional signals. All inputs are known at decision time.
    if strategy == "momentum":
        score = (
            0.25 * zscore(x["ret_15"])
            + 0.35 * zscore(x["ret_30"])
            + 0.40 * zscore(x["ret_60"])
        )
    elif strategy == "mean_reversion":
        score = (
            -0.60 * zscore(x["ret_15"])
            -0.40 * zscore(x["ret_30"])
        )
    elif strategy == "trend":
        score = (
            0.45 * zscore(x["trend"])
            + 0.35 * zscore(x["ret_30"])
            + 0.20 * zscore(x["ret_15"])
        )
    elif strategy == "hybrid":
        market_regime = x["ret_30"].median()
        momentum = (
            0.30 * zscore(x["ret_15"])
            + 0.35 * zscore(x["ret_30"])
            + 0.35 * zscore(x["ret_60"])
        )
        reversal = -0.65 * zscore(x["ret_15"]) - 0.35 * zscore(x["ret_30"])
        score = momentum if market_regime >= 0 else reversal
    else:
        raise ValueError(strategy)

    score = score.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    if side_mode == "long_only":
        chosen = x.assign(score=score).nlargest(TOP_N, "score")
        chosen = chosen[chosen["score"] > 0]
        if chosen.empty:
            return pd.Series(0.0, index=x["pair"])
        w = GROSS / len(chosen)
        return pd.Series(
            [w if p in set(chosen["pair"]) else 0.0 for p in x["pair"]],
            index=x["pair"],
        )

    # Long/short: long top names, short bottom names, equal gross halves.
    top = x.assign(score=score).nlargest(TOP_N, "score")
    bottom = x.assign(score=score).nsmallest(TOP_N, "score")

    weights = pd.Series(0.0, index=x["pair"])
    top_set = set(top["pair"])
    bottom_set = set(bottom["pair"])

    if top_set:
        weights += x["pair"].map(
            lambda p: GROSS / 2.0 / len(top_set) if p in top_set else 0.0
        ).values
    if bottom_set:
        weights -= x["pair"].map(
            lambda p: GROSS / 2.0 / len(bottom_set) if p in bottom_set else 0.0
        ).values
    return weights


def run_strategy(df, strategy, side_mode, step=15, cost_per_turnover=COST_PER_TURNOVER):
    work = df.sort_values(["timestamp", "pair"]).copy()

    # Keep this race self-contained: older feature files may not expose
    # every return horizon used by the portfolio signals.
    grouped = work.groupby("pair")["last_price"]
    for periods, name in ((15, "ret_15"), (30, "ret_30"), (60, "ret_60")):
        if name not in work.columns:
            work[name] = grouped.pct_change(periods)

    if "trend" not in work.columns:
        ema_fast = grouped.transform(
            lambda s: s.ewm(span=15, adjust=False).mean()
        )
        ema_slow = grouped.transform(
            lambda s: s.ewm(span=60, adjust=False).mean()
        )
        work["trend"] = ema_fast / ema_slow - 1.0

    if "spread_bps" not in work.columns:
        midpoint = (work["bid"] + work["ask"]) / 2.0
        work["spread_bps"] = (
            (work["ask"] - work["bid"]) / midpoint * 10_000
        )


    # Next-interval return: today's signal acts only on the following snapshot.
    work["next_price"] = work.groupby("pair")["last_price"].shift(-1)
    work["next_ret"] = work["next_price"] / work["last_price"] - 1.0

    times = sorted(work["timestamp"].unique())
    equity = 1.0
    prev_weights = {}
    period_returns = []
    turnovers = []
    trade_events = 0
    gross_total = 0.0
    cost_total = 0.0

    for i in range(WARMUP, len(times) - 1, step):
        t = times[i]
        next_t = times[min(i + step, len(times) - 1)]

        x = work[work["timestamp"] == t].copy()
        future = work[work["timestamp"] == next_t][["pair", "last_price"]]
        future = future.rename(columns={"last_price": "future_price"})
        x = x.merge(future, on="pair", how="inner")

        x = x.dropna(
            subset=[
                "last_price", "future_price", "ret_15",
                "ret_30", "ret_60", "trend", "spread_bps"
            ]
        )
        x = x[
            (x["spread_bps"] >= 0)
            & (x["spread_bps"] <= MAX_SPREAD_BPS)
        ]

        if len(x) < TOP_N:
            continue

        weights = select_weights(x, strategy, side_mode)
        weights.index = x["pair"].values

        current = {p: float(w) for p, w in weights.items() if abs(w) > 1e-12}
        all_pairs = set(prev_weights) | set(current)
        turnover = sum(
            abs(current.get(p, 0.0) - prev_weights.get(p, 0.0))
            for p in all_pairs
        )

        # The signal at t earns the return from t to t+STEP.
        x["next_interval_ret"] = (
            x["future_price"] / x["last_price"] - 1.0
        )
        gross_ret = float(
            sum(
                weights.get(pair, 0.0) * ret
                for pair, ret in zip(
                    x["pair"], x["next_interval_ret"]
                )
            )
        )

        trading_cost = cost_per_turnover * turnover
        gross_total += gross_ret
        cost_total += trading_cost
        net_ret = gross_ret - trading_cost
        equity *= max(0.0, 1.0 + net_ret)

        period_returns.append(net_ret)
        turnovers.append(turnover)
        trade_events += sum(
            abs(current.get(p, 0.0) - prev_weights.get(p, 0.0)) > 1e-9
            for p in all_pairs
        )
        prev_weights = current

    if len(period_returns) < 5:
        return None

    r = pd.Series(period_returns)
    eq = (1.0 + r).cumprod()
    dd = eq / eq.cummax() - 1.0
    vol = r.std()
    downside = r[r < 0].std()

    sharpe = np.sqrt(len(r)) * r.mean() / vol if vol > 0 else 0.0
    sortino = (
        np.sqrt(len(r)) * r.mean() / downside
        if downside > 0 else 0.0
    )

    return {
        "strategy": strategy,
        "mode": side_mode,
        "return": eq.iloc[-1] - 1.0,
        "max_dd": dd.min(),
        "sharpe": sharpe,
        "sortino": sortino,
        "turnover": float(np.mean(turnovers)),
        "gross_return": float(gross_total),
        "cost_drag": float(cost_total),
        "step": step,
        "events": trade_events,
        "periods": len(r),
    }


def main():
    df = build_features(load_snapshots("data/ticker_snapshots.csv"))
    print("=" * 100)
    print("PRIME EXECUTION — COST / REBALANCE SCAN")
    print("=" * 100)
    print(f"Snapshots: {df[\"timestamp\"].nunique()} | warmup: {WARMUP} | gross: {GROSS:.0%}")
    print("Testing rebalance speeds before selecting a production candidate.")
    print("Fee: 0.10% | slippage: 0.05% per unit turnover.")
    print()

    results = []
    for step in (5, 15, 30, 60):
        for strategy in ("momentum", "mean_reversion", "trend", "hybrid"):
            for mode in ("long_only", "long_short"):
                result = run_strategy(df, strategy, mode, step=step, cost_per_turnover=COST_PER_TURNOVER)
                if result:
                    results.append(result)

    if not results:
        print("Not enough observations.")
        return

    results.sort(key=lambda r: (r["sharpe"], r["return"]), reverse=True)
    print(f"{\"Step\":>4} {\"Strategy\":<18} {\"Mode\":<12} {\"Net\":>9} {\"Gross\":>9} {\"Cost\":>9} {\"MaxDD\":>9} {\"Sharpe\":>8} {\"Turn\":>7} {\"Events\":>6}")
    print("-" * 100)
    for r in results:
        print(f"{r[\"step\"]:>4} {r[\"strategy\"]:<18} {r[\"mode\"]:<12} {r[\"return\"]:+8.3%} {r[\"gross_return\"]:+8.3%} {r[\"cost_drag\"]:+8.3%} {r[\"max_dd\"]:+8.3%} {r[\"sharpe\"]:+7.3f} {r[\"turnover\"]:7.3f} {r[\"events\"]:6d}")

    print("\nTOP 5 BY SHARPE")
    print("-" * 100)
    for r in results[:5]:
        print(f"{r[\"step\"]:>2}m {r[\"strategy\"]:<18} {r[\"mode\"]:<12} net={r[\"return\"]:+.3%} gross={r[\"gross_return\"]:+.3%} cost={r[\"cost_drag\"]:+.3%} sharpe={r[\"sharpe\"]:+.3f}")

    print("\nPAPER SIMULATION ONLY — NO ORDERS ARE GENERATED.")

if __name__ == "__main__":
    main()
