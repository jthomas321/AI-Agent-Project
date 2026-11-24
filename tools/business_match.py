"""Match a dessert shop to its listing on a review platform.

A wrong match would attach another shop's reviews to this shop, so matching is
strict. A listing is accepted only when:
- its name is essentially the same as the dessert record's business name, AND
- its street number matches the dessert record's address and it is in Cookeville
  (or, when the dessert record has no address, the name is an exact match and
  the listing is in Cookeville).

If more than one listing passes, the match is ambiguous and is rejected.
Closed listings are ignored.
"""

import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, Optional, Tuple

NAME_THRESHOLD = 0.92
TOWN = "cookeville"
_STREET_NUMBER = re.compile(r"^\s*(\d+)\b")


def normalize_name(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def street_number(address: Optional[str]) -> Optional[str]:
    if not address:
        return None
    match = _STREET_NUMBER.match(address)
    return match.group(1) if match else None


def names_match(a: Optional[str], b: Optional[str]) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= NAME_THRESHOLD


def _in_town(address: Optional[str]) -> bool:
    return bool(address) and TOWN in address.lower()


def _accepts(business_name: str, address: Optional[str], listing: Dict[str, Any]) -> bool:
    if listing.get("closed"):
        return False
    listing_address = listing.get("address")
    if address:
        if not names_match(business_name, listing.get("name")):
            return False
        if not _in_town(listing_address):
            return False
        number = street_number(address)
        return number is not None and number == street_number(listing_address)
    # No address on the dessert record: only an exact name in town is accepted.
    return (
        normalize_name(business_name) == normalize_name(listing.get("name"))
        and _in_town(listing_address)
    )


def choose_match(
    business_name: str,
    address: Optional[str],
    listings: Iterable[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return (listing, reason). reason is 'matched', 'no_match', or 'ambiguous'.

    Each listing is a dict with at least 'id', 'name', 'address'.
    """
    accepted: Dict[str, Dict[str, Any]] = {}
    for listing in listings:
        if not listing.get("id"):
            continue
        if _accepts(business_name, address, listing):
            accepted.setdefault(listing["id"], listing)

    if not accepted:
        return None, "no_match"
    if len(accepted) > 1:
        return None, "ambiguous"
    return next(iter(accepted.values())), "matched"


def business_key(dessert: Dict[str, Any]) -> str:
    """Records for the same business share a key. The address number separates chain locations."""
    name = normalize_name(dessert.get("business"))
    number = street_number(dessert.get("address"))
    return f"{name}|{number}" if number else name
