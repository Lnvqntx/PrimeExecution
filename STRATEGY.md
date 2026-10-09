# Strategy: Prime Execution (Team107, IITM)

Competition: APAC Quant Trading Hackathon, Roostoo mock exchange. Spot, long-only, no leverage, fully autonomous.

## Summary

We run a **liquid equal-weight basket** (internal name `liquid_basket_v0`, "Phase 0") with a drawdown-based risk overlay.
It is a deliberately simple baseline. We tested three signal strategies and a long/short variant on 21 months of
out-of-sample Binance data. None passed our promotion gates, so none is live. The logs show the bot doing exactly what
this document says.

## What the bot holds

- **Universe:** USD pairs listed on Roostoo, ranked by 24h USD turnover. A pair must have a quoted spread under 20 bps.
  Stablecoins are excluded.
- **Basket:** the top 10 pairs, equal weight. A held coin is kept while it ranks within the top 15 (hysteresis, to avoid
  churn).
- **Exposure:** 30% of equity invested in total, at most 5% in any coin. The other 70% stays in USD.
- **Orders:** market orders only, sells before buys, quantities rounded down to each pair's precision.

## When it trades (Hong Kong time)

| Trigger | Condition |
| --- | --- |
| Daily rebalance | First cycle of each HKT day (09:00 HKT onward after the first day) |
| Drawdown scale change | Risk engine moves exposure between full, half and flat |
| Watchdog | 20:00 HKT, if nothing has filled that day: one more genuine rebalance with a tighter tolerance |

The watchdog never invents trades. If the portfolio is already on target it sends nothing. Rebalancing to the declared
targets is the only source of orders.

## Risk controls

- Drawdown from peak of -4%: exposure halved. At -8%: everything is sold and the bot stays in cash for 12 hours, then
  restarts from a fresh peak.
- Per-coin cap, total gross cap, minimum notional and a no-trade band on small differences.
- The exchange balance is the source of truth, never local files.
- Orders are never retried blindly: a timeout is treated as "unknown" and reconciled from the balance next cycle.
- Two locks for live trading: `LIVE_TRADING=true` in the environment and the `--live` flag.

## Why a baseline

- **Costs:** the observed fee is 0.1% per side, so a round trip costs about 0.2%. A short-horizon signal has to clear
  that by a wide margin. Measured slippage on our first live fills was about -1.5 bps (slightly better than the quote).
- **Metrics:** the competition scores Sortino, Sharpe and Calmar as well as return. A low-exposure, diversified basket
  keeps volatility and drawdown small.
- **Honesty:** we would rather run a declared baseline than an untested signal.

## Research and results

Method (`research/`, trials in `experiments/trials.jsonl`): Binance spot daily klines for the 30 most liquid pairs,
Oct 2024 to Sep 2026. The universe is fixed from data before the test window. A 3-month training period is followed by
21 monthly out-of-sample folds, where each month is traded with the best setting found so far. Costs include fees plus
an assumed spread of 2, 5 or 10 bps by liquidity tier, also tested at 2x. Promotion requires a positive result after
costs and at 2x costs, at least 65% of folds positive, stability under +/-30% parameter changes, and a deflated Sharpe
that accounts for the number of configurations tried.

| Run (21 OOS months, normal costs) | Return | Max drawdown | Gates passed |
| --- | --- | --- | --- |
| Time-series trend | -36.6% | -51.9% | 0/4 |
| Cross-sectional momentum | -55.5% | -83.2% | 0/4 |
| Volatility-scaled basket | -12.8% | -46.4% | 0/4 |
| BTC buy-and-hold (benchmark) | -10.6% | -53.0% | |
| Equal weight, all 30 pairs (benchmark) | -64.2% | -81.2% | |
| Phase 0 proxy, gross 0.3 | -9.1% | -25.6% | |

Round 2: raising the basket's exposure (gross 0.2, 0.3, 0.5, 0.8) only scales losses and drawdown (Sharpe stays near
-0.18). A long/short variant made +13.0% at normal costs but fails 3 of 4 gates (48% of months positive, unstable
lookback, deflated-Sharpe probability 0.37) and its gains were concentrated in 2025. It was rejected on those gates. Short
selling is supported by the exchange API and by `prime/client.py`, but the live bot stays spot long-only unless a reviewed
change says otherwise.

Limits of this evidence: the test window was a falling market, the spreads are assumptions because daily candles do not
include them, the universe has survivorship bias, and 8 live days cannot validate a signal. Every run, including
discarded and retroactively logged ones (`exp-007` to `exp-009`), is in the trial log.

## Process and compliance

- One branch per change, strategy and risk numbers only in `prime/config.py` and `prime/strategy.py`, commit messages
  give the reason, every backtest is logged in `experiments/trials.jsonl` and nothing is deleted.
- Strategies are pure functions (market state in, target weights out). Execution, risk and sizing are separate modules.
- All orders come from `prime/executor.py`. There is no manual trading path and no logic that generates activity.
- The bot runs on AWS EC2, which only pulls `main` and runs it. Research runs off-instance.
- `python -m pytest -q` must pass before any merge. `python -m prime.report` prints the active Hong Kong trading days,
  equity, drawdown, slippage and commission from the bot's own logs.

## Decision rule for changing the strategy

A candidate replaces Phase 0 only after it passes the gates above on a branch, with the trial recorded. Until then the
baseline keeps running unchanged.
