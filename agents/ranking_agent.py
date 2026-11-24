"""Ranking agent.


rank(request, checked_candidates, recommendation_scores=None, hours_records=None) -> list of RankedResult
(at most config.MAX_RESULTS, numbered 1, 2, 3 ...).

Steps:
1. Validate each checked candidate. Malformed records and duplicate dessert_ids are skipped.
2. Enforce essential requirements. These are pass/fail, not scored: verification status
   (needs_research is excluded), an address in Cookeville, the requested dessert type,
   a confirmed price over max_price, and a known distance over max_distance_miles.
   Unconfirmed prices are never used to exclude a candidate.
3. Score eligible desserts with rating (7.5%), open hours (7.5%), flavor (25%),
   dessert type (25%), location (15%), and relative price (20%).
   Missing data is never treated as zero. It gets a neutral value, so a candidate is
   neither rewarded nor penalized for a platform that has no data. Ratings with no data
   use a neutral score.
4. Compare confirmed prices or estimated range midpoints across eligible desserts.
   The lowest gets 20/20 price points; more expensive desserts get fewer.
   Sort exact dessert types before related types, then flavor, hours, score and reviews.
   Keep the top config.MAX_RESULTS, preferring distinct businesses.
5. Ollama (when config.RANK_MODE is "ollama") writes an explanation and concerns for each
   selected result. Its output is checked: unknown IDs are dropped, every number must come
   from the facts Python provided, and any failure falls back to a rules-based explanation.
   Ollama never changes the selection or the order.
"""

import json
import logging
import math
import re
from datetime import datetime

import config
from agents.recommendation_agent import business_key
from models import validate_check_result, validate_dessert
from tools.business_hours import hours_text, is_open_at
from tools.ollama_client import ask_json
from tools.review_scoring import combined_rating, rating_to_score
from tools.dessert_match import DESSERT_FALLBACKS
from agents.recommendation_agent import business_key
from agents.price_prediction_agent import fallback_price
logger = logging.getLogger(__name__)

RANKABLE_STATUSES = ("verified", "unknown")
MAX_EXPLANATION_CHARS = 400
MAX_CONCERNS = 3
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
NUMBER_TOLERANCE = 0.05
FIELD_NAME = re.compile(r"\b[a-z]+_[a-z_]+\b", re.IGNORECASE)
NEGATIVE_VERDICT = re.compile(r"\b(not suit|does not suit|doesn't suit|unsuitable|not a match)\b",
                              re.IGNORECASE)
# Related desserts are only used to fill slots after exact-type candidates.
'''
DESSERT_FALLBACKS = {
    "cupcake": ("muffin",),
    "cake": ("cheesecake",),
}
'''
DESSERT_ALIASES = {
    "cakes": "cake", "cupcakes": "cupcake", "cheesecakes": "cheesecake",
    "cookies": "cookie", "brownies": "brownie", "pies": "pie",
    "pastries": "pastry", "donuts": "donut", "doughnuts": "donut",
    "ice creams": "ice cream", "macarons": "macaron", "muffins": "muffin",
}
GENERIC_NAME_WORDS = (
    "ice cream", "soft serve", "milkshake", "shake", "sundae", "gelato",
    "cupcakes", "cupcake", "cakes", "cake", "cookies", "cookie",
    "donuts", "donut", "doughnut", "brownie", "blondie", "pie", "tart",
    "cheesecake", "pastry", "croissant", "muffin", "macaron",
    "dessert", "scoop", "cone", "bar", "plain", "bean", "french", "classic", "milk", "dark", "double", "triple", "mousse", "nsa",
)


def _canonical_type(value):
    name = (_text(value) or "").casefold().strip()
    return DESSERT_ALIASES.get(name, name)


def _strip_generic(text):
    for word in sorted(GENERIC_NAME_WORDS, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(word) + r"(?!\w)", " ", text)
    return text.strip(" -_,")


RANK_WEIGHTS = {
    "rating": 0.075,
    "hours": 0.075,
    "flavor": 0.25,
    "dessert": 0.25,
    "location": 0.15,
    "price": 0.20,
}


# Entry point

