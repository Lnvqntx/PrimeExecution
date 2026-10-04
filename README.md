# Prime Execution

Autonomous quantitative trading bot for the APAC Quant Trading Hackathon.

Team: Team107-Prime Execution (IITM)

## Current status

Phase 1: API connectivity and safe-mode infrastructure.

The bot is intentionally non-trading by default. We will validate market-data connectivity, build the strategy, add risk controls, backtest, and only then enable live order execution.

## Architecture

- main.py — runtime entrypoint
- config.py — environment/configuration
- roostoo_client.py — Roostoo REST client and signing foundation
- requirements.txt — Python dependencies
- .env.example — secret/config template

## Safety

Never commit API keys or secrets. Use environment variables on the local machine and AWS instance.

## Competition constraints

The bot is designed for the Roostoo mock exchange and will follow the hackathon rules: autonomous execution, spot 1x trading only, no HFT/market-making/arbitrage, and internal trade/API logs.

## Development roadmap

1. API connectivity
2. Market universe and data collection
3. Baseline signal
4. Backtesting and transaction-cost model
5. Risk engine
6. Execution engine
7. Paper/dry-run validation
8. AWS deployment
9. Controlled live trading
10. Continuous performance monitoring
