import copy
import hashlib
import json
import time
from pathlib import Path

CACHE_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "research_cache"
)

DESSERT_CHILDREN = {
    "cake": {"cheesecake"},
    "cupcake": {"muffin"},
}

# Existing successful Cookeville research files.
LEGACY_FILES = {
    "cookeville, tn": [
        "7d639c83ac49f7afde58f3edbc7d4d62fdfc290c0f43e4ff278414713de8d6ac.json",
        "822b847b861c5243eede3d1bbdd4a1298171ea3de407c12c7d75b4e783476c1d.json",
    ]
}


def _normalize(value):
    return str(value or "").strip().lower()


def _location(request):
    location = _normalize(request.get("location"))
    location = location.replace(", tennessee", ", tn")

    if location == "cookeville":
        location = "cookeville, tn"

    return location


def _cache_path(request):
    key = json.dumps(request, sort_keys=True, default=str)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()

    return CACHE_DIR / f"{digest}.json"


def _shared_cache_path(request):
    key = json.dumps({
        "location": _location(request),
        "data_source": request.get("data_source"),
    }, sort_keys=True)

    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()

    return CACHE_DIR / f"shared_{digest}.json"


def _read_cache(path):
    try:
        with path.open("r", encoding="utf-8") as file:
            cached = json.load(file)

        desserts = cached.get("desserts", [])

        if not isinstance(desserts, list):
            return []

        return [
            dessert for dessert in desserts
            if isinstance(dessert, dict)
        ]

    except (OSError, ValueError, KeyError, TypeError):
        return []


def _merge_desserts(*collections):
    merged = {}

    for desserts in collections:
        for dessert in desserts:
            dessert_id = dessert.get("dessert_id")

            if dessert_id:
                merged[dessert_id] = copy.deepcopy(dessert)

    return list(merged.values())


def _legacy_desserts(request):
    collections = []

    # Original exact-request cache.
    exact = _read_cache(_cache_path(request))

    if exact:
        collections.append(exact)

    # Recover known successful location-specific files.
    for filename in LEGACY_FILES.get(_location(request), []):

        path = CACHE_DIR / filename
        desserts = _read_cache(path)

        if desserts:
            print(
                f"LEGACY CACHE FOUND: "
                f"{filename} - {len(desserts)} desserts"
            )

            collections.append(desserts)

    return _merge_desserts(*collections)


def _write_cache(path, desserts):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": time.time(),
        "desserts": copy.deepcopy(desserts),
    }

    temp_path = path.with_suffix(".tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)

    temp_path.replace(path)


def get_cached(request):
    path = _shared_cache_path(request)

    existing = _read_cache(path)
    legacy = _legacy_desserts(request)

    desserts = _merge_desserts(legacy, existing)

    if not desserts:
        return None

    # Permanently preserve recovered research.
    if desserts != existing:
        _write_cache(path, desserts)

    requested_type = _normalize(
        request.get("dessert_type")
    )

    # Any dessert type returns the complete cache.
    if requested_type in ("", "any", "none", "all"):
        return copy.deepcopy(desserts)

    # Check if the requested category exists.
    exact_matches = [
        dessert for dessert in desserts
        if _normalize(dessert.get("dessert_type"))
        == requested_type
    ]

    # Only research when the category is missing.
    if not exact_matches:
        return None
    # Requested category exists.
    # Return the full cache so screening and checking
    # can correct dessert types and flavors.
    return copy.deepcopy(desserts)
    


def save_cached(request, desserts):

    # Never replace existing data with empty results.
    if not desserts:
        return

    path = _shared_cache_path(request)

    existing = _read_cache(path)
    legacy = _legacy_desserts(request)

    merged = _merge_desserts(
        legacy,
        existing,
        desserts
    )

    _write_cache(path, merged)