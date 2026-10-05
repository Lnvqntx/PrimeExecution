from __future__ import annotations

from paper_engine import PaperConfig, run_paper_backtest
from features import load_snapshots


def main():
    df = load_snapshots("data/ticker_snapshots.csv")

    print("=" * 78)
    print("PRIME EXECUTION — V1 vs V2 PAPER COMPARISON")
    print("=" * 78)

    results = {}
    for strategy in ("v1", "v2"):
        _, result = run_paper_backtest(df, PaperConfig(), strategy)
        if "error" in result:
            print(result["error"])
            print("Keep the collector running until 61+ snapshots exist.")
            return
        results[strategy] = result

    print()
    print(f"{'Metric':<20} {'V1':>12} {'V2':>12} {'V2-V1':>12}")
    print("-" * 58)

    for key, formatter in (
        ("total_return", lambda x: f"{x:.2%}"),
        ("max_drawdown", lambda x: f"{x:.2%}"),
        ("sharpe", lambda x: f"{x:.3f}"),
        ("sortino", lambda x: f"{x:.3f}"),
    ):
        v1 = results["v1"][key]
        v2 = results["v2"][key]
        print(f"{key:<20} {formatter(v1):>12} {formatter(v2):>12} {formatter(v2-v1):>12}")

    print()
    print(f"V1 simulated trades: {results['v1']['trades']}")
    print(f"V2 simulated trades: {results['v2']['trades']}")
    print()
    print("PAPER SIMULATION ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
