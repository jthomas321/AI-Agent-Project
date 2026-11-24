"""

Two jobs, both kept here:

1. recommend(request, desserts) -> candidates
   The filter the pipeline uses today. Unchanged.

2. score_businesses(desserts) -> list of business score records
   Reads dessert records from research, finds each business on Google Places and
   Yelp, collects reviews, asks Ollama for text-based judgments, and computes a
   deterministic recommendation score per business. The ranking agent uses
   lookup_score(records, dessert) to attach the score to a dessert. The records
   can also be written to config.REVIEW_OUTPUT_PATH with write_scores().

Scoring rules:
- Missing data is not zero. A component with no evidence is left out, and the
  weights are renormalized over the rest.
- A business with no reviews gets no score (None) and confidence "unknown".
- Ollama supplies only text-based judgments. Python computes the final number.

Contract for recommend(): exclude a dessert only when the data proves a mismatch.
Unknown values pass through. Preserve dessert_id and evidence. Do not change facts.

Command line (scores the configured mock file, or a file you pass):
    python -m agents.recommendation_agent [path/to/desserts.json] [--output path]
"""

import argparse
import copy
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import config
from models import validate_dessert
from tools.business_match import business_key  # noqa: F401  (re-exported for callers)
from tools.review_apis import (
    NotConfigured,
    RateLimited,
    SourceUnavailable,
    build_source,
)
from tools.review_ollama import analyze_reviews
from tools.review_scoring import compute_business_score, parse_review_date

logger = logging.getLogger(__name__)

EXCERPT_CHARS = 200
MAX_DESSERT_NAMES = 10


def recommend(request, desserts):
    return [d for d in desserts if _fits(request, d)]


def _fits(request, dessert):
    if request["flavor"] and dessert["flavors"]:
        if request["flavor"] not in [f.lower() for f in dessert["flavors"]]:
            return False

    if request["dessert_type"] and dessert["dessert_type"]:
        if dessert["dessert_type"].lower() != request["dessert_type"]:
            return False

    if (request["max_price"] is not None and dessert["price"] is not None
            and dessert.get("price_status") != "estimated"):
        if dessert["price"] > request["max_price"]:
            return False

    if request["max_distance_miles"] is not None and dessert["distance_miles"] is not None:
        if dessert["distance_miles"] > request["max_distance_miles"]:
            return False

    return True


# Business-level scoring


def default_sources() -> Dict[str, Any]:
    sources = {}
    for platform in config.REVIEW_SOURCES:
        source = build_source(platform)
        if source is None:
            logger.warning("Unknown review source in config: %s", platform)
            continue
        sources[platform] = source
    return sources