def rank(request, checked_candidates, recommendation_scores=None, hours_records=None):
    records = _index_records(recommendation_scores)
    hours_index = _index_hours(hours_records)
    now = datetime.now()

    wanted_flavor = _requested_flavor(request)
    wanted_type = _canonical_type(request.get("dessert_type"))

    eligible = []
    for candidate in _valid_candidates(checked_candidates):
        failures = _essential_failures(request, candidate)

        dessert = candidate["dessert"]

        print(
            "RANKING DEBUG:",
            dessert.get("name"),
            "| Business:", dessert.get("business"),
            "| Address:", dessert.get("address"),
            "| Failures:", failures
        )
        print("\n========== LAZY COW DEBUG ==========")
        print("Name:", dessert.get("name"))
        print("Business:", dessert.get("business"))
        print("Dessert type:", dessert.get("dessert_type"))
        print("Flavors:", dessert.get("flavors"))
        print("Address:", dessert.get("address"))
        print("Check status:", candidate["check"]["status"])
        print("Requested type:", request.get("dessert_type"))
        print("Requested flavor:", wanted_flavor)
        print(
            "Flavor tier:",
            _flavor_match_tier(dessert, wanted_flavor)
            if wanted_flavor else "Any"
        )
        print("Failures:", failures)
        print("====================================")

        if failures:
            continue
        if _ranking_price(candidate) is None:
            price = _number(dessert.get("price"))

            if price is None or price <= 0:
                dessert.update(fallback_price())
        record = records.get(business_key(candidate["dessert"]))
        hours_record = hours_index.get(business_key(candidate["dessert"]))
        raw_score, facts = _score(request, candidate, record, hours_record, now)
        eligible.append((raw_score, candidate, record, facts))

    # Compare prices across all eligible desserts before sorting and selecting top results.
    eligible = _apply_relative_price_scores(eligible)
    eligible.sort(key=_sort_key)
    print("\n========== SORTED ELIGIBLE DESSERTS ==========")

    for position, (score, candidate, record, facts) in enumerate(
        eligible, start=1
    ):
        dessert = candidate["dessert"]

        print(
            position,
            "| Name:", dessert.get("name"),
            "| Business:", dessert.get("business"),
            "| Type:", dessert.get("dessert_type"),
            "| Flavor:", facts["flavor_availability"],
            "| Open:", facts["open_now"],
            "| Score:", round(score, 1)
        )

    print("=============================================")
    # Flavor searches can include multiple exact-flavor matches from one shop.
    # No-flavor searches prefer distinct businesses, then fill with best remaining items.
        # Allow repeated businesses when both dessert type
    # and flavor are specifically requested.
    # Otherwise, prioritize distinct businesses.
    #wanted_flavor = _requested_flavor(request)
    #wanted_type = _canonical_type(request.get("dessert_type"))

    selected = _select_top(
        eligible,
        config.MAX_RESULTS,
        per_business=None if wanted_type and wanted_flavor else 1,
        fill_repeats=True,
    )
    print("MAX_RESULTS:", config.MAX_RESULTS)
    print("Eligible for ranking:", len(eligible))
    print("Selected results:", len(selected))
    explanations = _explain(request, selected)

    results = []
    for position, (_, candidate, record, facts) in enumerate(selected, start=1):
        text, concerns, source = explanations[facts["dessert_id"]]
        results.append({
            "rank": position,
            "dessert": candidate["dessert"],
            "check": candidate["check"],
            "reason": _reason(facts),
            "recommendation": _recommendation_summary(record),
            "score": facts["score"],
            "score_breakdown": facts["components"],
            "ratings": {
                "google": facts["google"],
                "yelp": facts["yelp"],
                "combined_rating": facts["combined_rating"],
                "total_reviews": facts["total_reviews"],
            },
            "flavor_availability": facts["flavor_availability"],
            "business_hours": facts["hours"],
            "open_now": facts["open_now"],
            "verification_status": facts["verification_status"],
            "match_type": facts["match_type"],
            "explanation": text,
            "concerns": concerns,
            "explanation_source": source,
        })
    return results


# Validation and essential requirements

