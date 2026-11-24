"""Review-platform clients: Google Places API (New) and Yelp Fusion.

Each source provides:
- find_business(name, address) -> (listing or None, reason)
- fetch_reviews(listing) -> {"rating", "review_count", "reviews"}

Errors:
- NotConfigured: no API key set for this source (skipped, not a failure)
- RateLimited: HTTP 429 (the caller stops using this source for the run)
- SourceUnavailable: any other HTTP error, timeout, or invalid response

Only documented endpoints are used. Keys are sent in request headers and are
never included in exception messages or saved output.

Google: Places API (New). The older "Place Details" web-service endpoint is
legacy and may not be available to new projects.
Yelp: Fusion business search, business reviews. Yelp returns at most 3 review
excerpts per business. Its content terms require attribution and limit caching;
the cache TTL in config.py is kept short for that reason.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional

import config
from tools import review_cache
from tools.business_match import choose_match

PLATFORM_GOOGLE = "google"
PLATFORM_YELP = "yelp"


class SourceUnavailable(Exception):
    """The source could not be used for this request."""


class NotConfigured(SourceUnavailable):
    """No API key is set for this source."""


class RateLimited(SourceUnavailable):
    """The source returned HTTP 429. Callers should stop using it for this run."""


def _http_json(method: str, url: str, headers: Optional[Dict[str, str]] = None,
               body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=config.REVIEW_HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # must come before URLError (its parent)
        if exc.code == 429:
            raise RateLimited("rate limited (HTTP 429)") from None
        raise SourceUnavailable(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceUnavailable(f"network error: {type(exc).__name__}") from None
    except ValueError:
        raise SourceUnavailable("invalid JSON from API") from None


HttpFn = Callable[..., Dict[str, Any]]


def _location_text(address: Optional[str]) -> str:
    return address or config.RESEARCH_TOWN


class GooglePlacesSource:
    platform = PLATFORM_GOOGLE
    SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
    DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
    SEARCH_FIELDS = (
        "places.id,places.displayName,places.formattedAddress,"
        "places.rating,places.userRatingCount,places.websiteUri"
    )
    DETAILS_FIELDS = "id,displayName,formattedAddress,rating,userRatingCount,websiteUri,reviews"

    def __init__(self, api_key: Optional[str] = None, http: Optional[HttpFn] = None):
        self.api_key = config.GOOGLE_PLACES_API_KEY if api_key is None else api_key
        self._http = http

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _request(self, method: str, url: str, fields: str, body=None) -> Dict[str, Any]:
        if not self.available:
            raise NotConfigured("GOOGLE_PLACES_API_KEY is not set")
        headers = {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": fields}
        return (self._http or _http_json)(method, url, headers=headers, body=body)

    def find_business(self, name: str, address: Optional[str] = None):
        if not self.available:
            raise NotConfigured("GOOGLE_PLACES_API_KEY is not set")
        query = f"{name} {_location_text(address)}"
        hit, listings = review_cache.memory_get("google_search", query)
        if not hit:
            data = self._request(
                "POST", self.SEARCH_URL, self.SEARCH_FIELDS,
                body={"textQuery": query, "maxResultCount": 5},
            )
            listings = [_google_listing(p) for p in data.get("places", [])]
            review_cache.memory_put("google_search", query, listings)
        return choose_match(name, address, listings)

    def fetch_reviews(self, listing: Dict[str, Any]) -> Dict[str, Any]:
        hit, details = review_cache.memory_get("google_details", listing["id"])
        if not hit:
            data = self._request(
                "GET", self.DETAILS_URL.format(place_id=urllib.parse.quote(listing["id"], safe="")),
                self.DETAILS_FIELDS,
            )
            details = {
                "rating": data.get("rating"),
                "review_count": data.get("userRatingCount"),
                "url": f"https://www.google.com/maps/place/?q=place_id:{listing['id']}",
                "reviews": [_google_review(r) for r in data.get("reviews", [])],
            }
            review_cache.memory_put("google_details", listing["id"], details)
        return {
            "rating": details.get("rating"),
            "review_count": details.get("review_count"),
            "reviews": details.get("reviews", []),
        }


def _google_listing(place: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": place.get("id"),
        "name": (place.get("displayName") or {}).get("text"),
        "address": place.get("formattedAddress"),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "url": place.get("websiteUri"),
        "closed": False,
    }


def _google_review(review: Dict[str, Any]) -> Dict[str, Any]:
    text = (review.get("text") or {}).get("text") or (review.get("originalText") or {}).get("text")
    return {
        "review_id": review.get("name") or "",
        "rating": review.get("rating"),
        "text": text,
        "date": review.get("publishTime"),
        "url": None,
    }


class YelpFusionSource:
    platform = PLATFORM_YELP
    BASE_URL = "https://api.yelp.com/v3/businesses"

    def __init__(self, api_key: Optional[str] = None, http: Optional[HttpFn] = None):
        self.api_key = config.YELP_API_KEY if api_key is None else api_key
        self._http = http

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _request(self, url: str) -> Dict[str, Any]:
        if not self.available:
            raise NotConfigured("YELP_API_KEY is not set")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        return (self._http or _http_json)("GET", url, headers=headers)

    def find_business(self, name: str, address: Optional[str] = None):
        if not self.available:
            raise NotConfigured("YELP_API_KEY is not set")
        location = _location_text(address)
        cache_key = f"{name}|{location}"
        hit, listings = review_cache.disk_get("yelp_search", cache_key)
        if not hit:
            params = urllib.parse.urlencode({"term": name, "location": location, "limit": 5})
            data = self._request(f"{self.BASE_URL}/search?{params}")
            listings = [_yelp_listing(b) for b in data.get("businesses", [])]
            review_cache.disk_put("yelp_search", cache_key, listings)
        return choose_match(name, address, listings)

    def fetch_reviews(self, listing: Dict[str, Any]) -> Dict[str, Any]:
        hit, reviews = review_cache.disk_get("yelp_reviews", listing["id"])
        if not hit:
            url = f"{self.BASE_URL}/{urllib.parse.quote(listing['id'], safe='')}/reviews?locale=en_US"
            try:
                data = self._request(url)
            except RateLimited:
                raise
            except SourceUnavailable:
                # This key cannot read review text. Keep the search rating and count.
                # Nothing is cached, so the request is retried on the next run.
                return {
                    "rating": listing.get("rating"),
                    "review_count": listing.get("review_count"),
                    "reviews": [],
                }
            reviews = [_yelp_review(r) for r in data.get("reviews", [])]
            review_cache.disk_put("yelp_reviews", listing["id"], reviews)
        # Yelp's search result already carries the rating and count for this business.
        return {
            "rating": listing.get("rating"),
            "review_count": listing.get("review_count"),
            "reviews": reviews,
        }

    def fetch_hours(self, listing: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Weekly hours from Yelp's business details endpoint, or None if Yelp lists none.

        Cached for the Yelp 24-hour window. Yelp's "open now" flag is not kept, because it
        goes stale; the caller works out open/closed from the weekly hours and the clock.
        """
        hit, hours = review_cache.disk_get("yelp_hours", listing["id"])
        if not hit:
            url = f"{self.BASE_URL}/{urllib.parse.quote(listing['id'], safe='')}"
            hours = _yelp_hours(self._request(url))
            review_cache.disk_put("yelp_hours", listing["id"], hours)
        return hours


