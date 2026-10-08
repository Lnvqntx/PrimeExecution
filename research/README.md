# research/

Offline research only. Nothing here is imported by `prime/` or runs on EC2.

```bash
pip install -r requirements-research.txt
python -m research.data          # download Binance 1d klines -> research/data/ (git-ignored)
python -m research.run           # walk-forward evaluation -> research/results/
python -m research.run --log     # same, and append the runs to experiments/trials.jsonl
```

- `data.py`: picks the universe with no look-ahead (top 30 USDT pairs by median daily quote volume over
  2024-07..09, stablecoins, wrapped and leveraged tokens excluded; see `universe.json`) and downloads monthly
  daily-kline zips from the public Binance dump (data.binance.vision, fetched through its S3 endpoint), checking
  each file against its published SHA-256 when the checksum can be fetched.
- `backtest.py`: daily long-only simulator. Weights decided at day t's close earn day t+1's return, with drift
  between rebalances, a 0.1% fee per side plus half-spread, no leverage, and delisted pairs sold at their last
  close. Also holds the metrics, the composite score (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar) and the deflated Sharpe.
- `strategies.py`: the three pre-declared candidates and their fixed grids, plus reference benchmarks.
- `run.py`: the protocol (monthly expanding-window walk-forward, 21 OOS folds, 1x and 2x costs, the
  promotion gates from `experiments/README.md`).

Running `run.py` reports gate results only. Any promotion into `prime/strategy.py` is a separate, reviewed change.
