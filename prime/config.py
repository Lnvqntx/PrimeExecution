"""Configuration.

Secrets and the live switch come from the environment (same variable names as the
original .env, so the existing EC2 .env keeps working). Strategy and risk numbers
live in `Params` below and are changed ONLY through git commits, so every change
to behavior is traceable in the commit history.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv is optional; the EC2 service can also inject real env vars
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

BASE_URL = os.getenv("ROOSTOO_BASE_URL", "https://mock-api.roostoo.com")
QUOTE = "USD"

# Pairs that never move; holding them earns nothing.
STABLE_COINS = frozenset(
    {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "BUSD", "USDP", "PYUSD", "USDD", "USDE", "EUR", "EURI"}
)


@dataclass(frozen=True)
class Params:
    # --- strategy: Phase 0 liquid basket ---
    basket_size: int = 10          # number of coins held
    keep_rank: int = 15            # a held coin stays while it ranks within this
    max_spread_bps: float = 20.0   # eligibility: quoted spread must be tighter than this
    gross: float = 0.30            # fraction of equity invested (rest stays USD)
    max_weight: float = 0.05       # hard cap per coin, fraction of equity

    # --- schedule (all Hong Kong time) ---
    rebalance_hour_hkt: float = 9.0    # daily rebalance, after the first run of each HKT day
    watchdog_hour_hkt: float = 20.0    # if no trade yet today, rebalance again at tighter tolerance

    # --- order sizing / filters ---
    band_usd: float = 100.0        # skip rebalance trades smaller than max(band_usd, band_frac*equity)
    band_frac: float = 0.001
    watchdog_band_usd: float = 25.0
    min_notional_usd: float = 50.0
    watchdog_min_notional_usd: float = 25.0
    dust_usd: float = 10.0         # holdings below this are ignored
    cash_buffer: float = 0.995     # never spend the last 0.5% of free USD (fees)

    # --- risk ---
    dd_half: float = -0.04         # drawdown from peak that halves exposure
    dd_flat: float = -0.08         # drawdown from peak that flattens and cools off
    breaker_hours: float = 12.0

    # --- runtime ---
    poll_seconds: int = 60
    min_call_gap_s: float = 0.25   # client-side throttle between API calls
    max_cycle_errors: int = 10     # consecutive failed cycles before a long pause
    reject_halt_streak: int = 5    # consecutive rejected orders before halting for an hour


@dataclass(frozen=True)
class Settings:
    api_key: str
    secret_key: str
    live_env: bool            # LIVE_TRADING=true in the environment (first of two locks)
    log_dir: Path


def load_settings() -> Settings:
    return Settings(
        api_key=os.getenv("ROOSTOO_API_KEY", ""),
        secret_key=os.getenv("ROOSTOO_SECRET_KEY", ""),
        live_env=os.getenv("LIVE_TRADING", "false").strip().lower() == "true",
        log_dir=Path(os.getenv("PRIME_LOG_DIR", "logs")),
    )