def _valid_candidates(checked_candidates):
    seen = set()
    valid = []
    for candidate in checked_candidates or []:
        try:
            dessert = validate_dessert(candidate["dessert"])
            check = validate_check_result(candidate["check"])
            dessert_id = dessert["dessert_id"]
            if not isinstance(dessert_id, str) or not dessert_id.strip():
                raise ValueError("missing dessert_id")
            if check["dessert_id"] != dessert_id:
                raise ValueError("check result belongs to a different dessert")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            logger.warning("Ranking skipped a malformed candidate: %s", exc)
            continue
        if dessert_id in seen:
            logger.warning("Ranking skipped duplicate dessert_id %s", dessert_id)
            continue
        seen.add(dessert_id)
        valid.append(candidate)
    return valid


def _essential_failures(request, candidate):
    """Reasons a candidate cannot be ranked at all. An empty list means eligible."""
    dessert = candidate["dessert"]
    check = candidate["check"]
    failures = []

    if check["status"] not in RANKABLE_STATUSES:
        failures.append("details still need research")

    if not _text(dessert.get("name")) or not _text(dessert.get("business")):
        failures.append("name or business missing")

    address = _text(dessert.get("address"))
    if address is None:
        print("Address not verified; location identified by research but unconfirmed.")

    elif config.RANK_LOCATION_TOWN.lower() not in address.lower():
        failures.append("not in Cookeville")
    wanted_type = _canonical_type(request.get("dessert_type"))
    if wanted_type:
        actual_type = _canonical_type(dessert.get("dessert_type"))
        allowed = (wanted_type,) + DESSERT_FALLBACKS.get(wanted_type, ())
        if not actual_type:
            failures.append("dessert type not confirmed")
        elif actual_type not in allowed:
            failures.append(f"dessert type is {actual_type}, not {wanted_type} or an approved fallback")

    # A requested flavor is mandatory: missing flavor evidence is not a match.
    wanted_flavor = _requested_flavor(request)
    if wanted_flavor and _flavor_match_tier(dessert, wanted_flavor) == 0:
        failures.append("requested flavor not confirmed")
    # Require an actual confirmed price or a valid estimated price.
    price = _confirmed_price(candidate)
    max_price = _number(request.get("max_price"))
    if max_price is not None and price is not None and price > max_price:
        failures.append("over budget")

    distance = _number(dessert.get("distance_miles"))
    max_distance = _number(request.get("max_distance_miles"))
    if max_distance is not None and distance is not None and distance > max_distance:
        failures.append("too far")

    return failures


# Scoring


