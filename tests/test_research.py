"""Research backtester sanity checks (synthetic data only, no network)."""
import math

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from research.backtest import Costs, metrics, score, simulate  # noqa: E402
from research.strategies import CANDIDATES, ts_trend, xs_momentum  # noqa: E402
from research.run import perturbations  # noqa: E402


def _panel(n=200, pairs=("A", "B", "C"), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    rets = rng.normal(0.0, 0.02, size=(n, len(pairs)))
    close = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=list(pairs))
    return close, close * 0 + 1e6


def test_score_weights():
    assert score(1.0, 2.0, 3.0) == pytest.approx(0.4 + 0.6 + 0.9)


def test_buy_and_hold_matches_price_and_charges_entry_cost_once():
    close, _ = _panel()
    w = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    w.iloc[0] = [1.0, 0.0, 0.0]
    costs = Costs(fee=0.001, default_half_spread=0.0005)
    sim = simulate(close, w, costs)
    assert sim["cost"].iloc[0] == pytest.approx(0.0015)
    assert sim["cost"].iloc[1:].sum() == 0
    eq = (1 + sim["net"]).prod()
    assert eq == pytest.approx(close["A"].iloc[-1] / close["A"].iloc[0] * (1 - 0.0015))


def test_weights_earn_next_day_return_not_same_day():
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    close = pd.DataFrame({"A": [100.0, 200.0, 200.0]}, index=idx)
    w = pd.DataFrame({"A": [np.nan, 1.0, 1.0]}, index=idx)  # decide at close of day 2
    sim = simulate(close, w, Costs(fee=0.0, default_half_spread=0.0))
    assert sim["gross"].tolist() == [0.0, 0.0, 0.0]  # the day-2 jump is not captured


def test_cost_multiplier_and_no_leverage():
    close, _ = _panel()
    w = pd.DataFrame(1.0, index=close.index, columns=close.columns)  # asks for 300% gross
    sim1 = simulate(close, w, Costs(mult=1.0))
    sim2 = simulate(close, w, Costs(mult=2.0))
    assert sim2["cost"].sum() == pytest.approx(2 * sim1["cost"].sum())
    assert sim1["turnover"].iloc[0] == pytest.approx(1.0)


def test_delisted_pair_is_sold():
    close, _ = _panel(n=20)
    close.iloc[10:, 1] = np.nan
    w = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    w.iloc[0] = [0.0, 1.0, 0.0]
    sim = simulate(close, w, Costs())
    assert sim["turnover"].iloc[10] == pytest.approx(1.0)
    assert sim["gross"].iloc[11:].abs().sum() == 0


def test_metrics_on_known_series():
    r = pd.Series([0.01, -0.01] * 50)
    m = metrics(r)
    assert m["sharpe"] == pytest.approx(r.mean() / r.std() * math.sqrt(365), abs=1e-3)
    assert m["maxdd"] < 0 and m["days"] == 100


def test_strategies_are_causal():
    """Changing future prices must not change past weights."""
    close, vol = _panel(n=150)
    future = close.copy()
    future.iloc[120:] *= 3.0
    for fn, grid in CANDIDATES.values():
        a = fn(close, vol, **grid[0]).iloc[:120]
        b = fn(future, vol, **grid[0]).iloc[:120]
        pd.testing.assert_frame_equal(a, b)


def test_strategies_long_only_unlevered():
    close, vol = _panel(n=150, pairs=tuple("ABCDEFGHIJKL"))
    for fn, grid in CANDIDATES.values():
        for g in grid:
            w = fn(close, vol, **g).dropna(how="all")
            assert (w.fillna(0) >= 0).all().all()
            assert (w.sum(axis=1) <= 1 + 1e-9).all()


def test_xs_momentum_picks_top_k():
    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    close = pd.DataFrame({"A": [1, 1, 1, 1, 2.0], "B": [1, 1, 1, 1, 1.5], "C": [1, 1, 1, 1, 0.5]}, index=idx)
    w = xs_momentum(close, close, lookback=2, top_k=2).iloc[-1]
    assert w.to_dict() == {"A": 0.5, "B": 0.5, "C": 0.0}


