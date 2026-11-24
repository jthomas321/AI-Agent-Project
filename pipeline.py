"""Fixed agent sequence for Sweetery.

run_pipeline(request) is the only function the UI calls. It always returns a
PipelineResult, even when an agent fails, so the UI never crashes.

Flow: normalize -> research -> price estimates (missing only) -> review scoring -> screen -> check
      -> (re-search if needed) -> rank

The result also exposes all_desserts for the Streamlit research-results table.
"""

import copy
import logging
import math
from typing import Any, Dict, List, Optional
from agents.pricing_step import estimate_missing_prices
import config
from agents.checking_agent import check
from agents.ranking_agent import rank
from agents.recommendation_agent import score_businesses
from agents.screening_agent import screen
from agents.research_agent import research
#from agents.price_prediction_agent import predict_price
from models import PipelineResult, normalize_request, validate_dessert
from tools.business_hours import hours_for_businesses
from agents.screening_agent import (
    screen,
    normalize_business_names,
)
from tools.processed_cache import (
    load_processed_cache,
    save_processed_cache,
)

from tools.business_ratings_cache import (
    initialize_csv,
    load_business_ratings,
)
logger = logging.getLogger(__name__)


def run_pipeline(
    raw_request: Dict[str, Any], on_step=None
) -> PipelineResult:
    log: List[str] = []
    pool: Dict[str, Dict[str, Any]] = {}
    checking_results = []
    def progress(stage, message):
        log.append(message)
        if on_step is not None:
            on_step(stage, message)

    try:
        request = normalize_request(raw_request)
    except ValueError as exc:
        return _result("error", f"Please check your request: {exc}", log=log)

    log.append(f"Request: {request}")

    try:
        initialize_csv()

        # =========================================
        # PROCESSED CACHE LOOKUP
        # =========================================

        cache_hit = False
        cached_data = None

        if config.PROCESSED_CACHE_ENABLED:
            cache_hit, cached_data = load_processed_cache(
                request
            )

        if cache_hit:

            # =====================================
            # PROCESSED CACHE HIT
            # =====================================

            progress(
                "cache",
                "PROCESSED CACHE HIT"
            )

            eligible_checked = cached_data[
                "checked_candidates"
            ]

            checking_results = cached_data[
                "checking_results"
            ]

            pool = {
                dessert["dessert_id"]: dessert
                for dessert in cached_data["all_desserts"]
            }

            review_records = load_business_ratings()

            hours_records = []

            log.append(
                f"Loaded {len(eligible_checked)} "
                f"processed desserts"
            )

        else:

            # =====================================
            # PROCESSED CACHE MISS
            # =====================================

            progress(
                "cache",
                "PROCESSED CACHE MISS"
            )

            if config.DEMO_MODE:
                return _result(
                    "no_match",
                    "No processed cache exists for this search.",
                    log=log,
                )

            # Remove budget and distance restrictions
            # during cache preparation.

            processing_request = copy.deepcopy(request)

            processing_request["max_price"] = None
            processing_request["max_distance_miles"] = None

            # =====================================
            # RESEARCH
            # =====================================

            progress(
                "research",
                "Retrieving research results..."
            )

            _research_into(
                pool,
                processing_request,
                attempt=1,
                log=log,
            )

            # =====================================
            # SCREENING, PRICING, RATINGS, CHECKING
            # =====================================

            progress(
                "screening",
                "Reviewing, screening, and checking desserts..."
            )

            checked, review_records = _screen_and_check(
                processing_request,
                pool,
                log,
            )

            checking_results = checked

            eligible_checked = [
                candidate
                for candidate in checked
                if candidate["check"].get(
                    "eligible_for_ranking", False
                )
            ]

            log.append(
                f"Checking Agent: {len(eligible_checked)} "
                f"of {len(checked)} desserts eligible for ranking"
            )

            # =====================================
            # SAVE PROCESSED CACHE
            # =====================================
            print("========== CACHE DEBUG ==========")
            print("Cache enabled:", config.PROCESSED_CACHE_ENABLED)
            print("Demo mode:", config.DEMO_MODE)
            print("Data source:", config.DATA_SOURCE)
            print("Eligible desserts:", len(eligible_checked))
            print("Processing request:", processing_request)
            print("Cache directory:", config.PROCESSED_CACHE_DIR)
            print("=================================")

            if (
                config.PROCESSED_CACHE_ENABLED
                and config.DATA_SOURCE == "live"
                and eligible_checked
            ):
                saved = save_processed_cache(
                    processing_request,
                    checked_candidates=eligible_checked,
                    all_desserts=list(pool.values()),
                    checking_results=checking_results,
                )

                print("Cache saved:", saved)

                if saved:
                    progress("cache", "PROCESSED CACHE SAVED")
                else:
                    progress("cache", "PROCESSED CACHE SAVE FAILED")

            else:
                progress(
                    "cache",
                    f"CACHE SAVE SKIPPED: "
                    f"enabled={config.PROCESSED_CACHE_ENABLED}, "
                    f"source={config.DATA_SOURCE}, "
                    f"eligible={len(eligible_checked)}"
                )

            # =====================================
            # BUSINESS HOURS
            # =====================================

            try:

                hours_records = hours_for_businesses(
                    [
                        candidate["dessert"]
                        for candidate in eligible_checked
                    ]
                )

                log.append(
                    f"Yelp hours retrieved for "
                    f"{len(hours_records)} business(es)"
                )

            except Exception:

                logger.exception(
                    "Yelp hours lookup failed"
                )

                hours_records = []

                log.append(
                    "Yelp hours unavailable"
                )

        # =========================================
        # RANKING
        # =========================================

        progress(
            "ranking",
            "Ranking the best desserts..."
        )

        ranked = rank(
            request,
            eligible_checked,
            recommendation_scores=review_records,
            hours_records=hours_records,
        )
    except NotImplementedError as exc:
        logger.warning("Agent not implemented: %s", exc)
        return _result(
            "error", "A search component is not connected yet. See the README.",
            log=log, all_desserts=list(pool.values()), checking_results=checking_results
        )
    except ValueError:
        logger.exception("Agent returned data in the wrong shape")
        return _result(
            "error", "Some returned data did not match the shared format.",
            log=log, all_desserts=list(pool.values()),
        )
    except Exception:
        logger.exception("Pipeline failed")
        return _result(
            "error", "Something went wrong while searching. Please try again.",
            log=log, all_desserts=list(pool.values()),
        )

    all_desserts = list(pool.values())

    if not ranked:
        return _result(
            "no_match",
            "No desserts matched your request. Try a different flavor, a higher budget, or a broader dessert type.",
            log=log,
            all_desserts=all_desserts,
            checking_results=checking_results
        )

    unconfirmed = sum(1 for r in ranked if r["check"]["status"] != "verified")
    message = f"Found {len(ranked)} option(s)."
    if unconfirmed:
        message += f" {unconfirmed} still have unconfirmed details; these are marked below."
    return _result(
        "ok", message, results=ranked, log=log, all_desserts=all_desserts, checking_results=checking_results
    )


