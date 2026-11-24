"""Persistent processed dessert cache."""

import json
import logging
import re
import time

import config

logger = logging.getLogger(__name__)

CACHE_VERSION = 1

CACHE_SECTIONS = (
    "dessert_specific",
    "flavor_specific",
    "dessert_and_flavor",
    "any_to_any"
)

REQUIRED_FIELDS = (
    "checked_candidates",
    "all_desserts",
    "checking_results",
)


def initialize_cache():
    """Create all three processed cache folders."""

    for section in CACHE_SECTIONS:

        folder = config.PROCESSED_CACHE_DIR / section

        folder.mkdir(
            parents=True,
            exist_ok=True
        )


def _normalize(value):
    value = str(value or "").strip().lower()

    if value in {"", "any", "none"}:
        return "any"

    return re.sub(
        r"[^a-z0-9]+", "_", value
    ).strip("_")


def _supported_location(request):
    location = str(
        request.get("location") or ""
    ).strip().lower()

    return location in {
        "cookeville",
        "cookeville, tn",
        "cookeville, tennessee",
    }


def get_cache_path(request):
    dessert = _normalize(request.get("dessert_type"))
    flavor = _normalize(request.get("flavor"))

    if dessert == "any" and flavor == "any":
        section = "any_to_any"

    elif flavor == "any":
        section = "dessert_specific"

    elif dessert == "any":
        section = "flavor_specific"

    else:
        section = "dessert_and_flavor"

    return (
        config.PROCESSED_CACHE_DIR
        / section
        / f"{dessert}_{flavor}.json"
    )


def _read_cache(path):
    """Load and validate the basic JSON structure."""

    try:
        with path.open(
            "r", encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):
            return None

        if data.get("cache_version") != CACHE_VERSION:
            return None

        if not all(
            isinstance(data.get(field), list)
            for field in REQUIRED_FIELDS
        ):
            return None

        return data

    except (OSError, ValueError):
        return None


def load_processed_cache(request):
    initialize_cache()

    if not _supported_location(request):
        return False, None

    dessert = _normalize(request.get("dessert_type"))
    flavor = _normalize(request.get("flavor"))

    path = get_cache_path(request)

    if dessert == "any" and flavor == "any":

        # Require a dedicated Any-to-Any cache first.
        data = _read_cache(path)

        if data is None:
            return False, None

        # Combine results from all four folders.
        return load_all_processed_caches()

    data = _read_cache(path)

    return data is not None, data

def save_processed_cache(
    request,
    checked_candidates,
    all_desserts,
    checking_results,
):
    """Save completed dessert processing results."""

    initialize_cache()

    if not _supported_location(request):
        print("CACHE SAVE FAILED: Unsupported location:",
              request.get("location"))
        return False

    path = get_cache_path(request)

    print("Saving processed cache to:", path.resolve())

    data = {
        "cache_version": CACHE_VERSION,
        "timestamp": time.time(),
        "request": request,
        "checked_candidates": checked_candidates,
        "all_desserts": all_desserts,
        "checking_results": checking_results,
    }

    temporary_path = path.with_suffix(".tmp")

    try:
        with temporary_path.open(
            "w", encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False
            )

        temporary_path.replace(path)

        return True

    except (OSError, TypeError, ValueError):

        logger.exception(
            "Could not save processed cache"
        )

        return False


def _dessert_key(dessert):
    """Identify duplicate desserts across searches."""

    return (
        _normalize(dessert.get("name")),
        _normalize(dessert.get("business")),
        _normalize(dessert.get("dessert_type")),
        tuple(sorted({
            _normalize(flavor)
            for flavor in (
                dessert.get("flavors") or []
            )
        })),
    )


def _candidate_key(candidate):
    return _dessert_key(candidate["dessert"])


def _verification_priority(candidate):
    check = candidate.get("check", {})

    return (
        check.get("status") == "verified",
        len(check.get("verified_fields") or []),
    )


def load_all_processed_caches():
    """Combine all three folders for Any-to-Any."""

    initialize_cache()

    merged = {
        field: {}
        for field in REQUIRED_FIELDS
    }

    valid_caches = []

    for section in CACHE_SECTIONS:

        folder = (
            config.PROCESSED_CACHE_DIR
            / section
        )

        for path in sorted(folder.glob("*.json")):

            data = _read_cache(path)

            if data is not None:
                valid_caches.append(data)

    if not valid_caches:
        return False, None

    # Prefer newer records when verification
    # quality is equal.
    valid_caches.sort(
        key=lambda data: data.get("timestamp", 0)
    )

    for data in valid_caches:

        for field in (
            "checked_candidates",
            "checking_results",
        ):

            for candidate in data[field]:

                key = _candidate_key(candidate)

                previous = merged[field].get(key)

                if (
                    previous is None
                    or _verification_priority(candidate)
                    >= _verification_priority(previous)
                ):
                    merged[field][key] = candidate

        for dessert in data["all_desserts"]:

            key = _dessert_key(dessert)

            merged["all_desserts"][key] = dessert

    return True, {
        field: list(records.values())
        for field, records in merged.items()
    }