def test_ts_trend_cash_when_below_average():
    idx = pd.date_range("2025-01-01", periods=4, freq="D")
    close = pd.DataFrame({"A": [4, 3, 2, 1.0], "B": [1, 2, 3, 4.0]}, index=idx)
    w = ts_trend(close, close, lookback=3).iloc[-1]
    assert w.to_dict() == {"A": 0.0, "B": 0.5}


def test_perturbations_skip_basket_size():
    assert perturbations({"lookback": 20, "top_k": 5}, 0.3) == [{"lookback": 14, "top_k": 5}, {"lookback": 26, "top_k": 5}]


# ---- round 2: collateralised shorts ----
from research.strategies import phase0_basket, phase0_long_short  # noqa: E402


def _one(prices, w0, **kw):
    idx = pd.date_range("2025-01-01", periods=len(prices), freq="D")
    close = pd.DataFrame({"A": prices}, index=idx)
    w = pd.DataFrame({"A": [w0] + [np.nan] * (len(prices) - 1)}, index=idx)
    return simulate(close, w, Costs(fee=0.0, default_half_spread=0.0, **kw), allow_short=True)


def test_short_profits_when_price_falls():
    sim = _one([100.0, 90.0], -0.5)
    assert sim["gross"].iloc[1] == pytest.approx(0.05)


def test_long_only_default_still_clips_shorts():
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    close = pd.DataFrame({"A": [100.0, 90.0]}, index=idx)
    w = pd.DataFrame({"A": [-0.5, np.nan]}, index=idx)
    assert simulate(close, w, Costs())["gross"].abs().sum() == 0


def test_short_liquidated_at_twice_entry():
    sim = _one([100.0, 150.0, 200.0, 400.0], -0.5)
    assert sim["liquidations"].tolist() == [0, 0, 1, 0]
    assert sim["gross"].iloc[3] == 0  # closed, no further loss
    eq = (1 + sim["net"]).prod()
    assert eq == pytest.approx(0.5)  # lost exactly the posted collateral


def test_gross_capped_by_absolute_weights():
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    close = pd.DataFrame({"A": [1.0, 1.0], "B": [1.0, 1.0]}, index=idx)
    w = pd.DataFrame({"A": [1.0, np.nan], "B": [-1.0, np.nan]}, index=idx)
    sim = simulate(close, w, Costs(fee=0.0, default_half_spread=0.0), allow_short=True)
    assert sim["turnover"].iloc[0] == pytest.approx(1.0)


def test_borrow_fee_accrues_on_short_notional():
    sim = _one([100.0, 100.0, 100.0], -0.5, borrow_annual=0.365)
    assert sim["cost"].iloc[1] == pytest.approx(0.5 * 0.001)


def test_long_short_weights_are_collateralised_and_disjoint():
    close, vol = _panel(n=120, pairs=tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), seed=1)
    w = phase0_long_short(close, vol, lookback=14).dropna(how="all")
    assert (w.abs().sum(axis=1) - 1.0).abs().max() < 1e-9
    assert w.sum(axis=1).abs().max() < 1e-9  # dollar neutral
    longs = phase0_basket(close, vol, gross=1.0).reindex(w.index) > 0
    assert not ((w < 0) & longs).any().any()
    assert ((w < 0).sum(axis=1) == 10).all()


def test_long_short_is_causal():
    close, vol = _panel(n=120, pairs=tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), seed=2)
    fut_c, fut_v = close.copy(), vol.copy()
    fut_c.iloc[100:] *= 3.0
    fut_v.iloc[100:] *= 5.0
    pd.testing.assert_frame_equal(phase0_long_short(close, vol, 14).iloc[:100],
                                  phase0_long_short(fut_c, fut_v, 14).iloc[:100])
