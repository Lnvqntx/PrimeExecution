"""End-to-end tests of the trading loop against the fake exchange."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from prime.bot import Bot, DataError
from prime.clock import HKT
from prime.config import Params
from prime.journal import Journal
from prime.state import State
from prime.strategy import LiquidBasket
from tests.fake_exchange import FakeExchange


def hkt(day: int, hour: float) -> float:
    """Timestamp for 2026-10-<day> at <hour> HKT."""
    h, m = int(hour), int(round((hour - int(hour)) * 60))
    return datetime(2026, 10, day, h, m, tzinfo=HKT).timestamp()


class Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t


@pytest.fixture
def env(tmp_path):
    ex = FakeExchange()
    clock = Clock(hkt(9, 8.0))
    st_path = tmp_path / "state.json"
    bot = Bot(ex, Params(), LiquidBasket(), Journal(tmp_path), State(), st_path, live=True, clock=clock)
    bot.metas = __import__("prime.market", fromlist=["x"]).parse_exchange_info(ex.exchange_info())
    bot.metas_day = "2026-10-09"
    return ex, bot, clock, tmp_path


def read(path, stream):
    f = path / f"{stream}.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def test_first_cycle_buys_ten_liquid_coins_at_target_gross(env):
    ex, bot, clock, tmp = env
    out = bot.cycle()
    assert out["traded"]
    held = {c for c, q in ex.coins.items() if q > 0}
    assert len(held) == 10 and "USDC" not in held            # stablecoin is never bought
    invested = sum(q * ex.bid(f"{c}/USD") for c, q in ex.coins.items())
    assert invested / ex.equity() == pytest.approx(0.30, abs=0.01)
    assert all(q * ex.bid(f"{c}/USD") / ex.equity() <= 0.05 + 1e-3 for c, q in ex.coins.items())
    assert bot.state.last_trade_day == "2026-10-09"
    assert len(read(tmp, "orders")) == 10 and all(o["outcome"] == "filled" for o in read(tmp, "orders"))


def test_second_cycle_same_day_does_nothing(env):
    ex, bot, clock, tmp = env
    bot.cycle()
    n = len(ex.orders)
    clock.t += 60
    assert bot.cycle()["action"] == "none"
    assert len(ex.orders) == n


def test_next_day_rebalances_from_09_hkt_not_before(env):
    ex, bot, clock, tmp = env
    bot.cycle()
    ex.move(1.03)
    held = next(c for c, q in ex.coins.items() if q > 0)
    ex.px[f"{held}/USD"] *= 1.25                   # force real drift on a coin we hold
    clock.t = hkt(10, 8.0)
    assert bot.cycle()["action"] == "none"         # before 09:00 HKT
    clock.t = hkt(10, 9.0)
    out = bot.cycle()
    assert out["action"] == "daily rebalance" and out["traded"]
    assert bot.state.last_trade_day == "2026-10-10"


def test_watchdog_sends_nothing_when_already_on_target(env):
    ex, bot, clock, tmp = env
    bot.cycle()
    clock.t = hkt(10, 9.0)
    bot.cycle()                                    # day-10 rebalance: portfolio already on target, no orders
    n = len(ex.orders)
    clock.t = hkt(10, 20.0)
    out = bot.cycle()
    assert out["action"].startswith("watchdog") and not out["traded"]
    assert len(ex.orders) == n                     # never invents a trade
    assert bot.state.watchdog_day == "2026-10-10"
    clock.t = hkt(10, 21.0)
    assert bot.cycle()["action"] == "none"         # runs once per day


def test_watchdog_trades_small_real_drift_the_daily_band_skipped(env):
    ex, bot, clock, tmp = env
    bot.cycle()
    held = next(c for c, q in ex.coins.items() if q > 0)
    ex.px[f"{held}/USD"] *= 1.017                  # ~$50 of drift on a ~$3000 position
    clock.t = hkt(10, 9.0)
    assert not bot.cycle()["traded"]               # below the $100 daily band
    clock.t = hkt(10, 20.0)
    out = bot.cycle()
    assert out["action"].startswith("watchdog") and out["traded"]
    assert bot.state.last_trade_day == "2026-10-10"


def test_drawdown_flattens_then_stays_flat_then_rebuilds(env):
    ex, bot, clock, tmp = env
    bot.cycle()
    ex.move(0.60)                                   # basket -40% => about -12% equity
    clock.t += 60
    out = bot.cycle()
    assert out["action"].startswith("flatten")
    assert sum(q * ex.bid(f"{c}/USD") for c, q in ex.coins.items()) < 20     # only dust left
    n = len(ex.orders)
    clock.t += 3600
    assert bot.cycle()["action"] == "none" and len(ex.orders) == n           # cool-off holds
    clock.t = hkt(10, 9.0)                                                    # breaker (12h) has expired
    out = bot.cycle()
    assert out["action"] == "daily rebalance" and out["traded"]
    invested = sum(q * ex.bid(f"{c}/USD") for c, q in ex.coins.items())
    assert invested / ex.equity() == pytest.approx(0.30, abs=0.02)


def test_half_exposure_at_minus_four_percent(env):
    ex, bot, clock, tmp = env
    bot.cycle()
    ex.move(0.86)                                   # basket -14% => about -4.2% equity
    clock.t += 60
    out = bot.cycle()
    assert "half exposure" in out["action"]
    invested = sum(q * ex.bid(f"{c}/USD") for c, q in ex.coins.items())
    assert invested / ex.equity() == pytest.approx(0.15, abs=0.02)


def test_rejects_are_retried_then_halt_for_an_hour(env):
    ex, bot, clock, tmp = env
    ex.fail_next = ["reject"] * 5
    out = bot.cycle()
    assert [o["outcome"] for o in read(tmp, "orders")] == ["rejected"] * 3     # batch stops after 3 in a row
    assert ex.orders == [] and bot.state.last_rebalance_day == ""              # NOT marked done: will retry
    clock.t += 60
    bot.cycle()                                                                # retry: 2 more rejects, rest fill
    assert len(ex.orders) >= 7 and bot.state.halted_until > clock.t            # 5 rejects in total -> halt 1h
    n = len(ex.orders)
    clock.t += 600
    assert bot.cycle()["action"] == "halted" and len(ex.orders) == n


def test_uncertain_order_stops_batch_and_next_cycle_reconciles(env):
    ex, bot, clock, tmp = env
    ex.fail_next = ["uncertain-applied"]            # first order lands but the reply is lost
    bot.cycle()
    assert len(ex.orders) == 1                      # batch stopped after the uncertain order
    assert bot.state.last_rebalance_day == ""       # trigger retried next cycle
    clock.t += 60
    bot.cycle()                                     # rebuilds from the real balance: no double buy
    held = {c: q for c, q in ex.coins.items() if q > 0}
    assert len(held) == 10
    first = ex.orders[0]
    assert sum(1 for o in ex.orders if o["pair"] == first["pair"] and o["side"] == "BUY") == 1


def test_thin_ticker_refuses_to_trade(env):
    ex, bot, clock, tmp = env
    ex.pairs = ex.pairs[:5]
    with pytest.raises(DataError):
        bot.cycle()


def test_dry_mode_sends_no_orders(env):
    ex, bot, clock, tmp = env
    bot.live = False
    bot.executor.live = False
    bot.cycle()
    assert ex.orders == [] and bot.state.last_trade_day == ""


def test_state_survives_restart(env):
    ex, bot, clock, tmp = env
    bot.cycle()
    reloaded = State.load(bot.state_path)
    assert reloaded.last_rebalance_day == "2026-10-09" and reloaded.peak_equity > 0


def test_cli_needs_both_locks_to_go_live(monkeypatch, tmp_path):
    import prime.bot as botmod
    from prime.config import Settings
    seen = {}

    class Stub:
        def preflight(self): pass
        def cycle(self): return {}

    def fake_build(settings, live, state_file=None):
        seen["live"] = live
        return Stub()

    monkeypatch.setattr(botmod, "build_bot", fake_build)
    for env_flag, cli, expect in [(False, True, False), (True, False, False), (True, True, True)]:
        monkeypatch.setattr(botmod, "load_settings",
                            lambda f=env_flag: Settings("k", "s", f, tmp_path))
        argv = ["--once"] + (["--live"] if cli else [])
        assert botmod.main(argv) == 0 and seen["live"] is expect