def _group_by_business(desserts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for dessert in desserts:
        key = business_key(dessert)
        group = groups.setdefault(key, {
            "business": dessert["business"],
            "address": dessert.get("address"),
            "dessert_ids": [],
            "dessert_names": [],
        })
        group["dessert_ids"].append(dessert["dessert_id"])
        if dessert["name"] and dessert["name"] not in group["dessert_names"]:
            group["dessert_names"].append(dessert["name"])
    return groups


MIN_TEXT_FOR_DEDUPE = 40  # shorter texts ("Great!") are common and must not be merged


def _review_keys(review: Dict[str, Any]) -> List[str]:
    """A review is a duplicate if it repeats a platform review ID, or if it repeats
    the same substantial text (for example, one review shown on both platforms)."""
    keys = []
    if review.get("review_id"):
        keys.append(f"id|{review.get('platform')}|{review['review_id']}")
    text = " ".join((review.get("text") or "").lower().split())
    if len(text) >= MIN_TEXT_FOR_DEDUPE:
        keys.append(f"text|{text}")
    return keys


def _dedupe_reviews(reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for review in reviews:
        keys = _review_keys(review)
        if any(k in seen for k in keys):
            continue
        seen.update(keys)
        unique.append(review)
    return unique


def score_businesses(
    desserts: List[Dict[str, Any]],
    sources: Optional[Dict[str, Any]] = None,
    analyzer: Optional[Callable[..., Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Score every business that appears in the dessert records."""
    now = now or datetime.now(timezone.utc)
    sources = default_sources() if sources is None else sources
    analyzer = analyzer or analyze_reviews
    for dessert in desserts:
        validate_dessert(dessert)

    # Circuit breakers: once a source is rate limited, or Ollama is down, stop calling it this run.
    state = {"sources": {p: "ok" for p in sources}, "ollama": "ok"}
    records = []
    for key, group in _group_by_business(desserts).items():
        records.append(_score_group(key, group, sources, analyzer, now, state))
    return records


def _query_platform(platform, source, group, state):
    """Find and fetch one platform's listing. Returns (report, (rating, count) or None, reviews)."""
    report: Dict[str, Any] = {"platform": platform, "status": None}
    if state["sources"][platform] != "ok":
        report["status"] = "skipped_" + state["sources"][platform]
        return report, None, []
    try:
        listing, reason = source.find_business(group["business"], group["address"])
        report["status"] = reason
        if listing is None:
            return report, None, []
        details = source.fetch_reviews(listing)
        report.update({
            "business_id": listing["id"],
            "rating": details.get("rating"),
            "review_count": details.get("review_count"),
            "url": listing.get("url"),
            "reviews_received": len(details.get("reviews", [])),
        })
        reviews = [dict(r, platform=platform) for r in details.get("reviews", [])]
        return report, (details.get("rating"), details.get("review_count")), reviews
    except NotConfigured:
        report["status"] = "not_configured"
    except RateLimited:
        report["status"] = "rate_limited"
        state["sources"][platform] = "rate_limited"
        logger.warning("%s rate limited; skipping it for the rest of this run", platform)
    except SourceUnavailable as exc:
        report["status"] = "unavailable"
        report["reason"] = str(exc)
    return report, None, []


def _score_group(key, group, sources, analyzer, now, state):
    reports: Dict[str, Dict[str, Any]] = {}
    platform_ratings = []
    all_reviews: List[Dict[str, Any]] = []

    for platform, source in sources.items():
        report, ratings, reviews = _query_platform(platform, source, group, state)
        reports[platform] = report
        if ratings is not None:
            platform_ratings.append(ratings)
        all_reviews.extend(reviews)

    unique = _dedupe_reviews(all_reviews)
    texts = [r for r in unique if (r.get("text") or "").strip()]
    for index, review in enumerate(texts, start=1):
        review["id"] = f"R{index}"

    if not texts:
        analysis = {"status": "no_reviews"}  # nothing to read, so the model is not called
    elif state["ollama"] == "down":
        analysis = {"status": "unavailable", "reason": "skipped after an earlier failure"}
    else:
        analysis = analyzer(group["business"], group["dessert_names"][:MAX_DESSERT_NAMES], texts)
        if analysis.get("status") == "unavailable":
            state["ollama"] = "down"
            logger.warning("Ollama unavailable; analysis skipped for the rest of this run")

    dates = [parse_review_date(r.get("date")) for r in unique]
    scored = compute_business_score(
        platform_ratings=platform_ratings,
        review_dates=dates,
        analysis=analysis,
        text_count=len(texts),
        now=now,
    )

    cited = set(analysis.get("review_ids_used") or [])
    evidence = [_evidence(r) for r in texts if r["id"] in cited]
    notes = []
    if analysis.get("status") != "ok":
        notes.append(f"Review analysis: {analysis.get('status')}.")
    if not platform_ratings:
        notes.append("No platform ratings found for this business.")

    google = reports.get("google", {})
    yelp = reports.get("yelp", {})
    return {
        "business_key": key,
        "business_name": group["business"],
        "address": group["address"],
        "dessert_ids": group["dessert_ids"],
        "google_rating": google.get("rating"),
        "google_review_count": google.get("review_count"),
        "yelp_rating": yelp.get("rating"),
        "yelp_review_count": yelp.get("review_count"),
        "review_count_used": len(texts),
        "combined_rating": scored["combined_rating"],
        "total_ratings": scored["total_ratings"],
        "rating_score": scored["components"]["ratings"],
        "sentiment_score": scored["components"]["sentiment"],
        "dessert_quality_score": scored["components"]["dessert_quality"],
        "review_recency_score": scored["components"]["recency"],
        "recommendation_score": scored["recommendation_score"],
        "evidence_coverage": scored["evidence_coverage"],
        "confidence": scored["confidence"],
        "is_dessert_related": bool(analysis.get("is_dessert_related", False)),
        "positive_themes": analysis.get("positive_themes", []),
        "negative_themes": analysis.get("negative_themes", []),
        "dessert_complaints": analysis.get("dessert_complaints", []),
        "taste_flavor_notes": analysis.get("taste_flavor_notes"),
        "texture_freshness_notes": analysis.get("texture_freshness_notes"),
        "analysis_status": analysis.get("status"),
        "platforms": reports,
        "evidence": evidence,
        "sources": [
            {"platform": p, "status": r.get("status"), "url": r.get("url")}
            for p, r in reports.items()
        ],
        "notes": notes,
        "last_checked": now.isoformat(),
    }


def _evidence(review: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join((review.get("text") or "").split())
    return {
        "review_id": review["id"],
        "platform": review.get("platform"),
        "rating": review.get("rating"),
        "date": review.get("date"),
        "excerpt": text[:EXCERPT_CHARS],
        "url": review.get("url"),
    }


def lookup_score(records: List[Dict[str, Any]], dessert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the business score record for a dessert, or None if it was not scored."""
    key = business_key(dessert)
    for record in records:
        if record["business_key"] == key:
            return record
    return None


def _for_storage(record: Dict[str, Any]) -> Dict[str, Any]:
    """Copy of a record that is safe to write to disk.

    Google review text and Google links are removed, because Google's caching and
    storage terms do not allow saving them. Scores, Yelp excerpts, and Google's
    ratings and counts are kept. The in-memory records used by the pipeline are not changed.
    """
    stored = copy.deepcopy(record)
    for item in stored["evidence"]:
        if item.get("platform") == "google":
            item["excerpt"] = None
            item["url"] = None
    for source in stored["sources"]:
        if source.get("platform") == "google":
            source["url"] = None
    for report in stored["platforms"].values():
        if report.get("platform") == "google":
            report["url"] = None
    return stored


def write_scores(records: List[Dict[str, Any]], path=None) -> str:
    path = str(path or config.REVIEW_OUTPUT_PATH)
    folder = os.path.dirname(path)
    if folder:  # a bare filename such as "scores.json" has no folder to create
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([_for_storage(r) for r in records], f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


# Command line

def _load_desserts(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise ValueError("input must be a JSON list of dessert records")
    return [validate_dessert(r) for r in records]


def _print_summary(records: List[Dict[str, Any]]) -> None:
    for record in records:
        score = record["recommendation_score"]
        score_text = str(score) if score is not None else "no score"
        print(f"- {record['business_name']}: score {score_text}, confidence {record['confidence']}")
        for platform, report in record["platforms"].items():
            rating = report.get("rating")
            if rating is not None:
                detail = f"rating {rating} from {report.get('review_count')} reviews"
            else:
                detail = f"no rating ({report.get('status')})"
            print(f"    {platform}: {detail}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Score dessert businesses from review data.")
    parser.add_argument("input", nargs="?", default=str(config.MOCK_DATA_PATH),
                        help="JSON list of dessert records (default: the configured mock file)")
    parser.add_argument("--output", default=None, help="where to write scores (default: config)")
    args = parser.parse_args(argv)

    try:
        desserts = _load_desserts(args.input)
    except (OSError, ValueError) as exc:
        print(f"Could not read {args.input}: {exc}", file=sys.stderr)
        return 1

    records = score_businesses(desserts)
    path = write_scores(records, args.output)
    print(f"Scored {len(records)} business(es). Wrote {path}")
    _print_summary(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
