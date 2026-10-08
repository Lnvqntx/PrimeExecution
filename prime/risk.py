"""Portfolio-level risk: drawdown ladder, circuit breaker, and weight clamps.

The ladder protects the Calmar leg of the score. Drawdown is measured against the
peak equity the exchange itself reports, so it survives restarts via the state file.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import Params


@dataclass
class RiskDecision:
    scale: float        # multiplier on target exposure: 1.0, 0.5 or 0.0
    flatten: bool       # sell everything now
    drawdown: float     # current drawdown from peak, <= 0
    reason: str


class RiskEngine:
    def __init__(self, params: Params):
        self.p = params

    def update(self, equity: float, now: float, state) -> RiskDecision:
        """Mutates `state.peak_equity` and `state.breaker_until`."""
        if state.breaker_until and now >= state.breaker_until:
            state.breaker_until = 0.0
            state.peak_equity = equity            # fresh start after the cool-off
        state.peak_equity = max(state.peak_equity, equity)
        dd = equity / state.peak_equity - 1.0 if state.peak_equity > 0 else 0.0

        if state.breaker_until:
            return RiskDecision(0.0, True, dd, "breaker cool-off active")
        if dd <= self.p.dd_flat:
            state.breaker_until = now + self.p.breaker_hours * 3600.0
            return RiskDecision(0.0, True, dd, f"drawdown {dd:.2%} <= {self.p.dd_flat:.0%}: flatten")
        if dd <= self.p.dd_half:
            return RiskDecision(0.5, False, dd, f"drawdown {dd:.2%} <= {self.p.dd_half:.0%}: half exposure")
        return RiskDecision(1.0, False, dd, "ok")

    def clamp(self, targets: dict[str, float], scale: float) -> dict[str, float]:
        """Per-name cap, then total cap, then the drawdown scale."""
        if scale <= 0 or not targets:
            return {}
        capped = {p: min(max(w, 0.0), self.p.max_weight) for p, w in targets.items()}
        gross = sum(capped.values())
        if gross > self.p.gross > 0:
            capped = {p: w * self.p.gross / gross for p, w in capped.items()}
        return {p: w * scale for p, w in capped.items() if w * scale > 0}
