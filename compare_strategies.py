from __future__ import annotations

from paper_engine import PaperConfig, run_paper_backtest
from features import load_snapshots


def main():
    df = load_snapshots("data/ticker_snapshots.csv")

    print("=" * 86)
    print("PRIME EXECUTION — V1 / V2 / V3 PAPER COMPARISON")
    print("=" * 86)

    results = {}
    for strategy in ("v1", "v2", "v3"):
        _, result = run_paper_backtest(df, PaperConfig(), strategy)
        if "error" in result:
            print(result["error"])
            print("Keep the collector running until more history is available.")
            return
        results[strategy] = result

    print()
    print(f"{'Metric':<20} {'V1':>12} {'V2':>12} {'V3':>12}")
    print("-" * 60)

    for key, formatter in (
        ("total_return", lambda x: f"{x:.2%}"),
        ("max_drawdown", lambda x: f"{x:.2%}"),
        ("sharpe", lambda x: f"{x:.3f}"),
        ("sortino", lambda x: f"{x:.3f}"),
        ("calmar", lambda x: f"{x:.3f}"),
    ):
        print(
            f"{key:<20}"
            f"{formatter(results['v1'][key]):>12}"
            f"{formatter(results['v2'][key]):>12}"
            f"{formatter(results['v3'][key]):>12}"
        )

    print()
    for strategy in ("v1", "v2", "v3"):
        print(f"{strategy.upper()} simulated trades: {results[strategy]['trades']}")

    print()
    print("PAPER SIMULATION ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