def _research_into(pool, request, attempt, log):
    records = research(request, attempt=attempt)
    records = normalize_business_names(copy.deepcopy(records))
    for record in records:
        validate_dessert(record)
        pool[record["dessert_id"]] = record  # newer records replace older ones by ID
    log.append(f"Research attempt {attempt}: {len(records)} record(s)")

def _prediction_category(dessert):
    """Map clearly identified items to an existing model category.

    Do not invent a category for a vague or ambiguous item.
    """
    name = (dessert.get("name") or "").casefold()
    kind = (dessert.get("dessert_type") or "").casefold().strip()
    if "frozen yogurt" in name or "froyo" in name or kind == "frozen yogurt":
        return "ice cream"
    if kind and kind not in {"unknown", "other", "any", "none"}:
        return kind
    keywords = (
        ("cheesecake", "cheesecake"), ("cupcake", "cupcake"),
        ("brownie", "brownie"), ("cookie", "cookie"),
        ("macaron", "macaron"), ("muffin", "muffin"),
        ("donut", "donut"), ("doughnut", "donut"),
        ("ice cream", "ice cream"), ("gelato", "ice cream"),
        ("sorbet", "ice cream"), ("cake", "cake"),
        ("pie", "pie"), ("pastry", "pastry"),
        ("croissant", "pastry"), ("milkshake", "milkshake"),
        ("sundae", "sundae"),
    )
    for word, category in keywords:
        if word in name:
            return category
    return None


