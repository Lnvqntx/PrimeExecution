from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from features import build_features, load_snapshots


@dataclass
class PaperConfig:
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    top_n: int = 5
    gross_exposure: float = 0.80
    rebalance_every: int = 15
    max_position_weight: float = 0.20
    min_score: float = 0.0
    initial_cash: float = 100_000.0


def make_targets(cross: pd.DataFrame, cfg: PaperConfig) -> dict[str, float]:
    eligible = cross[
        (cross["risk_adjusted_momentum"] > cfg.min_score)
        & (cross["spread_bps"] <= 50.0)
    ].copy()

    if eligible.empty:
        return {}

    selected = eligible.head(cfg.top_n).copy()
    scores = selected["risk_adjusted_momentum"].clip(lower=0.0)

    if scores.sum() <= 0:
        return {}

    weights = scores / scores.sum() * cfg.gross_exposure
    weights = weights.clip(upper=cfg.max_position_weight)

    # Re-normalize after the per-position cap.
    if weights.sum() > 0:
        weights = weights / weights.sum() * min(
            cfg.gross_exposure, weights.sum()
        )

    return dict(zip(selected["pair"], weights))


def performance_metrics(equity: pd.Series) -> dict[str, float]:
    if len(equity) < 2:
        return {
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
        }

    returns = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0

    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    max_drawdown = float(drawdown.min())

    mean = returns.mean()
    std = returns.std(ddof=1)
    downside = returns[returns < 0].std(ddof=1)

    sharpe = float(mean / std * math.sqrt(len(returns))) if std > 0 else 0.0
    sortino = (
        float(mean / downside * math.sqrt(len(returns)))
        if downside > 0
        else 0.0
    )

    return {
        "total_return": float(total_return),
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
    }


def run_paper_backtest(df: pd.DataFrame, cfg: PaperConfig):
    features = build_features(df)
    timestamps = sorted(features["timestamp"].dropna().unique())

    if len(timestamps) < 61:
        return None, {
            "error": f"Need at least 61 snapshots; found {len(timestamps)}"
        }

    cash = cfg.initial_cash
    positions: dict[str, float] = {}
    equity_rows = []
    trade_rows = []

    last_targets: dict[str, float] = {}

    for i, timestamp in enumerate(timestamps[:-1]):
        current = features[features["timestamp"] == timestamp].copy()
        next_time = timestamps[i + 1]
        nxt = features[features["timestamp"] == next_time].copy()

        prices = dict(zip(current["pair"], current["last_price"]))
        next_prices = dict(zip(nxt["pair"], nxt["last_price"]))

        # Mark current portfolio before any rebalance.
        current_equity = cash
        for pair, weight in positions.items():
            if pair in prices:
                current_equity += weight * current_equity * 0.0
        # Positions are represented as portfolio weights. Reconstruct their
        # value from the previous equity using current prices below.
        if i == 0:
            portfolio_value = cash
        else:
            portfolio_value = equity_rows[-1]["equity"]
            for pair, old_weight in positions.items():
                if pair in prices and pair in next_prices:
                    portfolio_value *= 1.0 + old_weight * (
                        next_prices[pair] / prices[pair] - 1.0
                    )

        if i % cfg.rebalance_every == 0:
            latest = current.replace([np.inf, -np.inf], np.nan).dropna(
                subset=[
                    "last_price",
                    "risk_adjusted_momentum",
                    "vol_60",
                    "spread_bps",
                ]
            )
            latest = latest.sort_values(
                "risk_adjusted_momentum", ascending=False
            )

            targets = make_targets(latest, cfg)

            all_pairs = set(positions) | set(targets)
            turnover = 0.0

            for pair in all_pairs:
                old = positions.get(pair, 0.0)
                new = targets.get(pair, 0.0)
                turnover += abs(new - old)

                if abs(new - old) > 1e-12:
                    trade_rows.append(
                        {
                            "timestamp": timestamp,
                            "pair": pair,
                            "old_weight": old,
                            "new_weight": new,
                            "turnover": abs(new - old),
                        }
                    )

            cost = turnover * (cfg.fee_bps + cfg.slippage_bps) / 10_000.0
            portfolio_value *= 1.0 - cost
            positions = targets
            last_targets = targets

        equity_rows.append(
            {
                "timestamp": timestamp,
                "equity": portfolio_value,
                "positions": len(last_targets),
            }
        )

    equity = pd.DataFrame(equity_rows)
    metrics = performance_metrics(equity["equity"])
    metrics["observations"] = len(timestamps)
    metrics["trades"] = len(trade_rows)

    return equity, {
        **metrics,
        "trade_log": pd.DataFrame(trade_rows),
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

    cfg = PaperConfig(top_n=args.top)
    equity, result = run_paper_backtest(df, cfg)

    print("=" * 78)
    print("PRIME EXECUTION — PAPER TRADING ENGINE")
    print("=" * 78)

    if equity is None:
        print(result["error"])
        print("Keep the collector running.")
        return

    print(f"Observations: {result['observations']}")
    print(f"Simulated trades: {result['trades']}")
    print(f"Total return: {result['total_return']:.2%}")
    print(f"Max drawdown: {result['max_drawdown']:.2%}")
    print(f"Sharpe-like: {result['sharpe']:.3f}")
    print(f"Sortino-like: {result['sortino']:.3f}")
    print()
    print("PAPER SIMULATION ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
