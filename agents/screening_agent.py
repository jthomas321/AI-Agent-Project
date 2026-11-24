"""Screening agent. Removes junk only.

Junk is non-food text, site navigation, business hours, addresses and phone numbers,
and non-sweet drinks. It trims trailing site text and "starts at" lead-ins from real
items, and it keeps a note that the price was a starting price.
It does not check type, flavor, price, distance, or location. Later steps do that.

screen(records, log=None) -> list of records, with cleaned names, in input order.
"""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

CONTENDER = "contender"
NEEDS_VERIFICATION = "needs_verification"
REJECT = "reject"

CLASSIFICATIONS = (CONTENDER, NEEDS_VERIFICATION, REJECT)
INVALID_BUSINESS_NAMES = {
    "view our",
    "view our menu",
    "our menu",
    "menu",
    "home",
    "about us",
    "contact us",
    "order online",
    "learn more",
    "unknown",
    "none",
    "n/a",
}
VALID_DESSERT_TYPES = {
    "ice cream",
    "frozen yogurt",
    "froyo",
    "cake",
    "cheesecake",
    "cupcake",
    "cookie",
    "brownie",
    "muffin",
    "macaron",
    "donut",
    "doughnut",
    "pastry",
    "pie",
    "gelato",
    "sorbet",
    "pudding",
    "sundae",
    "milkshake",
}

def is_suspicious_business_name(name):
    normalized = str(name or "").strip().lower()
    return not normalized or normalized in INVALID_BUSINESS_NAMES


def resolve_business_name(dessert):
    business = dessert.get("business", "")

    # Preserve existing valid business names.
    if not is_suspicious_business_name(business):
        return dessert

    # Look for URLs directly in the dessert record.
    urls = [
        dessert.get("source_url"),
        dessert.get("url"),
    ]

    # Also look for URLs inside research evidence.
    for evidence in dessert.get("evidence") or []:
        urls.extend([
            evidence.get("source_url"),
            evidence.get("url"),
        ])

    for url in urls:
        if not isinstance(url, str) or not url:
            continue

        domain = urlparse(url).hostname or ""
        domain = domain.removeprefix("www.")

        if not domain:
            continue

        name = domain.split(".")[0]

        # Avoid third-party platforms.
        if name in {
            "facebook",
            "instagram",
            "yelp",
            "doordash",
            "ubereats",
            "tripadvisor",
            "google",
            "toasttab",
            "square",
            "grubhub",
        }:
            continue

        name = name.replace("-", " ").replace("_", " ")

        if not is_suspicious_business_name(name):
            dessert["original_business"] = business
            dessert["business"] = name
            dessert["business_name_corrected"] = True
            dessert["business_name_source"] = "domain"
            break

    return dessert


def normalize_business_names(records):
    return [
        resolve_business_name(record)
        for record in records
    ]
# Site text after a real item: "Sherbet blended with soda water Book a Party" -> keep the item.
NAV_TAIL = re.compile(
    r"\b(book a party|order online|view menu|learn more|click here|contact us|"
    r"see more|add to cart|shop now|sign up)\b.*$",
    re.IGNORECASE,
)
DESSERT_WITH_DRINK_FLAVOR = re.compile(
    r"\b(?:coffee|espresso|americano|cold brew|latte|tea|chai|steamers?)"
    r"(?:[\s-]+[\w]+){0,3}[\s-]+"
    r"(?:ice cream|frozen yogurt|cheesecakes?|cupcakes?|cakes?|"
    r"cookies?|brownies?|muffins?|macarons?|donuts?|doughnuts?|"
    r"pastr(?:y|ies)|pies?|gelato|sorbet|pudding|sundaes?)\b",
    re.IGNORECASE,
)
# A starting-price lead-in at the end: "Multi tiered cakes start at" or "... starts at $150".
START_AT = re.compile(
    r"\s*\b(?:starts?|starting)\s+at\b\s*(?:\$\s*\d[\d.,]*)?\s*$",
    re.IGNORECASE,
)
STARTS_AT_ANY = re.compile(r"\b(?:starts?|starting)\s+at\b", re.IGNORECASE)

NAV_WHOLE = {
    "about us", "home", "menu", "our menu", "contact us", "extras", "special blend",
    "privacy policy", "terms of service", "business hours", "read more", "learn more",
    "order online", "view menu", "click here", "shop now", "see more", "add to cart",
}
HOURS = re.compile(
    r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b.*\d|\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\b(noon|midnight)\b",
    re.IGNORECASE,
)
ADDRESS_OR_PHONE = re.compile(
    r"\b\d{2,6}\s+\w+.*\b(st|street|ave|avenue|rd|road|blvd|hwy|dr|drive|ln|lane|way|pike)\b"
    r"|\b(tn|tennessee)\s*\d{5}\b|\(\d{3}\)\s*\d{3}-\d{4}",
    re.IGNORECASE,
)
# Drinks with no sweet dessert meaning. Review this list.
NON_SWEET_DRINK = re.compile(
    r"\b(coffee|espresso|americano|cold brew|latte|tea|chai|steamers?)\b", re.IGNORECASE
)
# Sweet drinks that are kept even when they contain a word from the list above.
SWEET_DRINK = re.compile(
    r"\bhot chocolate\b|\bchocolate milk\b|\bmilkshakes?\b|\bfloats?\b|\bshakes?\b|\bsundaes?\b",
    re.IGNORECASE,
)


def clean_name(name: Optional[str]) -> Optional[str]:
    """Trim trailing site text and starting-price lead-ins. Return None if nothing is left."""
    text = NAV_TAIL.sub("", (name or "").strip())
    text = START_AT.sub("", text).strip(" -:,")
    return text or None


def is_junk(
    name: Optional[str],
    dessert_type: Optional[str] = None
) -> bool:

    text = clean_name(name)
    kind = (dessert_type or "").strip().lower()

    if text is None or text.casefold() in NAV_WHOLE:
        return True

    if HOURS.search(text) or ADDRESS_OR_PHONE.search(text):
        return True

    if NON_SWEET_DRINK.search(text):

        # Keep recognized sweet drinks.
        if SWEET_DRINK.search(text):
            return False

        # Keep dessert names containing drink flavors.
        if DESSERT_WITH_DRINK_FLAVOR.search(text):
            return False

        # Keep items classified as a valid dessert type.
        if kind in VALID_DESSERT_TYPES:
            return False

        # Otherwise, remove non-sweet drinks.
        return True

    return False

def screen(records: List[Dict[str, Any]], log: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    dropped: List[str] = []
    for record in records:
        raw = record.get("name")
        if is_junk(raw, record.get("dessert_type")):
            dropped.append(str(raw))
            continue
        item = dict(record)
        item["name"] = clean_name(raw)
        if STARTS_AT_ANY.search(raw or ""):
            item["price_note"] = "starting price"
        kept.append(item)

    if log is not None:
        log.append(f"Screening removed {len(dropped)} junk record(s); {len(kept)} kept")
        for name in dropped[:20]:
            log.append(f"  removed: {name[:80]}")
    return kept