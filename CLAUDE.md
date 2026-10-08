# Rules for working in this repo (read before changing anything)

This is the live trading bot for the APAC Quant Trading Hackathon (Roostoo mock exchange).
The EC2 instance runs whatever is on `main`. A mistake here trades real (mock) money.

## Hard rules
1. **No secrets in git.** Never write API keys, `.env` contents or logs into any file that gets committed.
2. **No live API calls from development sessions.** Tests use `tests/fake_exchange.py` and `tests/mock_server.py` only.
   Never run `python -m prime --live` anywhere except the EC2 instance.
3. **Strategy and risk numbers live only in `prime/config.py` (`Params`) and `prime/strategy.py`.**
   Change them only on a branch, with a reason in the commit message, and record every backtest in `experiments/trials.jsonl`
   (one JSON object per line: id, date, what changed, data window, metrics, verdict). Never delete a trial.
4. **Strategies stay pure functions** (market state in, target weights out). Execution, risk and sizing are separate modules.
5. **Autonomous only.** No manual order placement, no console scripts that trade. The only thing that sends orders is `prime/executor.py`.
6. **No fake trades.** Never add logic whose purpose is to generate activity. Rebalancing to the declared targets is the only trade source.
7. **Spot long-only unless a reviewed change says otherwise.** No leverage. No high-frequency, market-making or arbitrage logic (competition rules).
8. **Every change must keep `python -m pytest -q` green.** Add a test for any new behavior or bug fix.
9. **Time is Hong Kong time (UTC+8)** for anything that touches the trading day (`prime/clock.py`).

## Layout
- `prime/` live bot (client, market, portfolio, strategy, risk, planner, executor, bot loop, report)
- `tests/` fake exchange, signature-verifying mock server, unit and end-to-end tests
- `experiments/` research trial log
- `deploy/` systemd installer for EC2 (EC2 is deployment-only: it runs the bot and pulls `main`, nothing else)
- `legacy/` the original research scripts, kept for history; not imported by the bot

## Workflow
Branch -> change + tests -> `python -m pytest -q` -> pull request -> review -> merge to `main` -> on EC2: `git pull` and `sudo systemctl restart primebot`.
