"""Pricing step. Runs after screening and before checking.

1. Splits multi-dessert lines into one record per dessert.
2. Estimates a price for each record that has no valid price.

It does not set dessert_type; checking does. It only chooses which price-model
category to predict with, from the same resolver checking uses.
Estimates are never verified menu prices.
"""

import copy
import logging
import math
import re
from typing import Any, Dict, List, Optional

from agents.price_prediction_agent import predict_price
from tools.item_types import business_type, head_type, resolve_item_type, split_parts

logger = logging.getLogger(__name__)

# Lines that describe a price or a menu section, not an orderable item. Left unpriced.
NOT_AN_ITEM = re.compile(r"\b(average|per person|each)\b", re.IGNORECASE)

PRICE_FIELDS = (
    "price", "price_status", "price_lower", "price_upper",
    "price_verified", "price_prediction_source",
)
def _clear_price(record: Dict[str, Any]) -> Dict[str, Any]:
    """Set every price field to None. Keep the keys so validate_dessert still passes."""
    for field in PRICE_FIELDS:
        record[field] = None
    return record

def _positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _has_valid_price(record: Dict[str, Any]) -> bool:
    return _positive(record.get("price")) and record.get("price_status") != "estimated"


def _split_record(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One record per dessert. Split children do not keep a shared price."""
    parts = split_parts(record.get("name") or "")
    if len(parts) == 1:
        return [record]
    children = []
    for index, part in enumerate(parts, start=1):
        child = copy.deepcopy(record)
        child["name"] = part
        child["dessert_id"] = f"{record['dessert_id']}#{index}"
        _clear_price(child)
        children.append(child)
    return children

'''
def _candidate_types(record: Dict[str, Any]) -> List[str]:
    """Categories to try, in order, without repeats."""
    name = record.get("name") or ""
    business = record.get("business")
    options = [
        resolve_item_type(name, business)[0],
        head_type(name),
        business_type(business),
    ]
    ordered: List[str] = []
    for option in options:
        if option and option not in ordered:
            ordered.append(option)
    return ordered
'''
def _candidate_types(record: Dict[str, Any]) -> List[str]:
    """Categories to try, in order, without repeats."""
    name = record.get("name") or ""
    business = record.get("business")

    options = [
        record.get("dessert_type"),
        resolve_item_type(name, business)[0],
        head_type(name),
        business_type(business),
    ]

    ordered: List[str] = []

    for option in options:
        option = str(option or "").strip().lower()

        if option == "frozen yogurt":
            option = "ice cream"

        if option in ("", "unclassified", "unknown", "other", "none", "any"):
            continue

        if option not in ordered:
            ordered.append(option)

    return ordered
def _predict(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = record.get("name") or ""
    if not name or NOT_AN_ITEM.search(name):
        return None
    for price_type in _candidate_types(record):
        try:
            result = predict_price(name, price_type)
        except Exception:
            logger.exception("Price prediction failed for %s (%s)", name, price_type)
            continue
        point = result.get("price")
        lower = result.get("price_lower")
        upper = result.get("price_upper")
        if not all(_positive(v) for v in (point, lower, upper)) or lower > upper:
            continue
        return {
            "price": float(point),
            "price_lower": float(lower),
            "price_upper": float(upper),
            "price_status": "estimated",
            "price_verified": False,
            "price_prediction_source": result.get("source", "price model"),
        }
    return None


def estimate_missing_prices(records: List[Dict[str, Any]], log: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    estimated = 0
    unpriced: List[str] = []

    for record in records:
        for child in _split_record(record):
            if not _has_valid_price(child):
                estimate = _predict(child)
                if estimate:
                    child.update(estimate)
                    estimated += 1
                else:
                    unpriced.append(str(child.get("name")))
            output.append(child)

    if log is not None:
        log.append(
            f"Price step: {len(output)} record(s); estimated {estimated}; "
            f"{len(unpriced)} without a price"
        )
        for name in unpriced[:20]:
            log.append(f"  unpriced: {name[:80]}")
    return output