def _valid_positive_price(value):
    try:
        number = float(value)
        return math.isfinite(number) and number > 0
    except (ValueError, TypeError):
        return False


def _estimate_missing_prices(desserts, log):
    """Estimate missing/invalid prices only for identifiable dessert items.

    Predictions are not menu evidence and must remain unverified.
    """
    predicted = 0
    for dessert in desserts:
        if _valid_positive_price(dessert.get("price")):
            continue
        dessert["price"] = None  # Never pass $0 or invalid values to UI.
        dessert.pop("price_lower", None)
        dessert.pop("price_upper", None)
        dessert.pop("price_status", None)
        name = dessert.get("name")
        category = _prediction_category(dessert)
        if not name or not category:
            log.append(f"Price not estimated (unidentified category): {name}")
            continue
        try:
            result = predict_price(name, category)
            point = result.get("price")
            lower = result.get("price_lower")
            upper = result.get("price_upper")
            if not all(_valid_positive_price(v) for v in (point, lower, upper)):
                log.append(f"Price prediction returned invalid range for {name}")
                continue
            if float(lower) > float(upper):
                log.append(f"Price prediction returned reversed range for {name}")
                continue
        except Exception as exc:
            logger.exception("Price prediction failed for %s", name)
            log.append(f"Price prediction failed for {name}: {exc}")
            continue
        dessert["price"] = float(point)
        dessert["price_lower"] = float(lower)
        dessert["price_upper"] = float(upper)
        dessert["price_status"] = "estimated"
        dessert["price_verified"] = False
        dessert["price_prediction_source"] = result.get("source", "price model")
        predicted += 1
    log.append(f"Price prediction: estimated {predicted} missing/invalid price(s)")


def _screen_and_check(request, pool, log):
    kept = screen(list(pool.values()), log=log)
    priced = estimate_missing_prices(kept, log=log)
    records = _review_scores(priced, log)
    checked = check(priced, request=request)
    log.append(f"Checked {len(checked)} record(s) after pricing")
    # Second pricing pass after dessert classification
    for candidate in checked:
        dessert = candidate["dessert"]

        if (
            candidate["check"].get("eligible_for_ranking")
            and dessert.get("price") is None
        ):
            updated = estimate_missing_prices([dessert], log=log)

            if updated:
                candidate["dessert"] = updated[0]

    log.append("Completed second pricing pass")
    return checked, records


def _review_scores(desserts, log):
    """Business records for every candidate. Return [] if ratings are unavailable."""
    if not config.REVIEW_SCORING_ENABLED or not desserts:
        return []
    try:
        records = score_businesses(desserts)
    except Exception:
        logger.exception("Review scoring failed; screening without ratings")
        log.append("Review scoring unavailable; screened without ratings")
        return []
    scored = sum(1 for r in records if r["recommendation_score"] is not None)
    log.append(f"Review scoring: {scored} of {len(records)} business(es) have a review score")
    return records


def _needs_research(checked):
    return any(c["check"]["status"] == "needs_research" for c in checked)


def _mark_unresolved_as_unknown(checked, log):
    resolved = []
    for candidate in checked:
        if candidate["check"]["status"] == "needs_research":
            candidate = copy.deepcopy(candidate)
            candidate["dessert"]["verification_status"] = "unknown"
            candidate["check"]["status"] = "unknown"
            candidate["check"]["notes"] += (
                f" Details could not be confirmed from the available evidence." #edited this line
            )
            log.append(f"Marked {candidate['dessert']['dessert_id']} as unknown after re-search")
        resolved.append(candidate)
    return resolved


def _result(
    status: str,
    message: str,
    results: Optional[list] = None,
    log: Optional[list] = None,
    all_desserts: Optional[list] = None,
    checking_results: Optional[list] = None,
) -> PipelineResult:
    return {
        "status": status,
        "message": message,
        "results": results if results is not None else [],
        "log": log if log is not None else [],
        "all_desserts": all_desserts if all_desserts is not None else [],
        "checking_results": checking_results if checking_results is not None else [],
    }
