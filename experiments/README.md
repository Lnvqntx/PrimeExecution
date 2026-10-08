# Experiments

Append-only trial log: `trials.jsonl`, one JSON object per line, never edited or deleted.

```json
{"id": "exp-001", "date": "2026-10-10", "idea": "...", "rationale": "...", "data": "Binance 1h 2024-10..2026-09",
 "params_tried": 12, "metrics": {"sharpe": 0.0, "sortino": 0.0, "calmar": 0.0, "maxdd": 0.0}, "verdict": "rejected|promoted"}
```

A strategy is promoted to `prime/strategy.py` only if it passes the gates in the plan: positive after costs and at 2x costs,
at least 65% of walk-forward folds positive, stable under +/-30% parameter changes, and a deflated Sharpe that accounts for
how many configurations were tried.

## Round 2 summary (2026-10-08)

Trials exp-007..exp-017. Same data, universe, costs and walk-forward as round 1: 21 out-of-sample months
2025-01..2026-09, 0.1% fee per side plus half-spread. Details are in `research/results/round2/RESULTS.md`.

- **Phase 0 gross sweep** (equal-weight top-10 basket, gross 0.2 / 0.3 / 0.5 / 0.8): returns -5.6% / -9.1% / -17.5% / -32.1%,
  max drawdown -17.7% / -25.6% / -39.7% / -56.9%. Sharpe stays about -0.18 at every level. Changing gross does not
  change the edge; the loss and drawdown just scale with it.
- **Long/short** (long the Phase 0 basket, short the 10 weakest names, each short fully cash-collateralised, gross <= 1):
  +13.0% at 1x costs (score 0.44), +3.9% at 2x, +3.6% with a 10%/yr borrow fee. It **fails 3 of 4 gates**: 48% of months
  positive, a -30% lookback change turns it negative, and the deflated-Sharpe probability is 0.37 over 26 configurations.
  The gains came almost entirely in 2025 (9 of the last 11 months were negative).
  It was rejected on these validation gates, not because shorting is unavailable. Roostoo offers `/v6/short_open`,
  `/v6/short_close` and `/v6/short_positions`. The live bot is spot long-only because of our own CLAUDE.md rule 7,
  which stays in force until a reviewed change says otherwise. (The exp-014 rationale says "Roostoo has no shorting".
  That is wrong; the line stays as written because the log is append-only, and this note corrects it.)
- **Benchmarks** (1x costs): BTC buy-and-hold -10.6% (max DD -53.0%), equal-weight 30 pairs -64.2% (-81.2%),
  Phase 0 proxy at gross 0.3 -9.1% (-25.6%). These reproduce round 1 exactly.
- **Notes**: exp-007..009 record runs that were not logged when they happened: the round-1 debug run on incomplete
  data (void), the round-1 rerun identical to exp-001..006, and a round-2 attempt that crashed before any output.

**Verdict: nothing promoted; Phase 0 unchanged.**
