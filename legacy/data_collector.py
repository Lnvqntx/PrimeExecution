from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone

from config import settings
from roostoo_client import RoostooClient

DATA_DIR = "data"
SNAPSHOT_FILE = os.path.join(DATA_DIR, "ticker_snapshots.csv")

FIELDS = [
    "timestamp",
    "pair",
    "last_price",
    "bid",
    "ask",
    "change_24h",
    "coin_trade_value",
    "unit_trade_value",
]


def collect_snapshot(client: RoostooClient):
    response = client.ticker()
    timestamp = datetime.now(timezone.utc).isoformat()
    rows = []

    for pair, values in response.get("Data", {}).items():
        rows.append(
            {
                "timestamp": timestamp,
                "pair": pair,
                "last_price": values.get("LastPrice"),
                "bid": values.get("MaxBid"),
                "ask": values.get("MinAsk"),
                "change_24h": values.get("Change"),
                "coin_trade_value": values.get("CoinTradeValue"),
                "unit_trade_value": values.get("UnitTradeValue"),
            }
        )

    return rows


def append_rows(rows):
    if not rows:
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    exists = os.path.exists(SNAPSHOT_FILE)

    with open(SNAPSHOT_FILE, "a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def main():
    if not settings.api_key or not settings.secret_key:
        raise RuntimeError("Roostoo API credentials are missing from .env")

    client = RoostooClient(settings.api_key, settings.secret_key)

    print("PRIME EXECUTION — MARKET DATA COLLECTOR")
    print(f"Interval: {settings.poll_interval_seconds}s")
    print(f"Output: {SNAPSHOT_FILE}")
    print("Press Ctrl+C to stop.")

    while True:
        started = time.time()

        try:
            rows = collect_snapshot(client)
            append_rows(rows)
            print(
                f"{datetime.now().strftime('%H:%M:%S')} "
                f"collected {len(rows)} pairs"
            )
        except Exception as exc:
            print(f"collector error: {type(exc).__name__}: {exc}")

        elapsed = time.time() - started
        time.sleep(max(1, settings.poll_interval_seconds - elapsed))


if __name__ == "__main__":
    main()
