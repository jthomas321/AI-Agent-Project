"""Caches for review data. Two stores, chosen per data source.

disk:   JSON files in data/review_cache/, expiring after config.REVIEW_CACHE_TTL_HOURS.
        Used for Yelp data, and for analyses that contain no Google text.
memory: kept only in this Python process, expiring after
        config.GOOGLE_MEMORY_CACHE_MINUTES. Used for Google data, which has its own
        caching terms and is never written to disk.

A miss returns (False, None). A cached value of None returns (True, None).
Setting a TTL to 0 disables that store.
"""

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import config

_MEMORY: Dict[Tuple[str, str], Tuple[float, Any]] = {}


def _path(namespace: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return Path(config.REVIEW_CACHE_DIR) / namespace / f"{digest}.json"


# ---- disk store -----------------------------------------------------------

def disk_get(namespace: str, key: str, now: Optional[datetime] = None) -> Tuple[bool, Any]:
    if config.REVIEW_CACHE_TTL_HOURS <= 0:
        return False, None
    try:
        with open(_path(namespace, key), encoding="utf-8") as f:
            entry = json.load(f)
        fetched_at = datetime.fromisoformat(entry["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False, None

    now = now or datetime.now(timezone.utc)
    if now - fetched_at > timedelta(hours=config.REVIEW_CACHE_TTL_HOURS):
        return False, None
    return True, entry.get("payload")


def disk_put(namespace: str, key: str, payload: Any, now: Optional[datetime] = None) -> None:
    if config.REVIEW_CACHE_TTL_HOURS <= 0:
        return
    path = _path(namespace, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "fetched_at": (now or datetime.now(timezone.utc)).isoformat(),
        "payload": payload,
    }
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False)
    os.replace(tmp, path)


# ---- memory store ---------------------------------------------------------

def _clock() -> float:
    return time.monotonic()


def memory_get(namespace: str, key: str) -> Tuple[bool, Any]:
    if config.GOOGLE_MEMORY_CACHE_MINUTES <= 0:
        return False, None
    entry = _MEMORY.get((namespace, key))
    if entry is None:
        return False, None
    expires_at, payload = entry
    if _clock() > expires_at:
        _MEMORY.pop((namespace, key), None)
        return False, None
    return True, payload


def memory_put(namespace: str, key: str, payload: Any) -> None:
    if config.GOOGLE_MEMORY_CACHE_MINUTES <= 0:
        return
    expires_at = _clock() + config.GOOGLE_MEMORY_CACHE_MINUTES * 60
    _MEMORY[(namespace, key)] = (expires_at, payload)


def clear_memory() -> None:
    _MEMORY.clear()
