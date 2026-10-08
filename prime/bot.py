"""The trading loop.

One cycle = fetch ticker -> reconcile with the exchange -> risk check -> (maybe)
plan and execute -> journal. All scheduling uses Hong Kong time because that is how
the competition counts trading days.

Trading triggers, in order of priority:
  1. flatten    : drawdown breaker says go to cash
  2. rebalance  : first cycle of each HKT day (immediately on the very first run,
                  otherwise from `rebalance_hour_hkt`), or a drawdown scale change
  3. watchdog   : from `watchdog_hour_hkt`, if no order has filled yet today, one more
                  genuine rebalance at a tighter tolerance. It never invents trades:
                  if the portfolio is already on target, nothing is sent.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .client import ApiError, RoostooClient
from .clock import hkt_day, hkt_hour
from .config import Params, Settings, load_settings
from .executor import Executor
from .journal import Journal, setup_logging
from .market import PairMeta, parse_exchange_info, parse_ticker
from .planner import plan_orders
from .portfolio import build_snapshot
from .risk import RiskEngine
from .state import State
from .strategy import LiquidBasket, Strategy

log = logging.getLogger("prime")


class DataError(Exception):
    pass


class Bot:
    def __init__(self, client, params: Params, strategy: Strategy, journal: Journal,
                 state: State, state_path: Path, live: bool, clock=time.time):
        self.client = client
        self.p = params
        self.strategy = strategy
        self.journal = journal
        self.state = state
        self.state_path = Path(state_path)
        self.live = live
        self.clock = clock
        self.risk = RiskEngine(params)
        self.executor = Executor(client, journal, live, reject_stop=3)
        self.metas: dict[str, PairMeta] = {}
        self.metas_day = ""

    # ------------------------------------------------------------------ setup
    def preflight(self) -> None:
        skew = abs(self.client.server_time() - int(self.clock() * 1000)) / 1000.0
        log.info("clock skew vs exchange: %.1fs", skew)
        if skew > 30:
            raise RuntimeError(f"local clock is {skew:.0f}s off the exchange; signed requests will be rejected")
        info = self.client.exchange_info()
        if not info.get("IsRunning", True):
            raise RuntimeError("exchange reports IsRunning=false")
        self._load_metas(info)
        bal = self.client.balance()          # fails fast on bad credentials
        log.info("preflight ok: %d USD pairs, wallet=%s", len(self.metas),
                 {k: v for k, v in (bal.get("Wallet") or {}).items() if (v.get("Free") or v.get("Lock"))})

    def _load_metas(self, info: dict | None = None) -> None:
        info = info or self.client.exchange_info()
        self.metas = parse_exchange_info(info)
        self.metas_day = hkt_day(self.clock())

    # ------------------------------------------------------------------ one cycle
    def cycle(self) -> dict:
        now = self.clock()
        day, hour = hkt_day(now), hkt_hour(now)
        st = self.state
        if day != self.metas_day:
            self._load_metas()

        quotes = parse_ticker(self.client.ticker(), self.metas)
        if len(quotes) < 10:
            raise DataError(f"only {len(quotes)} valid quotes; refusing to trade on thin data")
        snap = build_snapshot(self.client.balance(), self.metas, quotes, self.p)
        if snap.equity <= 0:
            raise DataError("equity <= 0 from balance; refusing to trade")

        rd = self.risk.update(snap.equity, now, st)
        self.journal.write("equity", equity=round(snap.equity, 2), usd=round(snap.usd_free, 2),
                           invested=round(snap.invested, 2), positions=len(snap.holdings),
                           peak=round(st.peak_equity, 2), drawdown=round(rd.drawdown, 5), risk=rd.reason,
                           unknown_coins=snap.unknown_coins or None)

        if now < st.halted_until:
            log.warning("trading halted until %s (order rejects)", hkt_day(st.halted_until))
            self._save()
            return {"action": "halted"}

        # ---- decide whether to trade this cycle
        reason, band, band_frac, min_notional, mark = None, self.p.band_usd, self.p.band_frac, self.p.min_notional_usd, None
        if rd.flatten:
            if snap.holdings:
                reason = f"flatten: {rd.reason}"
        elif st.last_rebalance_day != day and (st.last_rebalance_day == "" or hour >= self.p.rebalance_hour_hkt):
            reason, mark = "daily rebalance", "rebalance"
        elif rd.scale != st.last_scale:
            reason, mark = f"risk scale {st.last_scale} -> {rd.scale}: {rd.reason}", "scale"
        elif hour >= self.p.watchdog_hour_hkt and st.last_trade_day != day and st.watchdog_day != day:
            reason, mark = "watchdog: no fill yet today, tighter tolerance", "watchdog"
            band, band_frac, min_notional = self.p.watchdog_band_usd, 0.0, self.p.watchdog_min_notional_usd

        if reason is None:
            self._save()
            return {"action": "none", "equity": snap.equity}

        # ---- targets -> orders
        held = set(snap.holdings)
        raw = {} if rd.flatten else self.strategy.targets(quotes, self.metas, held, self.p)
        targets = self.risk.clamp(raw, rd.scale)
        orders = plan_orders(targets, snap, quotes, self.metas, self.p,
                             min_notional=min_notional, band_usd=band, band_frac=band_frac, reason=reason)
        log.info("TRADE CYCLE (%s): %d targets, %d orders, equity=%.2f", reason, len(targets), len(orders), snap.equity)
        self.journal.write("decisions", strategy=self.strategy.name, reason=reason, equity=round(snap.equity, 2),
                           risk_scale=rd.scale, targets={p: round(w, 5) for p, w in targets.items()},
                           orders=[f"{o.side} {o.qty_str} {o.pair} ~${o.notional:.0f}" for o in orders],
                           spreads_bps={p: round(quotes[p].spread_bps, 2) for p in targets if p in quotes})

        result = self.executor.run(orders, tag=mark or "flatten")
        if result.uncertain:
            log.error("uncertain order outcome; next cycle reconciles from the exchange balance")
        if result.rejects:
            st.reject_streak += result.rejects
            if st.reject_streak >= self.p.reject_halt_streak:
                st.halted_until = now + 3600.0
                st.reject_streak = 0
                log.error("too many rejected orders; halting trading for 1 hour")
        elif result.traded:
            st.reject_streak = 0

        if self.live and result.traded:
            st.last_trade_day = day
        if not result.uncertain and not result.rejects:   # on uncertainty or rejects, retry the trigger next cycle
            if mark == "rebalance":
                st.last_rebalance_day = day
            elif mark == "watchdog":
                st.watchdog_day = day
            if mark in ("rebalance", "scale"):
                st.last_scale = rd.scale
        self._save()
        return {"action": reason, "orders": len(orders), "traded": result.traded, "equity": snap.equity}

    def _save(self) -> None:
        self.state.save(self.state_path)

    # ------------------------------------------------------------------ loop
    def run_forever(self) -> None:
        errors = 0
        while True:
            try:
                self.cycle()
                errors = 0
                pause = self.p.poll_seconds
            except Exception as e:  # never die; back off, keep the service alive
                errors += 1
                log.exception("cycle error #%d: %s", errors, e)
                self.journal.write("errors", n=errors, error=repr(e))
                pause = min(self.p.poll_seconds * 2 ** min(errors, 4), 900)
                if errors >= self.p.max_cycle_errors:
                    log.critical("%d consecutive failed cycles; pausing 15 minutes", errors)
                    pause = 900
            time.sleep(pause)


# ---------------------------------------------------------------------- entrypoint
def build_bot(settings: Settings, live: bool, state_file: Path | None = None) -> Bot:
    params = Params()
    journal = Journal(settings.log_dir)
    client = RoostooClient(settings.api_key, settings.secret_key, min_gap=params.min_call_gap_s)
    default_state = settings.log_dir / ("state.json" if live else "state.dry.json")
    state_path = Path(state_file) if state_file else default_state
    return Bot(client, params, LiquidBasket(), journal, State.load(state_path), state_path, live)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prime", description="Prime Execution trading bot")
    ap.add_argument("--live", action="store_true", help="send real orders (also requires LIVE_TRADING=true)")
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    ap.add_argument("--state-file", default=None)
    args = ap.parse_args(argv)

    settings = load_settings()
    setup_logging(settings.log_dir)
    if not settings.api_key or not settings.secret_key:
        log.error("ROOSTOO_API_KEY / ROOSTOO_SECRET_KEY missing from the environment")
        return 2
    live = args.live and settings.live_env
    if args.live and not settings.live_env:
        log.error("--live given but LIVE_TRADING is not 'true' in the environment: refusing, running DRY instead")
    log.info("starting Prime Execution, mode=%s", "LIVE" if live else "DRY")

    bot = build_bot(settings, live, Path(args.state_file) if args.state_file else None)
    try:
        bot.preflight()
    except (ApiError, RuntimeError) as e:
        log.error("preflight failed: %s", e)
        return 3
    if args.once:
        print(bot.cycle())
        return 0
    bot.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
