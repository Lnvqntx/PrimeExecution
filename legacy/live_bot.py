"""live_bot.py - Prime Execution autonomous live trader (Roostoo mock exchange).

Strategy (from strategy_v5b.py): cross-sectional mean reversion. Every
REBALANCE_SECONDS, buy the TOP_N worst 24h performers (spread-filtered,
equal-weight, long-only spot, no leverage). Exit when a coin drops out of the
target set, or on a per-position stop-loss.

Risk controls:
  * per-position stop-loss with re-entry cooldown
  * portfolio drawdown circuit breaker (go to cash, cool off)
  * market-wide selloff filter (no new entries when the market is crashing)
  * gross exposure cap, per-position cap, min order size

Usage:
  python live_bot.py --dry --once     # print what it WOULD do, send nothing
  python live_bot.py --live           # real (mock-money) orders, loops forever

Everything is autonomous: no manual API calls, every order is logged to
logs/trades.jsonl with the signal that caused it.
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import statistics
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from config import settings
from roostoo_client import RoostooClient

# ----------------------------- parameters ---------------------------------
POLL_SECONDS = 60
REBALANCE_SECONDS = 3 * 3600
TOP_N = 5
GROSS = 0.60
MAX_POS_W = 0.15
MAX_SPREAD_BPS = 30.0
MIN_LOSS = -0.30
MAX_LOSS = -0.02
MARKET_CRASH_MEDIAN = -0.05
STOP_LOSS = 0.04
COOLDOWN_SECONDS = 24 * 3600
DD_LIMIT = 0.08
BREAKER_SECONDS = 6 * 3600
MIN_TRADE_USD = 100.0
FEE_BUFFER = 0.995
QUOTE = "USD"

STATE_FILE = Path("logs/state.json")
TRADE_LOG = Path("logs/trades.jsonl")
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("logs/bot.log"), logging.StreamHandler()],
)
log = logging.getLogger("prime")

_running = True


def _stop(*_):
    global _running
    _running = False
    log.info("Shutdown signal received; finishing current cycle.")


signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)


# ----------------------------- helpers ------------------------------------
def fnum(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def fmt_qty(qty: float, prec: int) -> str:
    d = Decimal(str(qty)).quantize(Decimal(1).scaleb(-prec), rounding=ROUND_DOWN)
    return format(d, "f")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            log.warning("State file unreadable; starting fresh.")
    return {"entries": {}, "peak": 0.0, "last_rebalance": 0.0,
            "breaker_until": 0.0, "cooldown": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def log_trade(record: dict) -> None:
    with TRADE_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")


def load_meta(client) -> dict:
    info = client.exchange_info()
    meta = {}
    for pair, m in info.get("TradePairs", {}).items():
        if m.get("Unit", QUOTE) != QUOTE:
            continue
        if m.get("CanTrade", True) is False:
            continue
        meta[pair] = {
            "coin": m.get("Coin", pair.split("/")[0]),
            "amt_prec": int(m.get("AmountPrecision", 4)),
            "min_order": fnum(m.get("MiniOrder", 1.0), 1.0),
        }
    return meta


def parse_ticker(client, meta: dict) -> dict:
    data = client.ticker().get("Data", {})
    snap = {}
    for pair, v in data.items():
        if pair not in meta:
            continue
        last, bid, ask = fnum(v.get("LastPrice")), fnum(v.get("MaxBid")), fnum(v.get("MinAsk"))
        if last <= 0 or bid <= 0 or ask <= 0 or ask < bid:
            continue
        mid = (bid + ask) / 2
        snap[pair] = {
            "last": last, "bid": bid, "ask": ask,
            "change": fnum(v.get("Change")),
            "spread_bps": (ask - bid) / mid * 1e4,
        }
    return snap


def get_wallet(client) -> dict:
    bal = client.balance()
    w = bal.get("SpotWallet") or bal.get("Wallet") or {}
    out = {}
    for coin, v in w.items():
        out[coin] = fnum(v.get("Free")) + fnum(v.get("Lock")) if isinstance(v, dict) else fnum(v)
    return out


# ----------------------------- signal -------------------------------------
def pick_targets(snap: dict, cooldown: dict, now: float) -> tuple[dict, str]:
    """Return ({pair: weight}, reason). Swap this function to change strategy."""
    changes = [s["change"] for s in snap.values()]
    if len(changes) < TOP_N:
        return {}, "universe too small"
    med = statistics.median(changes)
    if med < MARKET_CRASH_MEDIAN:
        return {}, f"market selloff filter (median 24h {med:+.2%})"

    cands = [
        (p, s) for p, s in snap.items()
        if MIN_LOSS <= s["change"] <= MAX_LOSS
        and s["spread_bps"] <= MAX_SPREAD_BPS
        and cooldown.get(p, 0) <= now
    ]
    cands.sort(key=lambda x: x[1]["change"])
    chosen = cands[:TOP_N]
    if not chosen:
        return {}, "no qualifying losers"
    w = min(GROSS / TOP_N, MAX_POS_W)
    return {p: w for p, _ in chosen}, f"top-{len(chosen)} 24h losers, median mkt {med:+.2%}"


# ----------------------------- execution ----------------------------------
def send(client, dry, pair, side, qty_str, ref_price, why, state) -> bool:
    rec = {"ts": time.time(), "pair": pair, "side": side, "qty": qty_str,
           "ref_price": ref_price, "why": why, "dry": dry}
    if dry:
        log.info("[DRY] %s %s %s @~%.6f (%s)", side, qty_str, pair, ref_price, why)
        log_trade(rec)
        return True
    try:
        resp = client.place_order(pair, side, qty_str, "MARKET")
    except Exception as e:
        log.error("Order failed %s %s %s: %s", side, qty_str, pair, e)
        rec["error"] = str(e)
        log_trade(rec)
        return False
    rec["response"] = resp
    log_trade(rec)
    ok = bool(resp.get("Success"))
    if not ok:
        log.error("Order rejected %s %s %s: %s", side, qty_str, pair, resp.get("ErrMsg"))
        return False
    detail = resp.get("OrderDetail", {}) or {}
    fill = fnum(detail.get("FilledAverPrice")) or ref_price
    log.info("FILLED %s %s %s @ %.6f (%s)", side, qty_str, pair, fill, why)
    if side == "BUY":
        state["entries"][pair] = fill
    else:
        state["entries"].pop(pair, None)
    return True


def sell_all(client, dry, pair, qty, snap, meta, why, state) -> bool:
    q = fmt_qty(qty, meta[pair]["amt_prec"])
    if fnum(q) <= 0:
        return False
    return send(client, dry, pair, "SELL", q, snap[pair]["bid"], why, state)


def cycle(client, meta, state, dry) -> None:
    now = time.time()
    snap = parse_ticker(client, meta)
    if not snap:
        log.warning("Empty ticker; skipping cycle.")
        return
    wallet = get_wallet(client)
    usd = wallet.get(QUOTE, 0.0)

    holdings = {}
    for pair, m in meta.items():
        qty = wallet.get(m["coin"], 0.0)
        if qty > 0 and pair in snap and qty * snap[pair]["last"] >= 10.0:
            holdings[pair] = qty

    equity = usd + sum(q * snap[p]["last"] for p, q in holdings.items())
    state["peak"] = max(state.get("peak", 0.0), equity)
    dd = equity / state["peak"] - 1.0 if state["peak"] > 0 else 0.0
    log.info("equity=%.2f usd=%.2f positions=%d drawdown=%.2f%%",
             equity, usd, len(holdings), dd * 100)

    # --- circuit breaker: flatten and cool off ---
    if now < state["breaker_until"]:
        return
    if dd <= -DD_LIMIT:
        log.warning("Drawdown %.2f%% hit limit; flattening and cooling off.", dd * 100)
        for pair, qty in holdings.items():
            sell_all(client, dry, pair, qty, snap, meta, "drawdown_breaker", state)
        state["breaker_until"] = now + BREAKER_SECONDS
        state["peak"] = equity
        save_state(state)
        return

    # --- per-position stop-loss ---
    for pair, qty in list(holdings.items()):
        entry = state["entries"].get(pair)
        if entry and snap[pair]["last"] <= entry * (1 - STOP_LOSS):
            if sell_all(client, dry, pair, qty, snap, meta,
                        f"stop_loss entry={entry:.6f}", state):
                state["cooldown"][pair] = now + COOLDOWN_SECONDS
                usd += qty * snap[pair]["bid"]
                holdings.pop(pair)

    # --- scheduled rebalance ---
    if now - state["last_rebalance"] >= REBALANCE_SECONDS:
        targets, reason = pick_targets(snap, state["cooldown"], now)
        log.info("REBALANCE: %s -> %s", reason, list(targets))

        for pair, qty in list(holdings.items()):
            if pair not in targets:
                if sell_all(client, dry, pair, qty, snap, meta,
                            f"exit_not_in_targets ({reason})", state):
                    usd += qty * snap[pair]["bid"]
                    holdings.pop(pair)

        for pair, w in targets.items():
            have = holdings.get(pair, 0.0) * snap[pair]["last"]
            want = w * equity
            need = want - have
            if need < max(MIN_TRADE_USD, 0.5 * want):
                continue
            spend = min(need, usd * FEE_BUFFER)
            if spend < max(MIN_TRADE_USD, meta[pair]["min_order"]):
                continue
            qty = spend / snap[pair]["ask"]
            q = fmt_qty(qty, meta[pair]["amt_prec"])
            if fnum(q) <= 0:
                continue
            if send(client, dry, pair, "BUY", q, snap[pair]["ask"],
                    f"entry 24h={snap[pair]['change']:+.2%} ({reason})", state):
                usd -= spend

        state["last_rebalance"] = now

    save_state(state)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="send real orders")
    ap.add_argument("--dry", action="store_true", help="log intended orders only")
    ap.add_argument("--once", action="store_true", help="run a single cycle")
    args = ap.parse_args()
    dry = not args.live or args.dry

    if not settings.api_key or not settings.secret_key:
        raise RuntimeError("Roostoo API credentials missing from .env")
    client = RoostooClient(settings.api_key, settings.secret_key)
    meta = load_meta(client)
    log.info("Loaded %d tradable %s pairs. MODE=%s", len(meta), QUOTE, "DRY" if dry else "LIVE")

    state = load_state()
    backoff = POLL_SECONDS
    while _running:
        try:
            cycle(client, meta, state, dry)
            backoff = POLL_SECONDS
        except Exception as e:
            log.exception("Cycle error: %s", e)
            backoff = min(backoff * 2, 600)
        if args.once:
            break
        for _ in range(int(backoff)):
            if not _running:
                break
            time.sleep(1)
    log.info("Bot stopped.")


if __name__ == "__main__":
    main()