def _score(request, candidate, record, hours_record=None, now=None):
    dessert = candidate["dessert"]
    check = candidate["check"]

    google = _platform(record, "google")
    yelp = _platform(record, "yelp")

    counts = [
        p["review_count"]
        for p in (google, yelp)
        if p["review_count"] is not None
    ]
    total_reviews = sum(counts) if counts else None

    combined, _ = combined_rating([
        (p["rating"], p["review_count"])
        for p in (google, yelp)
    ])

    # Rating: 7.5%
    rating = (
        rating_to_score(combined)
        if combined is not None
        else config.RANK_NEUTRAL_SCORE
    )

    # Hours: 7.5%
    hours = hours_text(hours_record) or _text(dessert.get("hours"))
    open_now = is_open_at(hours_record, now) if now is not None else None

    hours_score = (
        100.0 if open_now is True
        else 0.0 if open_now is False
        else config.RANK_NEUTRAL_SCORE
    )

    # Flavor: 25%
    flavor_availability, flavor = _flavor(request, dessert)
    flavor_score = flavor[0]

    # Dessert type: 25%
    wanted_type = _canonical_type(request.get("dessert_type"))
    actual_type = _canonical_type(dessert.get("dessert_type"))
    is_related = bool(wanted_type and actual_type != wanted_type)
    dessert_score = 70.0 if is_related else 100.0

    # Location: 15%
    address = (_text(dessert.get("address")) or "").lower()
    requested_location = (
        request.get("location") or "Cookeville"
    ).split(",")[0].strip().lower()

    location_score = (
        100.0 if requested_location in address
        else 0.0
    )

    # Price: 20%. Relative price points are assigned after all candidates are scored.
    price = _ranking_price(candidate)
    max_price = _number(request.get("max_price"))

    if max_price is None or max_price <= 0:
        price_score = config.RANK_NEUTRAL_SCORE
    elif price is None:
        price_score = config.RANK_NEUTRAL_SCORE
    else:
        price_score = config.RANK_NEUTRAL_SCORE  # placeholder until relative comparison

    values = {
        "rating": rating,
        "hours": hours_score,
        "flavor": flavor_score,
        "dessert": dessert_score,
        "location": location_score,
        "price": price_score,
    }

    components = {}

    for name, value in values.items():
        components[name] = {
            "score": round(value, 1),
            "weight": RANK_WEIGHTS[name],
            "state": "scored",
        }

    if combined is None:
        components["rating"]["state"] = "neutral"

    if open_now is None:
        components["hours"]["state"] = "neutral"

    if flavor_availability == "not_requested":
        components["flavor"]["state"] = "not_requested"
    if not wanted_type:
        components["dessert"]["state"] = "not_requested"

    # The relative-price pass updates this component and the final score.
    components["price"]["state"] = "neutral"

    # Weighted score out of 100
    raw_score = _weighted_average(components)

    facts = {
        "dessert_id": dessert["dessert_id"],
        "dessert_name": dessert["name"],
        "business": dessert["business"],
        "address": _text(dessert.get("address")),
        "price": price,
        "distance_miles": _number(dessert.get("distance_miles")),
        "verification_status": check["status"],
        "google": google,
        "yelp": yelp,
        "combined_rating": round(combined, 2) if combined is not None else None,
        "total_reviews": total_reviews,
        "requested_flavor": request.get("flavor"),
        "requested_type": request.get("dessert_type"),
        "match_type": "related" if is_related else "exact" if wanted_type else "not_requested",
        "flavor_availability": flavor_availability,
        "hours": hours,
        "open_now": open_now,
        "components": components,
        "score": round(raw_score, 1),
        "missing": _missing(
            google, yelp, total_reviews, flavor_availability,
            hours, check["status"], price
        ),
    }

    return raw_score, facts
def _apply_relative_price_scores(eligible):
    """Give the lowest priced eligible dessert all 20 price points.

    Prices are confirmed menu prices or midpoints of valid predicted ranges.
    Missing prices get a neutral score. Recompute scores before sorting.
    """
    available = [
        price for _, candidate, _, _ in eligible
        if (price := _ranking_price(candidate)) is not None
    ]
    lowest = min(available) if available else None
    updated = []

    for _, candidate, record, facts in eligible:
        price = _ranking_price(candidate)
        if price is None or lowest is None:
            value, state = config.RANK_NEUTRAL_SCORE, "neutral"
        elif lowest == 0:
            value, state = (100.0 if price == 0 else 0.0), "scored"
        else:
            value, state = 100.0 * lowest / price, "scored"

        facts["components"]["price"] = {
            "score": round(value, 1),
            "weight": RANK_WEIGHTS["price"],
            "state": state,
        }
        score = _weighted_average(facts["components"])
        facts["score"] = round(score, 1)
        updated.append((score, candidate, record, facts))

    return updated


def _weighted_average(components):
    total_weight = 0.0
    total = 0.0
    for component in components.values():
        if component["state"] == "not_requested" or component["weight"] <= 0:
            continue
        total_weight += component["weight"]
        total += component["score"] * component["weight"]
    return total / total_weight if total_weight > 0 else 0.0


def _requested_flavor(request):
    """Normalize the flavor filter; 'Any' means no flavor constraint."""
    flavor = _text(request.get("flavor"))
    if not flavor or flavor.casefold() in ("any", "all", "none"):
        return None
    return flavor.casefold()


