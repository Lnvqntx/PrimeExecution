from __future__ import annotations

import argparse

from features import load_snapshots
from paper_engine import PaperConfig, performance_metrics, run_paper_backtest


WARMUP = 61
TEST_SIZE = 60


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/ticker_snapshots.csv")
    args = parser.parse_args()

    df = load_snapshots(args.data)
    timestamps = sorted(df["timestamp"].dropna().unique())

    print("=" * 86)
    print("PRIME EXECUTION — WALK-FORWARD PAPER VALIDATION")
    print("=" * 86)

    minimum = WARMUP + TEST_SIZE
    if len(timestamps) < minimum:
        print(f"Need at least {minimum} snapshots; found {len(timestamps)}")
        print("Keep the collector running.")
        return

    cfg = PaperConfig()
    strategies = ("v1", "v2", "v3")

    for strategy in strategies:
        fold_results = []
        end = minimum

        while end <= len(timestamps):
            window_end = timestamps[end - 1]
            window_df = df[df["timestamp"] <= window_end].copy()

            equity, result = run_paper_backtest(window_df, cfg, strategy)
            if equity is None:
                break

            # Only score the unseen test section after the 61-observation
            # feature warmup.
            test_equity = equity.tail(TEST_SIZE)
            metrics = performance_metrics(
                test_equity["equity"], test_equity["timestamp"]
            )

            fold_results.append(metrics)
            end += TEST_SIZE

        print()
        print(f"{strategy.upper()} — {len(fold_results)} OOS folds")

        if not fold_results:
            print("No complete out-of-sample fold yet.")
            continue

        returns = [x["total_return"] for x in fold_results]
        drawdowns = [x["max_drawdown"] for x in fold_results]
        sharpes = [x["sharpe"] for x in fold_results]

        positive = sum(x > 0 for x in returns)
        print(f"Median fold return: {sorted(returns)[len(returns)//2]:.2%}")
        print(f"Positive folds: {positive}/{len(returns)}")
        print(f"Worst fold drawdown: {min(drawdowns):.2%}")
        print(f"Median Sharpe-like: {sorted(sharpes)[len(sharpes)//2]:.3f}")

        for i, metrics in enumerate(fold_results, start=1):
            print(
                f"  Fold {i}: return={metrics['total_return']:.2%} "
                f"dd={metrics['max_drawdown']:.2%} "
                f"sharpe={metrics['sharpe']:.3f}"
            )

    print()
    print("OUT-OF-SAMPLE PAPER VALIDATION ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
