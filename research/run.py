"""Walk-forward evaluation of the three pre-declared candidates.

    python -m research.data          # once: download klines, build the panel
    python -m research.run --log     # evaluate; --log appends to experiments/trials.jsonl

Protocol (fixed before the first run):
  * P&L window 2024-10-01..2026-09-30 (UTC daily candles). 2024-07..09 is warm-up only.
  * Monthly folds, expanding training window, first 3 months training only:
    21 out-of-sample months 2025-01..2026-09.
  * At the close of each month's last day, every grid member is scored on the training
    window (composite score of its net daily returns) and the best one trades next month.
  * Rebalance weekly (close of each Monday) and at each fold boundary.
  * Costs per side: 0.1% fee + half-spread by liquidity tier; repeated at 2x costs.
  * Score = 0.4*Sortino + 0.3*Sharpe + 0.3*Calmar on daily returns, annualised with 365.
Nothing is promoted by this script; it only reports gates.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import Costs, deflated_sharpe_prob, metrics, score, simulate
from .data import PANEL, UNIVERSE
from .strategies import BENCHMARKS, CANDIDATES

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRIALS = ROOT.parent / "experiments" / "trials.jsonl"

PNL_START = pd.Timestamp("2024-10-01")
PNL_END = pd.Timestamp("2026-09-30")
FIRST_TEST_MONTH = pd.Period("2025-01", "M")
# half-spread by pre-window liquidity rank (1-based): fraction of price
SPREAD_TIERS = [(5, 0.0002), (15, 0.0005), (30, 0.0010)]
GATES = {"min_folds_positive": 0.65, "min_dsr_prob": 0.95, "perturb": 0.30}


def load():
    uni = json.loads(UNIVERSE.read_text())["pairs"]
    pairs = [d["symbol"] for d in uni]
    df = pd.read_csv(PANEL, parse_dates=["date"])
    close = df.pivot(index="date", columns="symbol", values="close").reindex(columns=pairs).sort_index()
    volume = df.pivot(index="date", columns="symbol", values="quote_volume").reindex(columns=pairs).sort_index()
    close = close.loc[:PNL_END]
    volume = volume.loc[:PNL_END]
    half_spread = {}
    for i, p in enumerate(pairs, 1):
        half_spread[p] = next(hs for cap, hs in SPREAD_TIERS if i <= cap)
    return close, volume, half_spread


def weekly(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(index.dayofweek == 0, index=index)


def run_fixed(close, volume, fn, params, costs, start, allow_short=False):
    """Fixed-parameter run; returns the simulation for dates > start."""
    w = fn(close, volume, **params)
    c = close.loc[start:]
    reb = weekly(c.index)
    reb.iloc[0] = True
    sim = simulate(c, w.loc[start:], costs, reb, allow_short=allow_short)
    return sim.iloc[1:]


def walk_forward(close, volume, fn, grid, costs, allow_short=False):
    """Returns (OOS sim frame, per-fold choices, per-config full-window sims)."""
    start = PNL_START - pd.Timedelta(days=1)
    per_cfg = [run_fixed(close, volume, fn, g, costs, start, allow_short) for g in grid]
    weights = [fn(close, volume, **g) for g in grid]

    c = close.loc[FIRST_TEST_MONTH.start_time - pd.Timedelta(days=1):]
    stitched = pd.DataFrame(np.nan, index=c.index, columns=c.columns)
    reb = weekly(c.index)
    folds = []
    month = FIRST_TEST_MONTH
    while month.start_time <= PNL_END:
        train_end = month.start_time - pd.Timedelta(days=1)
        scores = [metrics(s["net"].loc[PNL_START:train_end])["score"] for s in per_cfg]
        best = int(np.argmax(scores))
        decide = c.index[(c.index >= train_end) & (c.index < month.end_time.normalize())]
        stitched.loc[decide] = weights[best].loc[decide]
        reb.loc[train_end] = True
        folds.append({"month": str(month), "chosen": grid[best], "train_score": round(scores[best], 4)})
        month += 1
    sim = simulate(c, stitched, costs, reb, allow_short=allow_short).iloc[1:]
    for f in folds:
        m = sim["net"][sim.index.to_period("M") == pd.Period(f["month"], "M")]
        f["oos_return"] = round(float((1 + m).prod() - 1), 4)
    return sim, folds, per_cfg


def perturbations(params: dict, k: float) -> list[dict]:
    out = []
    for key, v in params.items():
        if key == "top_k":
            continue  # basket size is a discrete structural choice, not tuned on returns
        for f in (1 - k, 1 + k):
            q = dict(params)
            q[key] = max(2, int(round(v * f))) if isinstance(v, int) else round(v * f, 4)
            out.append(q)
    return out


def per_period_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    return float(r.mean() / r.std(ddof=1)) if r.std(ddof=1) > 0 else 0.0


def evaluate(cost_mult: float):
    close, volume, hs = load()
    costs = Costs(half_spread=hs, mult=cost_mult)
    oos_start = FIRST_TEST_MONTH.start_time
    out = {"cost_mult": cost_mult, "candidates": {}, "benchmarks": {}}
    trial_sharpes = []
    for name, (fn, grid) in CANDIDATES.items():
        sim, folds, per_cfg = walk_forward(close, volume, fn, grid, costs)
        grid_res = []
        for g, s in zip(grid, per_cfg):
            r = s["net"].loc[oos_start:]
            trial_sharpes.append(per_period_sharpe(r))
            grid_res.append({"params": g, "oos_period": metrics(r), "full_window": metrics(s["net"])})
        mode = Counter(json.dumps(f["chosen"], sort_keys=True) for f in folds).most_common(1)[0][0]
        mode = json.loads(mode)
        sens = []
        for q in perturbations(mode, GATES["perturb"]):
            r = run_fixed(close, volume, fn, q, costs, PNL_START - pd.Timedelta(days=1))["net"].loc[oos_start:]
            trial_sharpes.append(per_period_sharpe(r))
            sens.append({"params": q, "oos_period": metrics(r)})
        out["candidates"][name] = {
            "grid": grid, "oos": metrics(sim["net"]), "oos_gross": metrics(sim["gross"]),
            "avg_daily_turnover": round(float(sim["turnover"].mean()), 4),
            "cost_drag_annual": round(float(sim["cost"].mean() * 365), 4),
            "folds": folds, "most_chosen": mode, "grid_results": grid_res, "sensitivity": sens,
            "_returns": sim["net"],
        }
    n_trials = len(trial_sharpes)
    for name, c in out["candidates"].items():
        r = c.pop("_returns")
        pos = sum(f["oos_return"] > 0 for f in c["folds"]) / len(c["folds"])
        dsr = deflated_sharpe_prob(r, n_trials, trial_sharpes)
        c["folds_positive"] = round(pos, 4)
        c["dsr_prob"] = round(dsr, 4)
        c["n_trials_deflated"] = n_trials
        c["gates"] = {
            "positive_after_costs": c["oos"]["total_return"] > 0 and c["oos"]["score"] > 0,
            "folds_positive_ge_65pct": pos >= GATES["min_folds_positive"],
            "stable_pm30pct": all(s["oos_period"]["score"] > 0 for s in c["sensitivity"]) and c["oos"]["score"] > 0,
            "deflated_sharpe_ge_95pct": dsr >= GATES["min_dsr_prob"],
        }
    for name, fn in BENCHMARKS.items():
        r = run_fixed(close, volume, fn, {}, costs, oos_start - pd.Timedelta(days=1))["net"]
        out["benchmarks"][name] = {"oos": metrics(r)}
    return out


def git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def next_id() -> int:
    if not TRIALS.exists():
        return 1
    ids = [json.loads(l)["id"] for l in TRIALS.read_text().splitlines() if l.strip()]
    return max((int(i.split("-")[1]) for i in ids if i.startswith("exp-")), default=0) + 1


def log_trials(results: dict) -> None:
    base = results["1x"]
    stress = results["2x"]
    n = next_id()
    lines = []
    data = "Binance spot 1d klines, top-30 USDT pairs (universe.json); OOS 2025-01..2026-09 (21 monthly folds), " \
           "training from 2024-10, warm-up 2024-07..09"
    for name, c in base["candidates"].items():
        s = stress["candidates"][name]
        lines.append({
            "id": f"exp-{n:03d}", "date": str(date.today()), "code_rev": git_rev(),
            "idea": f"{name} (pre-declared candidate, walk-forward selection over its grid)",
            "rationale": "research/strategies.py docstring; protocol in research/run.py",
            "data": data, "params_tried": len(c["grid"]) + len(c["sensitivity"]),
            "grid": c["grid"], "most_chosen": c["most_chosen"],
            "costs": "0.1% fee/side + half-spread 2/5/10 bps by liquidity tier",
            "metrics": c["oos"], "metrics_2x_costs": s["oos"],
            "folds_positive": c["folds_positive"], "folds_positive_2x_costs": s["folds_positive"],
            "dsr_prob": c["dsr_prob"], "n_trials_deflated": c["n_trials_deflated"],
            "sensitivity": [{"params": x["params"], "score": x["oos_period"]["score"]} for x in c["sensitivity"]],
            "grid_scores_oos": [{"params": x["params"], "score": x["oos_period"]["score"]} for x in c["grid_results"]],
            "gates": c["gates"], "gates_2x_costs": s["gates"],
            "verdict": "rejected" if not all(c["gates"].values()) or not all(s["gates"].values())
                       else "not_promoted (passes gates; awaiting review)",
        })
        n += 1
    for name, b in base["benchmarks"].items():
        lines.append({
            "id": f"exp-{n:03d}", "date": str(date.today()), "code_rev": git_rev(),
            "idea": f"benchmark: {name}", "rationale": "reference only, not a candidate",
            "data": data, "params_tried": 0, "metrics": b["oos"],
            "metrics_2x_costs": stress["benchmarks"][name]["oos"], "verdict": "benchmark",
        })
        n += 1
    with TRIALS.open("a") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")
    print(f"appended {len(lines)} trials to {TRIALS}")


def render(results: dict) -> str:
    def row(name, o, extra=""):
        return (f"| {name} | {o['score']:.3f} | {o['sortino']:.2f} | {o['sharpe']:.2f} | {o['calmar']:.2f} | "
                f"{o['total_return']:.1%} | {o['maxdd']:.1%} |{extra}")
    out = ["# Walk-forward results", "",
           "Generated by `python -m research.run`. Out-of-sample: 21 monthly folds, 2025-01..2026-09.",
           "Score = 0.4*Sortino + 0.3*Sharpe + 0.3*Calmar (daily, annualised x365). **No strategy is promoted.**", ""]
    for k, res in results.items():
        out += [f"## Costs {k} (0.1% fee/side + half-spread 2/5/10 bps by liquidity tier, x{res['cost_mult']:g})", "",
                "| run | score | Sortino | Sharpe | Calmar | return | max DD | folds + | DSR P | gates |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for name, c in res["candidates"].items():
            g = c["gates"]
            out.append(row(name, c["oos"], f" {c['folds_positive']:.0%} | {c['dsr_prob']:.2f} | "
                                            f"{sum(g.values())}/{len(g)} |"))
        for name, b in res["benchmarks"].items():
            out.append(row(f"*{name}* (benchmark)", b["oos"], " | | |"))
        out.append("")
    base = results["1x"]["candidates"]
    out += ["## Detail (1x costs)", ""]
    for name, c in base.items():
        out += [f"### {name}", "",
                f"Avg daily turnover {c['avg_daily_turnover']:.3f}, cost drag {c['cost_drag_annual']:.1%}/yr, "
                f"gross score {c['oos_gross']['score']:.3f}. Most chosen: `{json.dumps(c['most_chosen'])}`. "
                f"Gates: " + ", ".join(f"{k} {'PASS' if v else 'fail'}" for k, v in c["gates"].items()) + ".", "",
                "| fixed params (no selection) | OOS score | OOS return | max DD |", "|---|---|---|---|"]
        for x in c["grid_results"]:
            o = x["oos_period"]
            out.append(f"| `{json.dumps(x['params'])}` | {o['score']:.3f} | {o['total_return']:.1%} | {o['maxdd']:.1%} |")
        for x in c["sensitivity"]:
            o = x["oos_period"]
            out.append(f"| `{json.dumps(x['params'])}` (+/-30%) | {o['score']:.3f} | {o['total_return']:.1%} | "
                       f"{o['maxdd']:.1%} |")
        out += ["", "| month | chosen | OOS return |", "|---|---|---|"]
        out += [f"| {f['month']} | `{json.dumps(f['chosen'])}` | {f['oos_return']:.1%} |" for f in c["folds"]]
        out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="store_true", help="append results to experiments/trials.jsonl")
    args = ap.parse_args()
    results = {"1x": evaluate(1.0), "2x": evaluate(2.0)}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "summary.json").write_text(json.dumps(results, indent=1) + "\n")
    (RESULTS / "RESULTS.md").write_text(render(results))
    for k, res in results.items():
        print(f"\n=== costs {k} ===")
        for name, c in res["candidates"].items():
            o = c["oos"]
            print(f"{name:12s} score {o['score']:7.3f}  sharpe {o['sharpe']:6.2f}  sortino {o['sortino']:6.2f}  "
                  f"calmar {o['calmar']:6.2f}  ret {o['total_return']:7.1%}  mdd {o['maxdd']:7.1%}  "
                  f"folds+ {c['folds_positive']:.0%}  dsr {c['dsr_prob']:.2f}  gates {sum(c['gates'].values())}/4")
        for name, b in res["benchmarks"].items():
            o = b["oos"]
            print(f"{name:12s} score {o['score']:7.3f}  sharpe {o['sharpe']:6.2f}  sortino {o['sortino']:6.2f}  "
                  f"calmar {o['calmar']:6.2f}  ret {o['total_return']:7.1%}  mdd {o['maxdd']:7.1%}")
    if args.log:
        log_trials(results)


if __name__ == "__main__":
    main()
