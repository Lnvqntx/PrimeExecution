from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import pandas as pd

from features import build_features, load_snapshots
from strategy_v2 import score_v2
from strategy_v3 import score_v3


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


def make_targets(cross: pd.DataFrame, cfg: PaperConfig, strategy: str) -> dict[str, float]:
    if strategy == "v2":
        ranked = score_v2(cross)
        score_col = "v2_score"
        eligible = ranked[ranked[score_col] > cfg.min_score]
    elif strategy == "v3":
        ranked = score_v3(cross)
        score_col = "v3_score"
        eligible = ranked[ranked[score_col] > cfg.min_score]
    else:
        eligible = cross[
            (cross["risk_adjusted_momentum"] > cfg.min_score)
            & (cross["spread_bps"] <= 50.0)
        ].sort_values("risk_adjusted_momentum", ascending=False)
        score_col = "risk_adjusted_momentum"

    if eligible.empty:
        return {}

    selected = eligible.head(cfg.top_n)
    scores = selected[score_col].clip(lower=0.0)
    if scores.sum() <= 0:
        return {}

    weights = scores / scores.sum() * cfg.gross_exposure
    weights = weights.clip(upper=cfg.max_position_weight)
    return dict(zip(selected["pair"], weights))


def performance_metrics(equity: pd.Series, timestamps=None) -> dict[str, float]:
    if len(equity) < 2:
        return {
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
        }

    returns = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())

    mean = returns.mean()
    std = returns.std(ddof=1)
    downside = returns[returns < 0].std(ddof=1)
    sharpe = float(mean / std * math.sqrt(len(returns))) if std > 0 else 0.0
    sortino = float(mean / downside * math.sqrt(len(returns))) if downside > 0 else 0.0

    calmar = 0.0
    if timestamps is not None and len(timestamps) >= 2 and max_drawdown < 0:
        # Series uses a RangeIndex here, so iloc is required for positional
        # first/last access on pandas 2.x.
        first_time = pd.Timestamp(timestamps.iloc[0])
        last_time = pd.Timestamp(timestamps.iloc[-1])
        seconds = max(1.0, (last_time - first_time).total_seconds())
        years = seconds / (365.0 * 24.0 * 3600.0)
        annualized_return = (1.0 + total_return) ** (1.0 / max(years, 1e-9)) - 1.0
        calmar = float(annualized_return / abs(max_drawdown))

    return {
        "total_return": float(total_return),
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
    }


def run_paper_backtest(df: pd.DataFrame, cfg: PaperConfig, strategy: str = "v1"):
    features = build_features(df)
    timestamps = sorted(features["timestamp"].dropna().unique())

    if len(timestamps) < 61:
        return None, {"error": f"Need at least 61 snapshots; found {len(timestamps)}"}

    positions: dict[str, float] = {}
    equity = cfg.initial_cash
    equity_rows = []
    trade_rows = []

    for i, timestamp in enumerate(timestamps[:-1]):
        current = features[features["timestamp"] == timestamp].copy()
        next_time = timestamps[i + 1]
        nxt = features[features["timestamp"] == next_time].copy()

        current_prices = dict(zip(current["pair"], current["last_price"]))
        next_prices = dict(zip(nxt["pair"], nxt["last_price"]))

        if i % cfg.rebalance_every == 0:
            latest = current.replace([float("inf"), float("-inf")], pd.NA).dropna(
                subset=["last_price", "risk_adjusted_momentum", "vol_60", "spread_bps"]
            )

            targets = make_targets(latest, cfg, strategy)
            turnover = 0.0

            for pair in set(positions) | set(targets):
                old = positions.get(pair, 0.0)
                new = targets.get(pair, 0.0)
                change = abs(new - old)
                turnover += change

                if change > 1e-12:
                    trade_rows.append({
                        "timestamp": timestamp,
                        "pair": pair,
                        "old_weight": old,
                        "new_weight": new,
                        "turnover": change,
                    })

            cost = turnover * (cfg.fee_bps + cfg.slippage_bps) / 10_000.0
            equity *= 1.0 - cost
            positions = targets

        portfolio_return = 0.0
        for pair, weight in positions.items():
            if pair in current_prices and pair in next_prices:
                price = current_prices[pair]
                if price and price > 0:
                    portfolio_return += weight * (next_prices[pair] / price - 1.0)

        equity *= 1.0 + portfolio_return
        equity_rows.append({
            "timestamp": next_time,
            "equity": equity,
            "positions": len(positions),
        })

    equity_df = pd.DataFrame(equity_rows)
    metrics = performance_metrics(equity_df["equity"], equity_df["timestamp"])
    metrics["observations"] = len(timestamps)
    metrics["trades"] = len(trade_rows)

    return equity_df, {**metrics, "trade_log": pd.DataFrame(trade_rows)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/ticker_snapshots.csv")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--strategy", choices=["v1", "v2", "v3"], default="v1")
    args = parser.parse_args()

    df = load_snapshots(args.data)
    if df.empty:
        print("No market data yet.")
        return

    cfg = PaperConfig(top_n=args.top)
    equity, result = run_paper_backtest(df, cfg, args.strategy)

    print("=" * 78)
    print(f"PRIME EXECUTION — {args.strategy.upper()} PAPER TRADING ENGINE")
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
    print(f"Calmar-like: {result['calmar']:.3f}")
    print()
    print("PAPER SIMULATION ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
