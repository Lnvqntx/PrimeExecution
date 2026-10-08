from __future__ import annotations

import argparse

from features import build_features, latest_cross_section, load_snapshots


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data",
        default="data/ticker_snapshots.csv",
        help="Path to ticker snapshot CSV",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of candidates to display",
    )
    args = parser.parse_args()

    df = load_snapshots(args.data)
    if df.empty:
        print("No market data yet.")
        return

    features = build_features(df)
    latest = latest_cross_section(features)

    print("=" * 78)
    print("PRIME EXECUTION — CROSS-SECTIONAL RESEARCH SNAPSHOT")
    print("=" * 78)
    print(f"Latest timestamp: {features['timestamp'].max()}")
    print(f"Pairs observed: {features['pair'].nunique()}")
    print()

    columns = [
        "pair",
        "last_price",
        "ret_15",
        "ret_60",
        "vol_60",
        "trend",
        "spread_bps",
        "risk_adjusted_momentum",
    ]

    print(latest[columns].head(args.top).to_string(index=False))
    print()
    print("RESEARCH ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
