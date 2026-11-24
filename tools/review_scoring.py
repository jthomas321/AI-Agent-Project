"""Deterministic recommendation scoring. Python does all arithmetic.

Components, each on a 0-100 scale, or None when there is no evidence for it:
- ratings: star ratings from all platforms, combined with Bayesian smoothing
  (weighted by review count, pulled toward a prior mean), then mapped from
  1-5 stars to 0-100.
- sentiment: Ollama's sentiment_score for the business's reviews.
- dessert_quality: Ollama's dessert_quality_score (dessert-specific feedback only).
- recency: average of exponential decay over the sampled review dates.

Final score = weighted mean of the components that exist, with weights
renormalized over those components. A missing component is not counted as
zero. If no component exists, the score is None.

Confidence (a separate label, not part of the number):
- "unknown": no score
- "high": enough ratings and reviews, sentiment present, dessert-related, sufficient evidence
- "medium": sentiment present and enough ratings or reviews, sufficient evidence
- "low": anything else that has a score
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

import config

COMPONENTS = ("ratings", "sentiment", "dessert_quality", "recency")


def default_weights() -> Dict[str, float]:
    return {
        "ratings": config.WEIGHT_RATINGS,
        "sentiment": config.WEIGHT_SENTIMENT,
        "dessert_quality": config.WEIGHT_DESSERT_QUALITY,
        "recency": config.WEIGHT_RECENCY,
    }


def parse_review_date(value: Optional[str]) -> Optional[datetime]:
    """Accept ISO 8601 (Google) or 'YYYY-MM-DD HH:MM:SS' (Yelp). Returns an aware UTC datetime."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def rating_to_score(rating: Optional[float]) -> Optional[float]:
    """Map a 1-5 star rating to 0-100. None stays None."""
    if rating is None:
        return None
    return max(0.0, min(100.0, (float(rating) - 1.0) / 4.0 * 100.0))


def combined_rating(
    platform_ratings: Iterable[Tuple[Optional[float], Optional[int]]],
    prior_mean: Optional[float] = None,
    prior_count: Optional[float] = None,
) -> Tuple[Optional[float], int]:
    """Bayesian-smoothed star rating across platforms.

    platform_ratings: (rating, review_count) pairs. A pair with a missing rating
    or a zero/missing count is skipped (it cannot be weighted).
    Returns (combined_rating or None if no usable pairs, total review count).
    """
    prior_mean = config.RATING_PRIOR_MEAN if prior_mean is None else prior_mean
    prior_count = config.RATING_PRIOR_COUNT if prior_count is None else prior_count

    total_n = 0
    weighted_sum = 0.0
    for rating, count in platform_ratings:
        if rating is None or not count or count <= 0:
            continue
        weighted_sum += float(rating) * count
        total_n += count
    if total_n == 0:
        return None, 0
    combined = (prior_count * prior_mean + weighted_sum) / (prior_count + total_n)
    return combined, total_n


def recency_score(
    dates: Iterable[Optional[datetime]],
    now: datetime,
    half_life_days: Optional[float] = None,
) -> Optional[float]:
    """Mean exponential decay: a review from today scores 100, one half_life old scores 50."""
    half_life = config.RECENCY_HALF_LIFE_DAYS if half_life_days is None else half_life_days
    values = []
    for when in dates:
        if when is None:
            continue
        age_days = max(0.0, (now - when).total_seconds() / 86400.0)
        values.append(100.0 * 0.5 ** (age_days / half_life))
    if not values:
        return None
    return sum(values) / len(values)


def weighted_score(
    components: Dict[str, Optional[float]],
    weights: Dict[str, float],
) -> Tuple[Optional[int], float]:
    """Return (score rounded to int or None, evidence coverage 0-1).

    Coverage is the share of the total configured weight backed by evidence.
    """
    total_weight = sum(weights.get(k, 0.0) for k in COMPONENTS)
    available = {
        k: v for k, v in components.items()
        if v is not None and weights.get(k, 0.0) > 0
    }
    available_weight = sum(weights[k] for k in available)
    if not available or available_weight <= 0 or total_weight <= 0:
        return None, 0.0
    score = sum(weights[k] * available[k] for k in available) / available_weight
    coverage = available_weight / total_weight
    return int(round(score)), round(coverage, 2)


def confidence_level(
    *,
    has_score: bool,
    total_ratings: int,
    text_count: int,
    has_sentiment: bool,
    dessert_related: bool,
    evidence_sufficient: bool,
) -> str:
    if not has_score:
        return "unknown"
    if (
        has_sentiment and dessert_related and evidence_sufficient
        and total_ratings >= 50 and text_count >= 5
    ):
        return "high"
    if has_sentiment and evidence_sufficient and (total_ratings >= 10 or text_count >= 3):
        return "medium"
    return "low"


def compute_business_score(
    *,
    platform_ratings: Iterable[Tuple[Optional[float], Optional[int]]],
    review_dates: Iterable[Optional[datetime]],
    analysis: Dict[str, Any],
    text_count: int,
    now: datetime,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Combine all evidence for one business into a score and confidence."""
    weights = weights or default_weights()
    rating_value, total_ratings = combined_rating(platform_ratings)

    analysis_ok = analysis.get("status") == "ok"
    sentiment = analysis.get("sentiment_score") if analysis_ok else None
    dessert = analysis.get("dessert_quality_score") if analysis_ok else None
    dessert_related = bool(analysis.get("is_dessert_related")) if analysis_ok else False
    evidence_sufficient = bool(analysis.get("evidence_sufficient")) if analysis_ok else False

    components = {
        "ratings": rating_to_score(rating_value),
        "sentiment": sentiment,
        "dessert_quality": dessert,
        "recency": recency_score(review_dates, now),
    }
    score, coverage = weighted_score(components, weights)
    confidence = confidence_level(
        has_score=score is not None,
        total_ratings=total_ratings,
        text_count=text_count,
        has_sentiment=sentiment is not None,
        dessert_related=dessert_related,
        evidence_sufficient=evidence_sufficient,
    )
    return {
        "combined_rating": round(rating_value, 2) if rating_value is not None else None,
        "total_ratings": total_ratings,
        "components": {k: (round(v, 1) if v is not None else None) for k, v in components.items()},
        "recommendation_score": score,
        "evidence_coverage": coverage,
        "confidence": confidence,
    }