def _flavor_match_tier(dessert, requested):
    """3 = named flavor, 2 = plain unspecified, 1 = combination, 0 = no match.

    A generic plain ice cream is a fallback, not proof of vanilla flavor.
    """
    name = (_text(dessert.get("name")) or "").casefold()
    flavors = [f.strip().casefold() for f in (dessert.get("flavors") or [])
               if isinstance(f, str) and f.strip()]
    pattern = re.compile(r"(?<!\w)" + re.escape(requested) + r"(?!\w)", re.IGNORECASE)
    if name in (
        "chocolate milk",
        "df coconut cookie dough",
        "cookie dough",
    ):
        print("\n========== FLAVOR DEBUG ==========")
        print("Dessert:", dessert.get("name"))
        print("Dessert type:", dessert.get("dessert_type"))
        print("Requested flavor:", requested)
        print("Extracted flavors:", flavors)
        print("Name contains requested flavor:", bool(pattern.search(name)))
        print("Flavor list contains requested flavor:",
            any(pattern.search(f) for f in flavors))
        print("==================================")
    if pattern.search(name):
        # Vanilla Bean / Plain Vanilla count as named matches; vanilla mixed
        # with other named flavors is a secondary match.
        rest = _strip_generic(pattern.sub("", name))
        if not rest:
            return 3
        # Descriptive terms such as "chip" or a second flavor stay combinations.
        return 1
    if any(pattern.search(f) for f in flavors):
        # A listing of vanilla as the base of another named flavor is not an exact match.
        return 1
    # Only a genuinely unspecified plain ice cream can qualify as fallback.
    # A named non-vanilla flavor must never be treated as plain.
    if requested and name in ("plain ice cream", "plain soft serve", "ice cream",
                              "soft serve", "plain gelato", "gelato") and not flavors:
        return 2
    return 0


def _has_requested_flavor(dessert, requested):
    return _flavor_match_tier(dessert, requested) > 0


def _flavor(request, dessert):
    requested = _requested_flavor(request)
    if not requested:
        return "not_requested", (config.RANK_NEUTRAL_SCORE, "not_requested")
    tier = _flavor_match_tier(dessert, requested)
    if tier == 3:
        return "exact", (100.0, "scored")
    if tier == 2:
        return "plain_unspecified", (80.0, "scored")
    if tier == 1:
        return "combination", (60.0, "scored")
    return "not_matching", (0.0, "scored")

def _sort_key(entry):
    raw_score, candidate, _, facts = entry

    review_count = facts.get("total_reviews") or 0

    requested = _requested_flavor(
        {"flavor": facts.get("requested_flavor")}
    )

    if "flavor_priority" in facts:
        flavor_priority = facts["flavor_priority"]
    else:
        flavor_tier = (
            _flavor_match_tier(candidate["dessert"], requested)
            if requested else 0
        )
        flavor_priority = -flavor_tier

    open_now = facts.get("open_now")

    if open_now is True:
        hours_priority = 0
    elif open_now is None:
        hours_priority = 1
    else:
        hours_priority = 2

    # An exact dessert type always precedes an approved related type.
    type_priority = 1 if facts.get("match_type") == "related" else 0
    return (
        type_priority,
        flavor_priority,
        hours_priority,
        -raw_score,
        -review_count,
        candidate["dessert"]["dessert_id"],
    )

def _missing(google, yelp, total_reviews, flavor_availability, hours, status, price):
    missing = []
    if google["rating"] is None:
        missing.append("Google rating not found")
    if yelp["rating"] is None:
        missing.append("Yelp rating not found")
    if total_reviews is None:
        missing.append("review count not available")
    if flavor_availability == "not_listed":
        missing.append("flavor not listed")
    if hours is None:
        missing.append("business hours not available")
    if status != "verified":
        missing.append("some details not confirmed")
    if price is None:
        missing.append("price not confirmed")
    return missing


# Explanations (Ollama) and deterministic fallbacks

def _explain(request, selected):
    """Return {dessert_id: (explanation, concerns, source)} for every selected result."""
    fallback = {
        facts["dessert_id"]: (_fallback_explanation(facts), list(facts["missing"]), "rules")
        for _, _, _, facts in selected
    }
    if config.RANK_MODE != "ollama" or not config.OLLAMA_MODEL or not selected:
        return fallback

    try:
        payload_items = _explanation_payload(selected)
        # Every selected result's rank is a fact Python gave the model, so "#1" or "#2" is allowed.
        rank_numbers = {float(position) for position in range(1, len(payload_items) + 1)}
        allowed = {
            item["dessert_id"]: _allowed_numbers(request, item) | rank_numbers
            for item in payload_items
        }
        prompt = _build_prompt(request, payload_items)
        response = ask_json(
            prompt,
            model=config.OLLAMA_MODEL,
            host=config.OLLAMA_HOST,
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )
        missing_by_id = {f["dessert_id"]: f["missing"] for _, _, _, f in selected}
        facts_by_id = {item["dessert_id"]: json.dumps(item).lower() for item in payload_items}
        request_terms = [request[key] for key in ("location",) if request.get(key)]
        accepted = _validated_explanations(response, allowed, missing_by_id,
                                           facts_by_id, request_terms)
    except Exception as exc:
        logger.warning("Ollama explanations failed; using rules explanations: %s", exc)
        return fallback

    if not accepted:
        logger.warning(
            "Ollama reply had no usable explanations; using rules explanations. Raw reply: %s",
            repr(response)[:600],
        )

    result = {}
    for dessert_id, default in fallback.items():
        if dessert_id in accepted:
            text, concerns = accepted[dessert_id]
            result[dessert_id] = (text, concerns or default[1], "ollama")
        else:
            result[dessert_id] = default
    return result


