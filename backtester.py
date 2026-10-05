from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from features import build_features, load_snapshots


@dataclass(frozen=True)
class BacktestConfig:
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    top_n: int = 5
    gross_exposure: float = 0.80
    rebalance_every: int = 15


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """
    Research-only portfolio simulation.

    Signal at time t is formed from information available at t.
    The position is applied to the next observation, avoiding look-ahead.
    Costs are charged on absolute turnover.
    """
    features = build_features(df)
    times = sorted(features["timestamp"].dropna().unique())

    equity = 1.0
    previous_weights = {}
    records = []

    for i in range(len(times) - 1):
        now = times[i]
        nxt = times[i + 1]

        if i % cfg.rebalance_every != 0:
            continue

        cross = features[features["timestamp"] == now].copy()
        future = features[features["timestamp"] == nxt].copy()

        cross = cross.replace([np.inf, -np.inf], np.nan)
        cross = cross.dropna(
            subset=["risk_adjusted_momentum", "spread_bps", "vol_60"]
        )

        # Avoid obviously poor execution conditions.
        cross = cross[cross["spread_bps"] <= 50]

        if len(cross) < cfg.top_n:
            continue

        cross = cross.sort_values(
            "risk_adjusted_momentum", ascending=False
        ).head(cfg.top_n)

        # Equal-weight long-only portfolio for V1.
        target_weight = cfg.gross_exposure / len(cross)
        target_weights = {
            row["pair"]: target_weight
            for _, row in cross.iterrows()
        }

        turnover = 0.0
        all_pairs = set(previous_weights) | set(target_weights)
        for pair in all_pairs:
            turnover += abs(
                target_weights.get(pair, 0.0)
                - previous_weights.get(pair, 0.0)
            )

        cost_rate = (cfg.fee_bps + cfg.slippage_bps) / 10_000.0
        transaction_cost = turnover * cost_rate

        # Next-period portfolio return.
        future_returns = {}
        for _, row in future.iterrows():
            if row["pair"] in target_weights and row["last_price"] > 0:
                future_returns[row["pair"]] = row["last_price"]

        current_prices = {
            row["pair"]: row["last_price"]
            for _, row in cross.iterrows()
            if row["last_price"] > 0
        }

        portfolio_return = 0.0
        for pair, weight in target_weights.items():
            if pair in current_prices and pair in future_returns:
                r = future_returns[pair] / current_prices[pair] - 1.0
                portfolio_return += weight * r

        net_return = portfolio_return - transaction_cost
        equity *= 1.0 + net_return

        records.append(
            {
                "timestamp": now,
                "next_timestamp": nxt,
                "gross_return": portfolio_return,
                "turnover": turnover,
                "transaction_cost": transaction_cost,
                "net_return": net_return,
                "equity": equity,
                "positions": len(target_weights),
            }
        )

        previous_weights = target_weights

    return pd.DataFrame(records)


def metrics(result: pd.DataFrame) -> dict:
    if result.empty:
        return {}

    returns = result["net_return"].astype(float)
    equity = result["equity"].astype(float)

    downside = returns[returns < 0]
    downside_dev = downside.std(ddof=1) if len(downside) > 1 else np.nan
    volatility = returns.std(ddof=1)

    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0

    return {
        "total_return": float(equity.iloc[-1] - 1.0),
        "volatility": float(volatility) if pd.notna(volatility) else 0.0,
        "max_drawdown": float(drawdown.min()),
        "sharpe_like": (
            float(returns.mean() / volatility)
            if volatility and pd.notna(volatility)
            else 0.0
        ),
        "sortino_like": (
            float(returns.mean() / downside_dev)
            if downside_dev and pd.notna(downside_dev)
            else 0.0
        ),
        "observations": int(len(result)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/ticker_snapshots.csv")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    df = load_snapshots(args.data)
    if df.empty:
        print("No market data yet.")
        return

    cfg = BacktestConfig(top_n=args.top)
    result = run_backtest(df, cfg)

    print("=" * 78)
    print("PRIME EXECUTION — V1 RESEARCH BACKTEST")
    print("=" * 78)

    if result.empty:
        print("Not enough observations yet. Keep the collector running.")
        return

    for key, value in metrics(result).items():
        if isinstance(value, float):
            print(f"{key:20s}: {value:.6f}")
        else:
            print(f"{key:20s}: {value}")

    print()
    print("RESEARCH SIMULATION ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
