"""Business hours for the ranking agent, from Yelp.

hours_for_businesses(desserts) looks up each shop with the same strict matching used
for review scores (name, street number, Cookeville). It then fetches the shop's weekly
hours. A shop with no match, no hours, or a failed call gets no record. The ranking
treats that as "hours not available", which is neutral and not a penalty.

Yelp lets hours be cached for 24 hours. That cache lives in tools/review_cache.py.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from tools.business_match import business_key
from tools.review_apis import YelpFusionSource

logger = logging.getLogger(__name__)

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def hours_for_businesses(desserts, source=None) -> List[Dict[str, Any]]:
    """One hours record per shop that Yelp matches and lists hours for."""
    source = source or YelpFusionSource()
    if not source.available:
        return []
    records = []
    seen = set()
    for dessert in desserts:
        key = business_key(dessert)
        if key in seen:
            continue
        seen.add(key)
        record = _hours_for_one(dessert, key, source)
        if record is not None:
            records.append(record)
    return records


def _hours_for_one(dessert, key, source) -> Optional[Dict[str, Any]]:
    try:
        listing, reason = source.find_business(dessert["business"], dessert.get("address"))
        if listing is None:
            logger.info("Yelp hours: no match for %s (%s)", dessert["business"], reason)
            return None
        hours = source.fetch_hours(listing)
    except Exception as exc:  # one shop's failure must not stop the others
        logger.warning("Yelp hours unavailable for %s: %s", dessert["business"], exc)
        return None
    if not hours or not hours.get("weekly"):
        return None
    return {
        "business_key": key,
        "business_name": dessert["business"],
        "source": "yelp",
        "weekly": hours["weekly"],
    }


def hours_text(record: Optional[Dict[str, Any]]) -> Optional[str]:
    """Readable summary, for example 'Mon 11:00-20:00, Tue 11:00-20:00'."""
    if not record or not record.get("weekly"):
        return None
    slots = sorted(record["weekly"], key=lambda s: (s["day"], int(s["start"])))
    return ", ".join(
        f"{DAY_NAMES[s['day']]} {_clock(s['start'])}-{_clock(s['end'])}" for s in slots
    )


def is_open_at(record: Optional[Dict[str, Any]], when: datetime) -> Optional[bool]:
    """Is the shop open at this local time? None when no hours are known.

    Yelp closing times are exclusive. A slot that closes at or before it opens (or is
    flagged overnight) runs past midnight into the next day.
    """
    if not record or not record.get("weekly"):
        return None
    today = when.weekday()
    yesterday = (today - 1) % 7
    now = when.hour * 100 + when.minute
    for slot in record["weekly"]:
        start, end = int(slot["start"]), int(slot["end"])
        overnight = slot.get("overnight") or end <= start
        if slot["day"] == today:
            if overnight and now >= start:
                return True
            if not overnight and start <= now < end:
                return True
        if slot["day"] == yesterday and overnight and now < end:
            return True
    return False


def _clock(hhmm: str) -> str:
    text = str(hhmm).zfill(4)
    return f"{text[:2]}:{text[2:]}"
