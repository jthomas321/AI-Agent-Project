"""Shared data formats for Sweetery.

Owned by the whole team. Changing a field name, adding a required field, or
changing a status value needs team agreement and updates to tests/.

Rules:
- Use None for unknown values. Never guess a price, address, or flavor.
- Agents must preserve dessert_id and evidence when passing records along.
"""

from typing import Any, Dict, List, Optional, TypedDict

VERIFICATION_STATUSES = ("unverified", "verified", "needs_research", "unknown")
CHECK_STATUSES = ("verified", "needs_research", "unknown")
PIPELINE_STATUSES = ("ok", "no_match", "error")

REQUEST_KEYS = ("dessert_type", "flavor", "max_price", "location", "max_distance_miles")
DESSERT_KEYS = (
    "dessert_id", "name", "business", "price", "dessert_type", "flavors", "address",
    "distance_miles", "menu_url", "evidence", "verification_status",
)
# Optional: a dessert may have no rating. Ranking treats it as unrated.
OPTIONAL_DESSERT_KEYS = ("rating",)
EVIDENCE_KEYS = ("claim", "source_url", "source_text", "checked_at")
CHECK_KEYS = ("dessert_id", "status", "verified_fields", "flagged_fields", "notes")


class Evidence(TypedDict):
    claim: str
    source_url: Optional[str]
    source_text: Optional[str]
    checked_at: Optional[str]


class Request(TypedDict):
    dessert_type: Optional[str]
    flavor: Optional[str]
    max_price: Optional[float]
    location: Optional[str]
    max_distance_miles: Optional[float]


class Dessert(TypedDict):
    dessert_id: str
    name: str
    business: str
    price: Optional[float]
    dessert_type: Optional[str]
    flavors: List[str]
    address: Optional[str]
    distance_miles: Optional[float]
    menu_url: Optional[str]
    evidence: List[Evidence]
    verification_status: str
    rating: Optional[float]


class CheckResult(TypedDict):
    dessert_id: str
    status: str
    verified_fields: List[str]
    flagged_fields: List[str]
    notes: str


class CheckedCandidate(TypedDict):
    dessert: Dessert
    check: CheckResult


class RankedResult(TypedDict):
    rank: int
    dessert: Dessert
    check: CheckResult
    reason: str
    recommendation: Optional[Dict[str, Any]]  # review score summary, or None when unscored


class PipelineResult(TypedDict):
    status: str
    message: str
    results: List[RankedResult]
    log: List[str]


def normalize_request(raw: Dict[str, Any]) -> Request:
    """Turn raw UI or user input into a clean Request. Missing values become None."""
    unknown = set(raw) - set(REQUEST_KEYS)
    if unknown:
        raise ValueError(f"unknown request field(s): {sorted(unknown)}")

    def text(key: str, lower: bool = False) -> Optional[str]:
        value = raw.get(key)
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        return value.lower() if lower else value

    def number(key: str) -> Optional[float]:
        value = raw.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if amount < 0:
            raise ValueError(f"{key} cannot be negative")
        return round(amount, 2)

    return {
        "dessert_type": text("dessert_type", lower=True),
        "flavor": text("flavor", lower=True),
        "max_price": number("max_price"),
        "location": text("location"),
        "max_distance_miles": number("max_distance_miles"),
    }


def validate_dessert(record: Dict[str, Any]) -> Dict[str, Any]:
    """Raise ValueError if a dessert record does not match the shared format."""
    label = record.get("dessert_id", "?")
    missing = [k for k in DESSERT_KEYS if k not in record]
    if missing:
        raise ValueError(f"dessert {label} is missing fields: {missing}")
    if record["verification_status"] not in VERIFICATION_STATUSES:
        raise ValueError(f"dessert {label} has invalid verification_status")
    if not isinstance(record["flavors"], list):
        raise ValueError(f"dessert {label} flavors must be a list")
    if record["price"] is not None and not isinstance(record["price"], (int, float)):
        raise ValueError(f"dessert {label} price must be a number or None")
    rating = record.get("rating")
    if rating is not None and (
        isinstance(rating, bool) or not isinstance(rating, (int, float))
    ):
        raise ValueError(f"dessert {label} rating must be a number or None")
    for ev in record["evidence"]:
        missing_ev = [k for k in EVIDENCE_KEYS if k not in ev]
        if missing_ev:
            raise ValueError(f"dessert {label} evidence is missing fields: {missing_ev}")
    return record


def validate_check_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Raise ValueError if a check result does not match the shared format."""
    missing = [k for k in CHECK_KEYS if k not in result]
    if missing:
        raise ValueError(f"check result is missing fields: {missing}")
    if result["status"] not in CHECK_STATUSES:
        raise ValueError(f"invalid check status: {result['status']}")
    return result