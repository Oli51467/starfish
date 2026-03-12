from __future__ import annotations

from models.schemas import TrendLabel


class TrendAnalyzer:
    """Skeleton trend scoring helper."""

    @staticmethod
    def classify_by_score(score: float, paper_count: int) -> TrendLabel:
        if paper_count < 50 and score >= 0.7:
            return "emerging"
        if score >= 0.8:
            return "rising"
        if score >= 0.45:
            return "stable"
        return "saturated"
