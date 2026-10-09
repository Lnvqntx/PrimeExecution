# Prime Execution

Autonomous spot trading bot for the HK x AU x IN Quant Trading Hackathon (Roostoo mock exchange).
Team107 - Prime Execution (IITM).

## Strategy status (declared honestly)

**Phase 0 (live): liquid equal-weight basket.** The bot holds an equal-weight basket of the 10 most liquid USD pairs
(ranked by 24h USD turnover, quoted spread under 20 bps, stablecoins excluded) at 30% gross exposure, with at most 5% of
equity in any coin. The other 70% stays in USD. It rebalances once per Hong Kong trading day.

This is a baseline, not an alpha claim. The reasons for starting here:
- **Cost realism:** a market round trip costs at least 0.2% in fees, so a short-horizon signal has to clear that
  by a wide margin. We want measured fees and slippage from real fills before trusting any signal.
- **Smooth equity curve:** the competition scores Sortino, Sharpe and Calmar. A low-exposure, diversified basket keeps
  volatility and drawdown small, which is what those ratios reward.
- **Validity:** the strategy is declared up front and the logs show it executing exactly that.

Candidate signal strategies (time-series trend, cross-sectional momentum, volatility-scaled basket, and a long/short
variant) were tested offline on 21 out-of-sample months of Binance history with walk-forward validation. None passed the
gates in `experiments/README.md`, so none is live. Every trial, including the rejected and retroactively logged ones, is
in `experiments/trials.jsonl`. The full strategy description and results are in [STRATEGY.md](STRATEGY.md).

## How a trading cycle works

Every 60 seconds (`prime/bot.py`):

1. Fetch the ticker and drop invalid quotes (non-positive or crossed). Refuse to trade on thin data.
2. Rebuild the portfolio from the exchange's own `/v3/balance`. Local files are never the source of truth for holdings.
3. Risk check (`prime/risk.py`): drawdown from peak. At -4% exposure is halved; at -8% everything is sold and the bot
   stays in cash for 12 hours, then restarts from a fresh peak.
4. On a trading trigger, the strategy returns target weights, the risk engine clamps them (per-coin cap, total cap,
   drawdown scale), and the planner converts them to exchange-valid orders: quantities rounded down to the pair's
   `AmountPrecision`, minimum notional respected, sells before buys, buys capped to available cash.
5. The executor sends market orders one by one and checks `Success` on every response (the exchange returns HTTP 200 for
   failures). An order whose outcome is unknown (timeout) is never retried blindly; the next cycle reconciles from the balance.
6. Every decision, order, fill (with realized slippage and commission percent) and equity point is appended to
   `logs/*.jsonl`.

**Trading triggers** (all in Hong Kong time, which is how the competition counts days): first cycle of each day
(daily rebalance, from 09:00 HKT after the first day); a drawdown scale change; and a watchdog at 20:00 HKT that runs one
extra genuine rebalance with a tighter tolerance if nothing has filled that day. The watchdog never invents trades: if the
portfolio is already on target it sends nothing.

## Rules compliance

| Rule | How it is met |
| --- | --- |
| Autonomous execution | All orders come from `prime/executor.py`; there is no manual trading path |
| Spot, 1x, no leverage | Long-only market buys/sells of USD pairs; gross exposure capped at 30% |
| No HFT / market-making / arbitrage | One rebalance per day, market orders only, 60s polling |
| Trade log integrity | `logs/orders.jsonl` records every order with the reason that produced it |
| Commit history transparency | All strategy and risk parameters live in `prime/config.py`; changes only via commits |
| AWS is deployment only | EC2 runs the bot and pulls `main`; research happens off-instance |

## Project layout

```
prime/        live bot: client, market, portfolio, strategy, risk, planner, executor, bot loop, report
tests/        fake exchange, signature-verifying mock server, unit + end-to-end tests
experiments/  research trial log (trials.jsonl)
research/     offline walk-forward backtests (not imported by the bot)
deploy/       systemd installer for EC2
legacy/       original research scripts, kept for history
```

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in the keys (EC2 only)

python -m prime --once                  # one DRY cycle: logs intended orders, sends nothing
python -m prime --live                  # live; requires LIVE_TRADING=true in .env as well
python -m prime.report                  # active days (HKT), equity, drawdown, slippage, last orders
```

On EC2: `bash deploy/install_service.sh` installs and starts the `primebot` systemd service. Update with
`git pull && sudo systemctl restart primebot`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite covers request signing against the official Roostoo worked example, order sizing and rounding, the drawdown
ladder, the full trading loop (rebalance, watchdog, flatten, rejects, uncertain orders, restart), and the real
HTTP client driven through the command line against a local server that verifies signatures.

## Known limitations

- The Phase 0 basket has no predictive edge by design; its job is a stable, fully compliant baseline.
- Fee percentages are verified from the first live fills (`commission_pct` in `logs/orders.jsonl`), not assumed.
- Shorting is supported by the client but unused until a strategy that needs it passes validation.
