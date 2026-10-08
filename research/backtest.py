"""Daily long-only portfolio simulator and performance metrics (research only).

Timing: a strategy sees closes up to and including day t and returns target weights.
Those weights are traded at the close of day t and earn the close-to-close return of
day t+1. Between rebalances the weights drift with prices. Costs on each rebalance are
sum_i |w_target_i - w_drifted_i| * (fee + half_spread_i) * cost_mult.

A pair whose data ends (delisting) is sold at its last close: its return is 0 after that
and its weight is forced to 0 at the next rebalance (and charged as turnover).

Shorts (research only; the live bot is spot long-only, CLAUDE.md rule 7) are opt-in via
allow_short=True. Collateral sizing: sum(|w|) <= 1, so every unit of short notional is
backed by a unit of equity held as cash collateral and nothing is leveraged. A short whose
price reaches 2x its entry price has lost all its collateral and is force-closed
(liquidated) at that close. Borrow fees, if any, accrue daily on short notional.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365
FEE = 0.001  # 0.1% per side (Roostoo taker fee)


@dataclass(frozen=True)
class Costs:
    fee: float = FEE
    half_spread: dict[str, float] | None = None   # per pair, as a fraction; default below
    default_half_spread: float = 0.0005
    mult: float = 1.0                              # 2.0 for the 2x stress test
    borrow_annual: float = 0.0                     # short borrow fee, fraction of notional per year

    def per_side(self, pairs) -> np.ndarray:
        hs = self.half_spread or {}
        return np.array([(self.fee + hs.get(p, self.default_half_spread)) * self.mult for p in pairs])


def simulate(close: pd.DataFrame, weights: pd.DataFrame, costs: Costs,
             rebalance: pd.Series | None = None, allow_short: bool = False) -> pd.DataFrame:
    """close: dates x pairs (NaN where not trading). weights: same shape, target weights
    decided at each date's close (rows with all-NaN mean "no decision"). rebalance: bool
    per date; default every date. Returns per-date gross/cost/net return and turnover,
    where the return on date t is earned by holdings set at the close of t-1."""
    pairs = list(close.columns)
    rets = close.pct_change(fill_method=None).to_numpy()
    alive = close.notna().to_numpy()
    w_tgt = weights.reindex(index=close.index, columns=pairs).to_numpy()
    reb = np.ones(len(close), bool) if rebalance is None else rebalance.reindex(close.index).fillna(False).to_numpy()
    per_side = costs.per_side(pairs)
    px = close.to_numpy()

    n = len(close)
    hold = np.zeros(len(pairs))
    entry = np.full(len(pairs), np.nan)  # short entry price, for the liquidation check
    gross = np.zeros(n); cost = np.zeros(n); turnover = np.zeros(n); liquidations = np.zeros(n, int)
    for t in range(n):
        if t > 0:
            r = np.where(np.isnan(rets[t]), 0.0, rets[t])
            gross[t] = float(hold @ r)
            grown = hold * (1 + r)
            denom = 1 + gross[t]
            hold = grown / denom if denom > 0 else np.zeros_like(hold)
            cost[t] += costs.borrow_annual * costs.mult / DAYS_PER_YEAR * float(-hold[hold < 0].sum())
        dead = ~alive[t]
        if allow_short:  # liquidate shorts that have lost their whole collateral
            liq = (hold < 0) & ~dead & (px[t] >= 2 * entry)
            if liq.any():
                trade = np.where(liq, -hold, 0.0)
                turnover[t] += trade.sum()
                cost[t] += float(trade @ per_side)
                liquidations[t] = int(liq.sum())
                hold = np.where(liq, 0.0, hold)
                entry = np.where(liq, np.nan, entry)
        if reb[t] and not np.all(np.isnan(w_tgt[t])):
            tgt = np.where(np.isnan(w_tgt[t]) | dead, 0.0, w_tgt[t])
            if not allow_short:
                tgt = np.clip(tgt, 0.0, None)
            if np.abs(tgt).sum() > 1.0:  # no leverage: gross (longs + collateralised shorts) <= equity
                tgt = tgt / np.abs(tgt).sum()
            trade = np.abs(tgt - hold)
            turnover[t] += trade.sum()
            cost[t] += float(trade @ per_side)
            entry = np.where(tgt < 0, px[t], np.nan)  # resized shorts are re-collateralised
            hold = tgt
        elif dead.any() and np.abs(hold[dead]).sum() > 0:  # delisted: closed at last close
            trade = np.where(dead, np.abs(hold), 0.0)
            turnover[t] += trade.sum()
            cost[t] += float(trade @ per_side)
            hold = np.where(dead, 0.0, hold)
    out = pd.DataFrame({"gross": gross, "cost": cost, "turnover": turnover, "liquidations": liquidations},
                       index=close.index)
    # cost is paid at the close of t, so it reduces the equity carried into t+1
    out["net"] = (1 + out["gross"]) * (1 - out["cost"]) - 1
    return out


def max_drawdown(r: pd.Series) -> float:
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0


def metrics(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 2:
        return {"sharpe": 0.0, "sortino": 0.0, "calmar": 0.0, "maxdd": 0.0, "cagr": 0.0, "total_return": 0.0,
                "score": 0.0, "days": len(r)}
    mu, sd = r.mean(), r.std(ddof=1)
    downside = math.sqrt(float((np.minimum(r, 0.0) ** 2).mean()))
    sharpe = mu / sd * math.sqrt(DAYS_PER_YEAR) if sd > 0 else 0.0
    sortino = mu / downside * math.sqrt(DAYS_PER_YEAR) if downside > 0 else 0.0
    total = float((1 + r).prod() - 1)
    cagr = (1 + total) ** (DAYS_PER_YEAR / len(r)) - 1 if total > -1 else -1.0
    mdd = max_drawdown(r)
    calmar = cagr / abs(mdd) if mdd < 0 else 0.0
    return {
        "sharpe": round(sharpe, 4), "sortino": round(sortino, 4), "calmar": round(calmar, 4),
        "maxdd": round(mdd, 4), "cagr": round(cagr, 4), "total_return": round(total, 4),
        "score": round(score(sortino, sharpe, calmar), 4), "days": int(len(r)),
    }


def score(sortino: float, sharpe: float, calmar: float) -> float:
    """Competition composite."""
    return 0.4 * sortino + 0.3 * sharpe + 0.3 * calmar


def deflated_sharpe_prob(r: pd.Series, n_trials: int, trial_sharpes: list[float]) -> float:
    """Bailey & Lopez de Prado deflated Sharpe ratio: P(true SR > 0) after correcting the
    observed (per-period) SR for the best-of-N selection, skew and kurtosis."""
    r = r.dropna()
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return 0.0
    sr = r.mean() / r.std(ddof=1)
    skew = float(((r - r.mean()) ** 3).mean() / r.std(ddof=0) ** 3)
    kurt = float(((r - r.mean()) ** 4).mean() / r.std(ddof=0) ** 4)
    var_trials = float(np.var(trial_sharpes, ddof=1)) if len(trial_sharpes) > 1 else 0.0
    gamma = 0.5772156649
    if n_trials > 1 and var_trials > 0:
        from statistics import NormalDist
        z = NormalDist().inv_cdf
        sr0 = math.sqrt(var_trials) * ((1 - gamma) * z(1 - 1 / n_trials) + gamma * z(1 - 1 / (n_trials * math.e)))
    else:
        sr0 = 0.0
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    stat = (sr - sr0) * math.sqrt(n - 1) / denom
    return 0.5 * (1 + math.erf(stat / math.sqrt(2)))
