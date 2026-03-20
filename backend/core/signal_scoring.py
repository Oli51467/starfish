from __future__ import annotations

from datetime import datetime
import math

from models.schemas import PaperSignalTrendLabel


def clamp01(value: float) -> float:
    if value <= 0:
        return 0.0
    if value >= 1:
        return 1.0
    return float(value)


def normalize_citation_count(citation_count: int, *, reference_count: int = 1200) -> float:
    safe_count = max(0, int(citation_count or 0))
    safe_reference = max(50, int(reference_count or 1200))
    score = 1 - math.exp(-safe_count / safe_reference)
    return clamp01(score)


def recency_score(published_year: int | None, *, current_year: int | None = None) -> float:
    if published_year is None:
        return 0.36

    safe_current_year = int(current_year or datetime.utcnow().year)
    age = max(0, safe_current_year - int(published_year))
    if age <= 1:
        return 1.0
    if age <= 3:
        return 0.86
    if age <= 5:
        return 0.74
    if age <= 8:
        return 0.58
    if age <= 12:
        return 0.42
    return 0.28


def descendant_momentum(descendant_count: int) -> float:
    safe_descendants = max(0, int(descendant_count or 0))
    score = 1 - math.exp(-safe_descendants / 6.0)
    return clamp01(score)


def compute_heat_score(
    *,
    citation_count: int,
    published_year: int | None,
    descendant_count: int,
    current_year: int | None = None,
) -> float:
    citation = normalize_citation_count(citation_count)
    recency = recency_score(published_year, current_year=current_year)
    momentum = descendant_momentum(descendant_count)
    score = citation * 0.45 + recency * 0.30 + momentum * 0.25
    return clamp01(score)


def compute_controversy_score(*, contradicting_count: int, total_relations: int) -> float:
    safe_contradicting = max(0, int(contradicting_count or 0))
    safe_total = max(0, int(total_relations or 0))
    if safe_total <= 0:
        return 0.0
    return clamp01(safe_contradicting / safe_total)


def resolve_trend_label(
    *,
    heat_score: float,
    controversy_score: float,
    published_year: int | None,
    current_year: int | None = None,
) -> PaperSignalTrendLabel:
    safe_heat = clamp01(float(heat_score or 0.0))
    safe_controversy = clamp01(float(controversy_score or 0.0))
    recent_score = recency_score(published_year, current_year=current_year)

    if safe_controversy >= 0.34:
        return "controversial"
    if safe_heat >= 0.72 and recent_score >= 0.55:
        return "rising"
    if safe_heat >= 0.45:
        return "steady"
    return "cooling"
