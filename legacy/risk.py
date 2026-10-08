from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    max_position_weight: float = 0.20
    max_gross_exposure: float = 0.80
    max_daily_loss: float = 0.03
    max_drawdown: float = 0.10
    min_signal_score: float = 0.0


class RiskManager:
    """Research/simulation risk gate. It never submits orders."""

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()

    def size_weights(self, scores: dict[str, float]) -> dict[str, float]:
        positive = {
            pair: max(float(score), 0.0)
            for pair, score in scores.items()
            if float(score) >= self.config.min_signal_score
        }

        if not positive:
            return {}

        total = sum(positive.values())
        if total <= 0:
            return {}

        raw = {
            pair: score / total * self.config.max_gross_exposure
            for pair, score in positive.items()
        }

        capped = {
            pair: min(weight, self.config.max_position_weight)
            for pair, weight in raw.items()
        }

        total_capped = sum(capped.values())
        if total_capped > self.config.max_gross_exposure:
            scale = self.config.max_gross_exposure / total_capped
            capped = {
                pair: weight * scale
                for pair, weight in capped.items()
            }

        return capped

    def portfolio_allowed(
        self,
        daily_return: float,
        drawdown: float,
    ) -> bool:
        if daily_return <= -self.config.max_daily_loss:
            return False

        if drawdown <= -self.config.max_drawdown:
            return False

        return True
