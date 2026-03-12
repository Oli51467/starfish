from __future__ import annotations

from models.schemas import TrendLabel


class TrendAnalyzer:
    """Trend scoring and label helper."""

    @staticmethod
    def classify_by_score(score: float, paper_count: int) -> TrendLabel:
        if paper_count < 50 and score >= 0.7:
            return "emerging"
        if score >= 0.8:
            return "rising"
        if score >= 0.45:
            return "stable"
        return "saturated"

    @staticmethod
    def classify_by_growth(paper_growth_percent: float, paper_count: int, score: float) -> TrendLabel:
        # Rule priority follows PRD definitions.
        if paper_count < 50 and paper_growth_percent > 100:
            return "emerging"
        if paper_growth_percent > 200:
            return "rising"
        if 50 <= paper_growth_percent <= 200:
            return "stable"
        if paper_growth_percent < 50 and paper_count > 500:
            return "saturated"
        return TrendAnalyzer.classify_by_score(score, paper_count)