def _explanation_payload(selected):
    items = []
    for position, (raw_score, candidate, _, facts) in enumerate(selected, start=1):
        item = {
            "dessert_id": facts["dessert_id"],
            "rank": position,
            "dessert_name": facts["dessert_name"],
            "business": facts["business"],
            "address": facts["address"],
            "score": facts["score"],
            "score_scale": "0-100",
            "components": facts["components"],
            "google": facts["google"],
            "yelp": facts["yelp"],
            "combined_rating": facts["combined_rating"],
            "total_reviews": facts["total_reviews"],
            "flavor_availability": facts["flavor_availability"],
            "business_hours": facts["hours"],
            "open_now": facts["open_now"],
            "verification_status": facts["verification_status"],
            "price": facts["price"],
            "distance_miles": facts["distance_miles"],
            "missing": facts["missing"],
            "compared_with_previous": None,
        }
        if position > 1:
            _, _, _, previous = selected[position - 2]
            item["compared_with_previous"] = _comparison(position - 1, previous, facts)
        items.append(item)
    return items


def _comparison(previous_rank, previous, current):
    """Describe why the current result ranks below the previous one, from Python's numbers."""
    best_label, best_gap = None, 0.0
    for name, component in current["components"].items():
        other = previous["components"][name]
        if component["state"] == "not_requested" or other["state"] == "not_requested":
            continue
        gap = component["weight"] * (other["score"] - component["score"])
        if gap > best_gap:
            best_label, best_gap = name, gap
    text = f"ranked below #{previous_rank}: score {current['score']} vs {previous['score']}"
    if best_label:
        text += (f"; largest difference is {best_label.replace('_', ' ')} "
                 f"({current['components'][best_label]['score']} vs "
                 f"{previous['components'][best_label]['score']})")
    return text


def _build_prompt(request, payload_items):
    return (
        "You write short explanations for a dessert ranking that Python has already decided.\n"
        "Rules:\n"
        "- Use only the facts in the JSON below. Do not add any rating, review count, price, "
        "hours, availability, or other number that is not in the facts.\n"
        "- Do not question, change, or reorder the ranking. Do not add or remove results.\n"
        "- For each result, write at most two plain sentences on why it suits the request. "
        "If compared_with_previous is set, briefly say why it ranks below the previous result.\n"
        "- If a value is in missing, say it is a limitation. Never say a missing value is available.\n"
        "- To mention another result, use its dessert_name and business, not its rank number.\n"
        "- concerns: up to three short limitations for that result.\n"
        "Return only JSON in this form, with one entry per result:\n"
        'Use exactly this shape. "explanation" is one string, not a list. Use the dessert_id values given.\n'
        '{"explanations": [{"dessert_id": "...", "explanation": "...", "concerns": ["..."]}]}\n\n'
        f"Request: {json.dumps(request)}\n"
        f"Results: {json.dumps(payload_items)}"
    )


def _allowed_numbers(request, item):
    numbers = {100.0}
    for source in (item, request):
        for token in NUMBER_PATTERN.findall(json.dumps(source)):
            numbers.add(float(token))
    return numbers


MISSING_TOPICS = (
    ("hours", ("hour", "open")),
    ("Google", ("google",)),
    ("Yelp", ("yelp",)),
    ("review count", ("review",)),
    ("price", ("price", "$", "cost")),
)
NEGATIONS = ("not", "no ", "n't", "unavailable", "missing", "unknown", "unconfirmed", "without", "none")


