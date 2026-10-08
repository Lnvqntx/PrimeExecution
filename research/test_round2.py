"""Round 2 research tests: collateralised shorts and the long/short weights (synthetic data, no network)."""
import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from research.backtest import Costs, simulate  # noqa: E402
from research.strategies import phase0_basket, phase0_long_short  # noqa: E402


def _panel(n=200, pairs=("A", "B", "C"), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    rets = rng.normal(0.0, 0.02, size=(n, len(pairs)))
    close = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=list(pairs))
    return close, close * 0 + 1e6

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
