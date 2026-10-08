# Experiments

Append-only trial log: `trials.jsonl`, one JSON object per line, never edited or deleted.

```json
{"id": "exp-001", "date": "2026-10-10", "idea": "...", "rationale": "...", "data": "Binance 1h 2024-10..2026-09",
 "params_tried": 12, "metrics": {"sharpe": 0.0, "sortino": 0.0, "calmar": 0.0, "maxdd": 0.0}, "verdict": "rejected|promoted"}
```

A strategy is promoted to `prime/strategy.py` only if it passes the gates in the plan: positive after costs and at 2x costs,
at least 65% of walk-forward folds positive, stable under +/-30% parameter changes, and a deflated Sharpe that accounts for
how many configurations were tried.