def _false_availability_claims(text, missing):
    """Missing items the text claims are available. Empty list means no such claim.

    A sentence that mentions a missing topic must also contain a negation. For example,
    "business hours are not available" passes; "a business with available hours" does not.
    """
    claims = []
    sentences = re.split(r"[.;]", text.lower())
    for item in missing:
        for topic, keywords in MISSING_TOPICS:
            if topic.lower() not in item.lower():
                continue
            for sentence in sentences:
                mentions = any(k in sentence for k in keywords)
                negated = any(n in sentence for n in NEGATIONS)
                if mentions and not negated:
                    claims.append(item)
                    break
    return claims


def _numbers_allowed(text, allowed):
    for token in NUMBER_PATTERN.findall(text):
        value = float(token)
        if not any(abs(value - a) < NUMBER_TOLERANCE for a in allowed):
            return False
    return True


def _grounding_problem(text, facts_text, request_terms):
    """Why a model sentence cannot be used, or None if it passes.

    facts_text is the lowercase JSON of everything Python gave the model for this dessert.
    """
    if FIELD_NAME.search(text):
        return "uses an internal field name"
    if NEGATIVE_VERDICT.search(text):
        return "says a ranked dessert does not suit the request"
    for term in request_terms:
        term_lower = term.lower()
        if term_lower in text.lower() and term_lower not in facts_text:
            return f"mentions '{term}' from the request, which is not a fact about this dessert"
    return None


def _validated_explanations(response, allowed, missing_by_id, facts_by_id=None, request_terms=()):
    """Return {dessert_id: (explanation, concerns)} for entries that pass every check."""
    accepted = {}
    for item in _explanation_items(response):
        dessert_id = item.get("dessert_id")
        if dessert_id not in allowed:
            logger.warning("Ollama reply: unknown dessert_id %r ignored", dessert_id)
            continue
        if dessert_id in accepted:
            continue
        text = _as_text(item.get("explanation"))
        if not isinstance(text, str) or not text.strip():
            logger.warning("Ollama reply: no explanation text for %s", dessert_id)
            continue
        if len(text) > MAX_EXPLANATION_CHARS:
            logger.warning("Ollama reply: explanation for %s is too long (%d chars)", dessert_id, len(text))
            continue
        problem = _grounding_problem(text, (facts_by_id or {}).get(dessert_id, ""), request_terms)
        if problem:
            logger.warning("Ollama reply: explanation for %s rejected: %s; %r",
                           dessert_id, problem, text[:160])
            continue
        claims = _false_availability_claims(text, missing_by_id.get(dessert_id, []))
        if claims:
            logger.warning("Ollama reply: explanation for %s says %s is available; it is missing",
                           dessert_id, claims)
            continue
        if not _numbers_allowed(text, allowed[dessert_id]):
            unsupported = [t for t in NUMBER_PATTERN.findall(text)
                           if not _numbers_allowed(t, allowed[dessert_id])]
            logger.warning("Ollama reply: explanation for %s has unsupported number(s) %s: %r",
                           dessert_id, unsupported, text[:160])
            continue

        raw_concerns = item.get("concerns") if isinstance(item.get("concerns"), list) else []
        concerns = []
        for concern in raw_concerns:
            if (isinstance(concern, str) and concern.strip()
                    and _numbers_allowed(concern, allowed[dessert_id])
                    and not FIELD_NAME.search(concern)):
                concerns.append(concern.strip())
        accepted[dessert_id] = (text.strip(), concerns[:MAX_CONCERNS])
    return accepted


def _explanation_items(response):
    """Yield explanation entries from the shapes a model may return.

    1. {"explanations": [{"dessert_id", "explanation", "concerns"}, ...]}   (requested shape)
    2. {dessert_id: {"explanations": [...strings...], "concerns": [...]}}  (seen from llama3.2)
    3. {dessert_id: "explanation text", ...}                                (seen from llama3.2)
    """
    if not isinstance(response, dict):
        return []
    items = response.get("explanations")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    entries = []
    for key, value in response.items():
        if isinstance(value, str):
            # A bare string: the explanation itself, with no concerns.
            entries.append({"dessert_id": key, "explanation": value, "concerns": []})
        elif isinstance(value, dict):
            entries.append({
                "dessert_id": key,
                "explanation": value.get("explanation", value.get("explanations")),
                "concerns": value.get("concerns", []),
            })
    return entries


