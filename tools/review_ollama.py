"""Ollama review analysis.

The model reads review text and returns judgments. It does not compute the
final score (agents/recommendation_agent.py and tools/review_scoring.py do).

analyze_reviews(business_name, dessert_names, reviews) returns a dict with
"status" set to one of:
- "ok": the output parsed and validated
- "no_reviews": nothing to analyze (no call made)
- "unavailable": Ollama could not be reached or timed out
- "malformed": the model's reply was not usable JSON

Rules enforced in code, not only in the prompt:
- Only review IDs that were sent to the model count as evidence.
- Scores outside 0-100 are discarded (set to None), not clipped.
- If the model cites no valid review, its scores are discarded too.
"""

import hashlib
import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

import config
from tools import review_cache

ANALYSIS_NAMESPACE = "ollama_analysis"
MAX_LIST_ITEMS = 5
MAX_ITEM_CHARS = 120
MAX_NOTE_CHARS = 300

SYSTEM_PROMPT = (
    "You analyze customer reviews of one business for a dessert recommendation system. "
    "Use only the reviews provided. Never invent reviews, ratings, quotes, or experiences. "
    "If the reviews do not support a judgment, use null or false. "
    "Reply with one JSON object and nothing else."
)

INSTRUCTIONS = """Return a JSON object with exactly these keys:
- "is_dessert_related": true only if at least one review discusses desserts, sweets, ice cream, or baked goods.
- "sentiment_score": integer 0-100 for overall customer sentiment toward the business, or null if the reviews give no basis.
- "dessert_quality_score": integer 0-100 for dessert-specific quality only (taste, texture, freshness of desserts), or null if no review discusses desserts.
- "evidence_sufficient": true only if the reviews are enough for a reliable judgment; otherwise false.
- "review_ids_used": list of the review IDs (for example "R1") you relied on. Use only IDs from the list below.
- "positive_themes": up to 5 short phrases about recurring positives.
- "negative_themes": up to 5 short phrases about recurring negatives.
- "dessert_complaints": up to 5 short phrases about dessert-related complaints.
- "taste_flavor_notes": one short sentence on taste or flavor feedback, or null.
- "texture_freshness_notes": one short sentence on texture or freshness feedback, or null."""

ChatFn = Callable[[str], str]


class OllamaUnavailable(Exception):
    pass


def build_prompt(business_name: str, dessert_names: List[str], reviews: List[Dict[str, Any]]) -> str:
    lines = [
        f"Business: {business_name}",
        f"Desserts on record for this business: {', '.join(dessert_names) if dessert_names else 'unknown'}",
        "",
        "Reviews:",
    ]
    for review in reviews:
        text = " ".join((review.get("text") or "").split())[: config.REVIEW_TEXT_CHARS]
        rating = review.get("rating")
        rating_text = f"{rating}/5" if rating is not None else "no rating"
        lines.append(f"[{review['id']}] ({review.get('platform', 'unknown')}, {rating_text}) {text}")
    lines += ["", INSTRUCTIONS]
    return "\n".join(lines)


def _chat(prompt: str, system: Optional[str] = None) -> str:
    """Send one request to the local Ollama server and return the reply text."""
    body = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system or SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        f"{config.OLLAMA_HOST.rstrip('/')}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.OLLAMA_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaUnavailable(type(exc).__name__) from None
    except ValueError:
        raise OllamaUnavailable("invalid response from Ollama") from None
    try:
        return payload["message"]["content"]
    except (KeyError, TypeError):
        raise OllamaUnavailable("unexpected response shape from Ollama") from None


def _parse_object(text: str) -> Optional[Dict[str, Any]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        value = json.loads(cleaned)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _score(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not 0 <= value <= 100:
        return None
    return int(round(value))


def _text_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip()[:MAX_ITEM_CHARS])
    return items[:MAX_LIST_ITEMS]


def _note(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()[:MAX_NOTE_CHARS]
    return None


def validate_analysis(obj: Dict[str, Any], valid_ids: List[str]) -> Dict[str, Any]:
    cited = [i for i in obj.get("review_ids_used") or [] if isinstance(i, str) and i in valid_ids]
    cited = list(dict.fromkeys(cited))  # keep order, drop duplicates
    evidence_ok = bool(obj.get("evidence_sufficient") is True) and bool(cited)

    sentiment = _score(obj.get("sentiment_score")) if cited else None
    dessert = _score(obj.get("dessert_quality_score")) if cited else None

    return {
        "status": "ok",
        "is_dessert_related": bool(obj.get("is_dessert_related") is True) and bool(cited),
        "sentiment_score": sentiment,
        "dessert_quality_score": dessert,
        "evidence_sufficient": evidence_ok,
        "review_ids_used": cited,
        "positive_themes": _text_list(obj.get("positive_themes")),
        "negative_themes": _text_list(obj.get("negative_themes")),
        "dessert_complaints": _text_list(obj.get("dessert_complaints")),
        "taste_flavor_notes": _note(obj.get("taste_flavor_notes")),
        "texture_freshness_notes": _note(obj.get("texture_freshness_notes")),
        "model": config.OLLAMA_MODEL,
    }


def analyze_reviews(
    business_name: str,
    dessert_names: List[str],
    reviews: List[Dict[str, Any]],
    chat: Optional[ChatFn] = None,
) -> Dict[str, Any]:
    """reviews: dicts with 'id', 'text', 'rating', 'platform'. Only the first
    config.REVIEW_MAX_TEXTS reviews with text are sent to the model."""
    usable = [r for r in reviews if (r.get("text") or "").strip()][: config.REVIEW_MAX_TEXTS]
    if not usable:
        return {"status": "no_reviews"}

    prompt = build_prompt(business_name, dessert_names, usable)
    cache_key = hashlib.sha256(f"{config.OLLAMA_MODEL}\n{prompt}".encode("utf-8")).hexdigest()
    # The prompt contains review text. If any of it is from Google, keep the result in
    # memory only, not on disk.
    on_disk = not any(r.get("platform") == "google" for r in usable)
    get = review_cache.disk_get if on_disk else review_cache.memory_get
    put = review_cache.disk_put if on_disk else review_cache.memory_put
    hit, cached = get(ANALYSIS_NAMESPACE, cache_key)
    if hit and cached:
        return cached

    try:
        reply = (chat or _chat)(prompt)
    except OllamaUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc)}

    obj = _parse_object(reply)
    if obj is None:
        return {"status": "malformed", "reason": "reply was not a JSON object"}

    result = validate_analysis(obj, [r["id"] for r in usable])
    put(ANALYSIS_NAMESPACE, cache_key, result)
    return result