def _yelp_hours(business: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Turn Yelp's hours block into {"weekly": [{day, start, end, overnight}, ...]}.

    Yelp days: 0 = Monday ... 6 = Sunday, which matches Python's date.weekday().
    Times are "HHMM" strings. Returns None when there are no usable hours.
    """
    entries = business.get("hours") or []
    if not entries:
        return None
    chosen = next((e for e in entries if e.get("hours_type") == "REGULAR"), entries[0])
    weekly = []
    for slot in chosen.get("open") or []:
        day, start, end = slot.get("day"), slot.get("start"), slot.get("end")
        if isinstance(day, int) and 0 <= day <= 6 and start and end:
            weekly.append({
                "day": day,
                "start": str(start),
                "end": str(end),
                "overnight": bool(slot.get("is_overnight")),
            })
    return {"weekly": weekly} if weekly else None


def _yelp_listing(business: Dict[str, Any]) -> Dict[str, Any]:
    location = business.get("location") or {}
    address = ", ".join(
        part for part in (location.get("address1"), location.get("city"), location.get("state")) if part
    )
    return {
        "id": business.get("id"),
        "name": business.get("name"),
        "address": address or None,
        "rating": business.get("rating"),
        "review_count": business.get("review_count"),
        "url": business.get("url"),
        "closed": bool(business.get("is_closed")),
    }


def _yelp_review(review: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "review_id": review.get("id") or "",
        "rating": review.get("rating"),
        "text": review.get("text"),
        "date": review.get("time_created"),
        "url": review.get("url"),
    }


def build_source(platform: str):
    """Return a source object for a platform name, or None if the name is unknown."""
    if platform == PLATFORM_GOOGLE:
        return GooglePlacesSource()
    if platform == PLATFORM_YELP:
        return YelpFusionSource()
    return None
