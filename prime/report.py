"""Read-only status report from the bot's own logs.

    python -m prime.report

Shows which Hong Kong days count as ACTIVE (at least one filled live order), so you
can verify the 8-day requirement yourself, plus the latest equity and last orders.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

from .clock import hkt_day, hkt_dt


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def main() -> int:
    log_dir = Path(os.getenv("PRIME_LOG_DIR", "logs"))
    orders, equity = _rows(log_dir / "orders.jsonl"), _rows(log_dir / "equity.jsonl")
    filled = [o for o in orders if o.get("outcome") == "filled" and o.get("live")]
    per_day = Counter(hkt_day(o["ts"]) for o in filled)

    print(f"ACTIVE DAYS (Hong Kong time, >=1 filled live order): {len(per_day)} of 8 needed")
    for day in sorted(per_day):
        print(f"  {day}: {per_day[day]} fills")
    if equity:
        last, first = equity[-1], equity[0]
        print(f"\nEquity now: {last['equity']:,.2f}  (first logged: {first['equity']:,.2f}, "
              f"return {last['equity'] / first['equity'] - 1:+.2%})")
        print(f"Peak: {last['peak']:,.2f}  drawdown: {last['drawdown']:+.2%}  positions: {last['positions']}  "
              f"as of {hkt_dt(last['ts']).strftime('%Y-%m-%d %H:%M')} HKT")
    slips = [o["slippage_bps"] for o in filled if o.get("slippage_bps") is not None]
    if slips:
        print(f"Avg slippage vs quote: {sum(slips) / len(slips):+.2f} bps over {len(slips)} fills")
    fees = {o.get("commission_pct") for o in filled if o.get("commission_pct") is not None}
    if fees:
        print(f"Commission percent seen in fills: {sorted(fees)}")
    print("\nLast orders:")
    for o in orders[-5:]:
        print(f"  {hkt_dt(o['ts']).strftime('%m-%d %H:%M')} {o.get('outcome'):9s} {o.get('side')} {o.get('qty')} {o.get('pair')}")
    errs = _rows(log_dir / "errors.jsonl")
    if errs:
        print(f"\nCycle errors logged: {len(errs)} (latest: {errs[-1].get('error')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