def _as_text(value):
    """A single string. A list of sentence strings is joined in order."""
    if isinstance(value, list):
        parts = [part.strip() for part in value if isinstance(part, str) and part.strip()]
        return " ".join(parts) if parts else None
    return value if isinstance(value, str) else None


def _fallback_explanation(facts):
    text = _reason(facts)
    if facts["missing"]:
        text += ". Limitations: " + "; ".join(facts["missing"])
    return text + "."


def _reason(facts):
    parts = []
    requested = facts["requested_flavor"]
    if facts["flavor_availability"] in ("exact", "combination"):
        parts.append(f"lists {requested}")
    elif facts["flavor_availability"] == "plain_unspecified":
        parts.append("plain flavor unspecified")
    elif facts["flavor_availability"] == "not_matching":
        parts.append(f"does not list {requested}")
    elif facts["flavor_availability"] == "not_listed":
        parts.append("flavor not listed")

    if facts["combined_rating"] is not None:
        parts.append(f"combined rating {facts['combined_rating']:.1f} from {facts['total_reviews']} reviews")
    else:
        parts.append("no platform rating available")

    if facts["verification_status"] == "verified":
        parts.append("details verified against the source")
    else:
        parts.append("some details not confirmed")

    parts.append(f"score {facts['score']:.1f}/100")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:]


# Helpers

def _select_top(eligible, limit, per_business, fill_repeats=False):
    """Prefer different shops first, then fill slots with highest-ranked repeats.

    The incoming eligible list is already sorted by ranking priorities.
    """
    if not per_business:
        return eligible[:limit]
    chosen, skipped, counts = [], [], {}
    for entry in eligible:
        dessert = entry[1]["dessert"]
        shop = " ".join((dessert.get("business") or "").casefold().split())
        if counts.get(shop, 0) < per_business:
            counts[shop] = counts.get(shop, 0) + 1
            chosen.append(entry)
        else:
            skipped.append(entry)
        if len(chosen) >= limit:
            return chosen
    return (chosen + skipped)[:limit] if fill_repeats else chosen[:limit]


def _index_hours(records):
    index = {}
    for record in records or []:
        if isinstance(record, dict) and record.get("business_key") is not None:
            index[record["business_key"]] = record
    return index


def _index_records(records):
    index = {}
    for record in records or []:
        if isinstance(record, dict) and record.get("business_key") is not None:
            index[record["business_key"]] = record
    return index


def _platform(record, prefix):
    if not record:
        return {"rating": None, "review_count": None}
    return {
        "rating": _number(record.get(f"{prefix}_rating")),
        "review_count": _count(record.get(f"{prefix}_review_count")),
    }


def _recommendation_summary(record):
    if record is None:
        return None
    return {
        "score": record.get("recommendation_score"),
        "confidence": record.get("confidence"),
        "evidence_coverage": record.get("evidence_coverage"),
        "review_count_used": record.get("review_count_used"),
        "analysis_status": record.get("analysis_status"),
    }


def _ranking_price(candidate):
    """Use verified price first; otherwise use midpoint of estimated range.

    Estimated range keys must be present on the dessert record. A predicted
    single price without range bounds is not treated as verified.
    """
    confirmed = _confirmed_price(candidate)
    if confirmed is not None:
        return confirmed

    dessert = candidate["dessert"]
    lower = _number(dessert.get("price_lower"))
    upper = _number(dessert.get("price_upper"))
    if lower is not None and upper is not None and 0 <= lower <= upper:
        return (lower + upper) / 2.0
    return None


def _confirmed_price(candidate):
    """The price, but only when the checking agent confirmed it."""
    price = _number(candidate["dessert"].get("price"))
    if price is None or price < 0:
        return None
    if "price" not in candidate["check"].get("verified_fields", []):
        return None
    return price


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return float(value)


def _count(value):
    number = _number(value)
    if number is None or number < 0:
        return None
    return int(number)


def _text(value):
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
