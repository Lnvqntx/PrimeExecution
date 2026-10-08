from __future__ import annotations

import pandas as pd

from features import load_snapshots


def main():
    df = load_snapshots("data/ticker_snapshots.csv")

    print("=" * 78)
    print("PRIME EXECUTION — MARKET DATA QUALITY CHECK")
    print("=" * 78)

    if df.empty:
        print("No data.")
        return

    timestamps = sorted(df["timestamp"].unique())
    pair_counts = df.groupby("timestamp")["pair"].nunique()

    invalid_price = int((df["last_price"] <= 0).sum())
    invalid_bid = int((df["bid"] <= 0).sum())
    invalid_ask = int((df["ask"] <= 0).sum())
    crossed = int((df["bid"] > df["ask"]).sum())
    duplicate_rows = int(df.duplicated(["timestamp", "pair"]).sum())

    gaps = pd.Series(timestamps).diff().dropna().dt.total_seconds()
    gap_count = int((gaps > 90).sum()) if not gaps.empty else 0

    print(f"Snapshots: {len(timestamps)}")
    print(f"Rows: {len(df)}")
    print(f"Unique pairs: {df['pair'].nunique()}")
    print(f"Expected pairs/snapshot: 86")
    print(f"Minimum pairs in a snapshot: {pair_counts.min()}")
    print(f"Maximum pairs in a snapshot: {pair_counts.max()}")
    print(f"Duplicate timestamp/pair rows: {duplicate_rows}")
    print(f"Non-positive last prices: {invalid_price}")
    print(f"Non-positive bids: {invalid_bid}")
    print(f"Non-positive asks: {invalid_ask}")
    print(f"Crossed markets (bid > ask): {crossed}")
    print(f"Collection gaps >90s: {gap_count}")

    if not gaps.empty:
        print(f"Median interval: {gaps.median():.1f}s")
        print(f"Max interval: {gaps.max():.1f}s")

    print()
    healthy = (
        duplicate_rows == 0
        and invalid_price == 0
        and invalid_bid == 0
        and invalid_ask == 0
        and crossed == 0
        and gap_count == 0
    )
    print("STATUS:", "HEALTHY" if healthy else "CHECK WARNINGS")
    print("RESEARCH ONLY — NO ORDERS ARE GENERATED.")


if __name__ == "__main__":
    main()
