
"""Research agent.

Contract: research(request, attempt=1) -> list of Dessert records.

Prioritizes business-owned websites and menu pages.
Extracts dessert names and prices from visible menu text.
Preserves source evidence. Never invents menu facts.
"""

import hashlib
import re
import ssl
import certifi
from tools.research_cache import get_cached, save_cached
from datetime import datetime, timezone
from getpass import getpass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

import config
from models import validate_dessert
from tools.menu_ocr import is_non_item_text
from tools.web_search import search
from tools.dessert_types import (
    CATEGORY_LABELS,
    CATEGORIES,
    ICE_CREAM,
    SEARCH_WORDS,
    canonical_type,
    classify,
    is_ice_cream_name,
)



#  WEBSITE FILTERING


UNOFFICIAL_DOMAINS = {
    "yelp.com",
    "tripadvisor.com",
    "tripadvisor.ca",
    "tripadvisor.ie",
    "tripadvisor.in",
    "tripadvisor.co.uk",
    "facebook.com",
    "instagram.com",
    "reddit.com",
    "doordash.com",
    "ubereats.com",
    "grubhub.com",
    "postmates.com",
    "yellowpages.com",
    "snapchat.com",
    "cookevillebites.com",
}

# Secondary ordering platforms.
# These are not considered business-owned sources.
SECONDARY_DOMAINS = {
    "postmates.com",
    "doordash.com",
    "ubereats.com",
    "grubhub.com",
    "square.site",
    "order.online",
}


def _get_host(url):
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def _is_unofficial(url):
    """Identify directories, review sites, and social platforms."""

    host = _get_host(url)

    return any(
        host == domain or host.endswith("." + domain)
        for domain in UNOFFICIAL_DOMAINS
    )


def _is_secondary_source(url):
    """Identify ordering platforms and other secondary sources."""

    host = _get_host(url)

    return any(
        host == domain or host.endswith("." + domain)
        for domain in SECONDARY_DOMAINS
    )


def _is_relevant_result(result, location):
    """Check whether a search result appears relevant to the request."""

    title = result.get("title", "").lower()
    snippet = result.get("snippet", "").lower()
    url = result.get("url", "").lower()

    text = f"{title} {snippet} {url}"

    dessert_keywords = [
        "donut",
        "doughnut",
        "bakery",
        "cupcake",
        "cake",
        "ice cream",
        "dessert",
        "cookie",
        "creamery",
        "pastry",
        "sweet",
        "menu",
        "frozen yogurt",
        "brownie",
        "pie",
    ]

    local_keywords = [
        "cookeville",
        "38501",
        "38506",
        "ralph's",
        "ralphs",
        "p-dilly",
        "pdilly",
        "lazy cow",
        "cream city",
    ]

    location_name = location.lower().split(",")[0].strip()

    if location_name:
        local_keywords.append(location_name)

    has_dessert = any(
        word in text for word in dessert_keywords + list(SEARCH_WORDS)
    )

    has_local_reference = any(
        word in text for word in local_keywords
    )

    return has_dessert and has_local_reference


#  LOCATION VALIDATION


def _is_correct_location(page_text, location):
    """Reject pages clearly identifying a different business location."""

    requested_city = location.lower().split(",")[0].strip()
    text = page_text.lower()

    if requested_city == "cookeville":

        other_cities = [
            "crossville, tn",
            "rossville, tn",
        ]

        has_other_city = any(
            city in text for city in other_cities
        )

        has_cookeville = (
            "cookeville, tn" in text
            or "cookeville, tennessee" in text
            or "cookeville tn" in text
        )

        if has_other_city and not has_cookeville:
            return False

    return True



#  MENU AND PRICE PATTERNS


PRICE_PATTERN = re.compile(
    r"\$\s*(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)"
)

# Prices written without a "$": "Price: 3.00", "Cost 4.50", or a bare "4.25" at the end of a short line.
LABELLED_PRICE_PATTERN = re.compile(
    r"(?:price|cost)\s*:?\s*\$?\s*(\d{1,4}\.\d{2})\b",
    re.IGNORECASE,
)
MENU_HEADINGS = {
    "menu", "our menu", "desserts", "dessert", "bakery", "shop", "home", "flavors",
    "pricing", "policies", "sweets", "pastries", "cakes", "cookies", "donuts",
}
PRICE_LABEL_SUFFIX = re.compile(r"\s*\b(?:price|cost)\s*:?\s*$", re.IGNORECASE)
BARE_PRICE_PATTERN = re.compile(r"(?<![\d.])(\d{1,3}\.\d{2})\s*$")


def _find_price(line):
    """A price match for one line, or None. Tries the $ form first, then labelled and bare forms."""
    match = PRICE_PATTERN.search(line)
    if match:
        return match
    match = LABELLED_PRICE_PATTERN.search(line)
    if match:
        return match
    if len(line.split()) <= 10:
        return BARE_PRICE_PATTERN.search(line)
    return None

MENU_WORDS = (
    "menu",
    "dessert",
    "cake",
    "cupcake",
    "bakery",
    "ice cream",
    "cookie",
    "donut",
    "doughnut",
    "sweet",
    "chocolate",
    "pastry",
    "creamery",
)

DESSERT_ITEM_WORDS = (
    "twist",
    "glazed",
    "fritter",
    "bavarian",
    "cinnamon",
    "sprinkle",
    "frosted",
    "filled",
    "long john",
    "bear claw",
    "danish",
    "brownie",
    "blondie",
    "macaron",
    "gelato",
    "sorbet",
    "cheesecake",
    "muffin",
    "pie",
    "tart",
    "croissant",
)

DESSERT_TYPES = {key: info["keywords"] for key, info in CATEGORIES.items()}



#  MAIN RESEARCH FUNCTIONS


'''def research(request, attempt=1):

    if config.DATA_SOURCE == "mock":
        return _load_mock()

    return _live_search(request, attempt)
'''

def research(request, attempt=1):

    if config.DATA_SOURCE == "mock":
        return _load_mock()

    # Keep cache keys consistent for equivalent requests.
    cache_request = {
        "location": (request.get("location") or "Cookeville, Tennessee").strip().lower(),
        "dessert_type": canonical_type(request.get("dessert_type")) or "",
        "flavor": (request.get("flavor") or "").strip().lower(),
        "max_price": request.get("max_price"),
        "max_distance_miles": request.get("max_distance_miles"),
        "data_source": config.DATA_SOURCE,
        "attempt": attempt,
        "cache_version": 3,
        "passes": 2,
    }

    cached = get_cached(cache_request)

    if cached is not None:
        try:
            validated = [validate_dessert(d) for d in cached]
            print(f"RESEARCH CACHE HIT: {len(validated)} desserts")
            return validated
        except (ValueError, TypeError, KeyError):
            print("RESEARCH CACHE INVALID: refreshing")

    print("RESEARCH CACHE MISS: running live research")

    desserts = _live_search(request, attempt)

    # Avoid caching empty or failed searches.
    if desserts:
        try:
            save_cached(cache_request, desserts)
            print(f"RESEARCH CACHE SAVED: {len(desserts)} desserts")
        except (OSError, TypeError, ValueError) as exc:
            print(f"RESEARCH CACHE SAVE FAILED: {exc}")

    return desserts

def _load_mock():

    import json

    with open(config.MOCK_DATA_PATH, encoding="utf-8") as f:
        records = json.load(f)

    return [
        validate_dessert(record)
        for record in records
    ]


#  SEARCH QUERY GENERATION


def _build_queries(request, attempt):

    location = request.get("location") or "Cookeville, Tennessee"
    dessert_type = request.get("dessert_type")
    flavor = request.get("flavor")

    queries = [
        f'"Ralph\'s Donut Shop" {location} official menu',
        f'"P-Dilly\'s Cupcakes" {location} menu',
        f'"Lazy Cow Creamery" {location} menu',
        f'"Cream City Ice Cream" {location} menu',
        f'"{location}" bakery official website menu',
        f'"{location}" dessert menu prices',
    ]

    if dessert_type:
        queries.insert(
            0,
            f'"{dessert_type}" menu {location} official website'
        )

    if flavor:
        queries.append(
            f'"{flavor}" desserts {location} menu prices'
        )

    if attempt > 1:

        queries = [
            f'"{location}" dessert shop official menu prices',
            f'"{location}" bakery online menu prices',
        ]

        if dessert_type:
            queries.append(
                f'"{dessert_type}" {location} menu prices'
            )

        if flavor:
            queries.append(
                f'"{flavor}" dessert {location} bakery menu'
            )

    return list(dict.fromkeys(queries))


#  FETCH WEBSITE HTML


# Words that suggest a link leads to a menu, order, or price page.
MENU_LINK_WORDS = (
    "menu", "order", "dessert", "pricing", "flavor", "cupcake", "donut",
    "cake", "cookie", "pastry", "bakery",
)


def _collect_links(soup, base_url):
    """(absolute url, link text) for every link on the page. Taken before nav and footer are removed."""
    links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        links.append((urljoin(base_url, href), anchor.get_text(" ", strip=True)))
    return links


def _menu_links(links, page_url, limit=2):
    """Links on the same website that look like menu, order, or dessert pages."""
    host = urlparse(page_url).netloc.lower().removeprefix("www.")
    chosen = []
    for url, text in links:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower().removeprefix("www.") != host:
            continue
        clean = parsed._replace(fragment="").geturl()
        if clean == page_url or clean in [c for c, _ in chosen]:
            continue
        label = f"{text} {parsed.path}".lower()
        if any(word in label for word in MENU_LINK_WORDS):
            chosen.append((clean, text))
        if len(chosen) >= limit:
            break
    return chosen


def _fetch_page(url):

    """Download a public HTML page using verified SSL."""

    if urlparse(url).scheme not in ("http", "https"):
        return None

    try:

        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        context = ssl.create_default_context(
            cafile=certifi.where()
        )

        with urlopen(
            request,
            timeout=30,
            context=context
        ) as response:

            content_type = response.headers.get(
                "Content-Type", ""
            ).lower()

            print("\nPAGE STATUS:", response.status)
            print("CONTENT TYPE:", content_type)
            print("FINAL URL:", response.geturl())

            if "html" not in content_type:
                print("NOT AN HTML PAGE")
                return None

            html = response.read(
                2_000_000
            ).decode(
                "utf-8",
                errors="replace"
            )

            final_url = response.geturl()

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        links = _collect_links(soup, final_url)
        images = _collect_images(soup, final_url)

        page_title = (
            soup.title.get_text(" ", strip=True)
            if soup.title else ""
        )

        for element in soup([
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "noscript",
        ]):
            element.decompose()

        page_text = soup.get_text(
            separator="\n",
            strip=True
        )

        return {
            "title": page_title,
            "text": page_text,
            "url": final_url,
            "links": links,
            "images": images,
        }

    except HTTPError as exc:
        print(f"HTTP ERROR: {exc.code} - {exc.reason}")

    except URLError as exc:
        print(f"URL ERROR: {exc.reason}")

    except ssl.SSLError as exc:
        print(f"SSL ERROR: {exc}")

    except TimeoutError:
        print("TIMEOUT: Website took too long to respond.")

    except Exception as exc:
        print(
            f"OTHER ERROR: {type(exc).__name__}: {exc}"
        )

    return None


#  PLAYWRIGHT BROWSER FALLBACK


def fetch_with_browser(url):
    """
    Extract text from JavaScript-rendered pages.

    Important:
    The browser is closed before the Playwright session ends.
    This prevents the 'Event loop is closed' cleanup error.
    """

    try:

        from playwright.sync_api import sync_playwright

        # Start Playwright.
        with sync_playwright() as p:

            browser = None

            try:

                browser = p.chromium.launch(
                    headless=True
                )

                page = browser.new_page(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
                    )
                )

                print("Opening browser page:", url)

                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000
                )

                if response:
                    print(
                        "BROWSER PAGE STATUS:",
                        response.status
                    )

                # Give JavaScript time to display menu content.
                page.wait_for_timeout(3000)

                # Try to wait for the body to become available.
                page.locator("body").wait_for(
                    state="visible",
                    timeout=10000
                )

                page_title = page.title()

                page_text = page.locator(
                    "body"
                ).inner_text(
                    timeout=10000
                )

                final_url = page.url

                print(
                    "BROWSER TEXT LENGTH:",
                    len(page_text)
                )

                return {
                    "title": page_title,
                    "text": page_text,
                    "url": final_url,
                    "images": _browser_images(page),
                }

            except Exception as exc:

                print(
                    "BROWSER PAGE ERROR:",
                    type(exc).__name__,
                    str(exc)
                )

                return None

            finally:

                # Close the browser while Playwright is still active.
                if browser is not None:

                    try:
                        browser.close()

                    except Exception as exc:

                        # Cleanup failure should not crash research.
                        print(
                            "BROWSER CLEANUP WARNING:",
                            str(exc)
                        )

    except ImportError as exc:

        print(
            "PLAYWRIGHT IMPORT ERROR:",
            exc
        )

    except Exception as exc:

        print(
            "PLAYWRIGHT STARTUP ERROR:",
            type(exc).__name__,
            str(exc)
        )

    return None



#  DESSERT EXTRACTION


def _extract_with_ollama(page_text):
    """Extract desserts using Ollama with source validation."""

    from tools.menu_ocr import _ollama_items, validate_items
    from tools.ollama_client import ask_json

    try:
        proposed = _ollama_items(page_text, ask_json)
        validated = validate_items(proposed, page_text)

        lines = [
            " ".join(line.split())
            for line in page_text.splitlines()
            if line.strip()
        ]

        results = []

        for item in validated:
            name = item["name"]
            price = item["price"]

            matching_lines = [
                line for line in lines
                if name.lower() in line.lower()
            ]

            if price is not None:
                matching_lines = [
                    line for line in matching_lines
                    if f"{price:.2f}" in line
                ]

            if not matching_lines:
                continue

            results.append({
                "name": name,
                "price": price,
                "source_text": matching_lines[0],
            })

        return results

    except Exception as exc:
        print("Ollama extraction failed:", exc)
        return []
def _extract_desserts(page_text, extra_words=()):

    """Extract dessert names and prices from visible menu text."""

    records = []

    lines = [
        " ".join(line.split()).strip()
        for line in page_text.splitlines()
    ]

    for i, line in enumerate(lines):

        if not line:
            continue

        match = _find_price(line)

        if match:

            name = PRICE_LABEL_SUFFIX.sub(
                "",
                line[:match.start()].strip(" -–—:|•\t"),
            ).strip(
                " -–—:|•\t"
            )

            source_text = line

        elif i + 1 < len(lines):

            next_match = _find_price(
                lines[i + 1]
            )

            if not next_match:
                continue

            match = next_match

            name = line.strip(
                " -–—:|•\t"
            )

            source_text = f"{line} | {lines[i + 1]}"

        else:
            continue

        if not name or len(name) < 3:
            continue

        # A real item name is short. Longer text is a sentence, for example a
        # description with an add-on price.
        if len(name.split()) > 6:
            continue
        if is_non_item_text(name):
            continue

        lower_name = name.lower()

        # A section heading ("Menu", "Desserts") above a priced item is not an item.
        if lower_name in MENU_HEADINGS:
            continue

        has_dessert_keyword = any(
            word in lower_name
            for word in MENU_WORDS + DESSERT_ITEM_WORDS + tuple(extra_words)
        )

        if not has_dessert_keyword:
            continue

        try:

            price = float(
                match.group(1).replace(",", "")
            )

        except (ValueError, AttributeError):
            continue

        records.append({
            "name": name,
            "price": price,
            "source_text": source_text,
        })

    return records


def _extract_legacy_priced_items(page_text):

    """Extract dessert names and prices from visible menu text."""

    records = []

    lines = [
        " ".join(line.split()).strip()
        for line in page_text.splitlines()
    ]

    for i, line in enumerate(lines):

        if not line:
            continue

        match = PRICE_PATTERN.search(line)

        if match:

            name = line[:match.start()].strip(
                " -–—:|•\t"
            )

            source_text = line

        elif i + 1 < len(lines):

            next_match = PRICE_PATTERN.search(
                lines[i + 1]
            )

            if not next_match:
                continue

            match = next_match

            name = line.strip(
                " -–—:|•\t"
            )

            source_text = f"{line} | {lines[i + 1]}"

        else:
            continue

        if not name or len(name) < 3:
            continue

        lower_name = name.lower()

        has_dessert_keyword = any(
            word in lower_name
            for word in MENU_WORDS + DESSERT_ITEM_WORDS
        )

        if not has_dessert_keyword:
            continue

        try:

            price = float(
                match.group(1).replace(",", "")
            )

        except (ValueError, AttributeError):
            continue

        records.append({
            "name": name,
            "price": price,
            "source_text": source_text,
        })

    return records


def _extract_ice_cream_flavors(page_text):
    """Read structured flavor cards from an explicitly labeled ice-cream page.

    Never treat ingredient lists as products or invent prices.
    """
    lines = [" ".join(x.split()).strip() for x in page_text.splitlines()]
    if not any("all ice cream flavors" in x.lower() for x in lines[:30]):
        return []

    results = []
    seen = set()
    started = False
    for i, name in enumerate(lines):
        if name.lower() == "all flavors":
            started = True
            continue
        if not started:
            continue
        if name.lower() in {"contact us", "business hours", "follow us on facebook"}:
            break
        if not name or len(name.split()) > 5 or is_non_item_text(name):
            continue
        if name.lower() in {"dairy-free", "no nuts", "no eggs", "gluten-free", "gf", "df", "e", "n", "ingredients:"}:
            continue
        # Flavor card: a short title, a short description, then an ingredients block.
        if i + 1 >= len(lines):
            continue
        description = lines[i + 1]
        if not description or len(description.split()) < 5 or len(description.split()) > 35:
            continue
        if not any(x.lower() == "ingredients:" for x in lines[i + 2:i + 9]):
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        results.append({
            "name": name,
            "price": None,
            "dessert_type": "ice cream",
            "source_text": f"{name} | {description}",
        })
    return results


def _extract_flavor_cards(page_text):
    """Extract explicitly described flavors from non-Cream-City ice cream menus.

    Require an ice-cream flavor heading, a plausible short title, and a nearby
    descriptive sentence. This is a fallback, not a general text-to-menu guesser.
    """
    lines = [" ".join(x.split()).strip() for x in page_text.splitlines()]
    heading = next((i for i, line in enumerate(lines[:100])
                    if "ice cream flavors" in line.lower()), None)
    if heading is None:
        return []

    # Ignore introductory content, dietary filters and navigation.
    blocked = {
        "all flavors subject to availability", "allergy warning",
        "allergen handling policy", "dietary label explanation",
        "dietary filters", "clean label only", "dairy-free only",
        "keto/no sugar added only", "no dairy-free", "no eggs",
        "no peanuts", "no soy", "no tree nuts", "no wheat",
        "seasonal only", "ingredients & nutrition", "ingredients:",
        "standard & seasonal", "ice cream flavors", "flavors",
        "fall seasonal", "summer seasonal", "winter seasonal",
        "spring seasonal", "home", "menu", "rewards", "gift cards",
        "contact us", "business hours", "quick links", "follow us",
    }

    def is_title(s):
        low = s.lower().strip()
        return (bool(s) and 2 <= len(s) <= 45
                and len(s.split()) <= 5
                and low not in blocked
                and not low.startswith(("warnings:", "ingredients", "allergens", "click "))
                and not any(ch in s for ch in ".!?$:")
                and not any(x in s for x in ("🌱", "⭐", "🥛", "🍁"))
                and not is_non_item_text(s))

    results = []
    seen = set()
    consumed_title_lines = set()
    for i in range(heading + 1, len(lines)):
        if i in consumed_title_lines:
            continue
        title = lines[i]
        if not is_title(title):
            continue
        # Cards sometimes split titles over two lines (Apple / Pie).
        # A description must immediately follow the full title (ignoring blanks).
        for parts in (2, 1):
            if parts == 2:
                if i + 1 >= len(lines) or not is_title(lines[i + 1]):
                    continue
                name = title + " " + lines[i + 1]
                j = i + 2
            else:
                name = title
                j = i + 1
            while j < len(lines) and not lines[j] and j < i + 5:
                j += 1
            if j >= len(lines):
                continue
            description = lines[j]
            words = description.split()
            if not (8 <= len(words) <= 65 and description != name
                    and not description.lower().startswith(("warnings:", "ingredients"))
                    and ("." in description or "," in description)):
                continue
            # Do not treat the intro, policies, or nutrition text as products.
            if any(x in description.lower() for x in (
                "cross-contamination", "allergens indicated", "click the button",
                "subject to availability", "allergen handling policy")):
                continue
            if name.lower() not in seen:
                seen.add(name.lower())
                if parts == 2:
                    consumed_title_lines.add(i + 1)
                results.append({
                    "name": name,
                    "price": None,
                    "dessert_type": "ice cream",
                    "source_text": f"{name} | {description}",
                })
            break
    return results



#  DESSERT CLASSIFICATION


def _get_dessert_type(name, requested_type=None):
    return classify(name)
def _normalize_identity_text(value):
    """Normalize names and addresses for comparison."""
    value = (value or "").casefold()
    value = value.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", value)


def _business_domain(url):
    """Get the website domain without www."""
    return _get_host(url)


def _ollama_business_match(existing, new):
    """Ask Ollama whether two business records represent the same shop."""
    import json
    from tools.ollama_client import ask_json

    prompt = (
        "Compare these two dessert business records.\n"
        "Determine whether they refer to the same physical business.\n\n"
        "RULES:\n"
        "1. Compare names, addresses, and official websites.\n"
        "2. Different menu page titles may refer to the same business.\n"
        "3. Similar names alone do not prove a match.\n"
        "4. Different branches of a chain are separate locations.\n"
        "5. Never invent missing addresses or business details.\n"
        "6. If uncertain, return same_business=false.\n"
        "7. Return JSON only.\n\n"
        'FORMAT: {"same_business": true, "reason": "..."}\n\n'
        f"EXISTING: {json.dumps(existing)}\n"
        f"NEW: {json.dumps(new)}"
    )

    try:
        response = ask_json(
            prompt,
            model=config.OLLAMA_MODEL,
            host=config.OLLAMA_HOST,
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )

        return (
            isinstance(response, dict)
            and response.get("same_business") is True
        )

    except Exception as exc:
        print("BUSINESS MATCH OLLAMA FAILED:", exc)
        return False


def _same_business(existing, new):
    """Match business identities conservatively."""

    old_address = _normalize_identity_text(existing.get("address"))
    new_address = _normalize_identity_text(new.get("address"))

    old_domain = _business_domain(existing.get("url", ""))
    new_domain = _business_domain(new.get("url", ""))

    # Conflicting known addresses: never automatically merge.
    if old_address and new_address and old_address != new_address:
        return False

    # Matching verified address is strong evidence.
    if old_address and new_address and old_address == new_address:
        return True

    # Same official website is strong evidence when addresses do not conflict.
    if old_domain and new_domain and old_domain == new_domain:
        return True

    # Ask Ollama to interpret ambiguous names.
    # Do not automatically merge without independent evidence.
    if _ollama_business_match(existing, new):
        print("OLLAMA: Possible business match; needs identity evidence")

    return False


def _resolve_business(name, address, url, known_businesses):
    """Find an existing canonical business or register a new one."""

    candidate = {
        "name": name,
        "address": address,
        "url": url,
    }

    for existing in known_businesses:
        if _same_business(existing, candidate):
            # Preserve an address if the first page lacked one.
            if not existing["address"] and address:
                existing["address"] = address

            return existing

    # New business. Use a stable identifier for this research run.
    candidate["id"] = f"business_{len(known_businesses) + 1}"
    known_businesses.append(candidate)

    return candidate

def _get_flavors(name, requested_flavor=None):

    if (
        requested_flavor
        and requested_flavor.lower() in name.lower()
    ):
        return [requested_flavor.lower()]

    return []



#  BUSINESS NAME


GENERIC_BUSINESS_NAMES = {
    "menu", "our menu", "home", "home page", "official website", "order", "order online",
    "pricing", "policies", "pricing & policies", "flavors", "gallery", "desserts", "shop",
    "about", "about us", "contact", "contact us", "welcome", "ice cream", "cupcakes",
    "cookies", "bakery", "icecream flavors", "ice cream flavors",
}

ADDRESS_PATTERN = re.compile(
    r"\d{1,6}\s+[A-Za-z0-9.'\u2019&#\- ]{2,40}?,?\s*"
    r"(?:(?:Ste|Suite|Unit|#)\s*[\w-]+,?\s*)?"
    r"Cookeville,?\s*(?:TN|Tennessee)\b(?:\s*\d{5}(?:-\d{4})?)?",
    re.IGNORECASE,
)


def _clean_business_name(segment):
    name = re.split(
        r"\s+(?:is|are|in|specializing|offers?|serving)\s+|,\s*",
        segment,
        maxsplit=1,
    )[0].strip()
    if name.lower() in GENERIC_BUSINESS_NAMES:
        return None
    name = re.sub(r"\s+(?:online\s+)?(?:menu|official website|home)$", "", name,
                  flags=re.IGNORECASE).strip()
    if len(name) < 4 or len(name) > 60 or name.lower() in GENERIC_BUSINESS_NAMES:
        return None
    return name


def _get_business_name(title, url):
    segments = [
        part.strip()
        for part in re.split(r"\s+[|\u2013\u2014]\s+|\s+-\s+|:\s+", title or "")
        if part.strip()
    ]
    # Segments that mention the town are usually descriptions. Try the others first.
    ordered = (
        [s for s in segments if "cookeville" not in s.lower()]
        + [s for s in segments if "cookeville" in s.lower()]
    )
    for segment in ordered:
        name = _clean_business_name(segment)
        if name:
            return name

    host = _get_host(url)

    return host.split(".")[0].replace("-", " ").title()


def _extract_address(text):
    """A street address in Cookeville found on the page, or None. Never invented."""
    match = ADDRESS_PATTERN.search(text or "")
    if not match:
        return None
    return " ".join(match.group(0).split()).strip(" ,")



#  CREATE DESSERT RECORD


def _make_dessert(
    item,
    business,
    menu_url,
    checked_at,
    requested_flavor=None,
    address=None,
    image_url=None,
):

    name = item["name"]
    source_text = item["source_text"]

    dessert_id = "web_" + hashlib.sha256(
        f"{menu_url}|{name}|{item['price']}".encode("utf-8")
    ).hexdigest()[:12]

    record = {
        "dessert_id": dessert_id,
        "name": name,
        "business": business,
        "price": item["price"],
        "dessert_type": item.get("dessert_type") or _get_dessert_type(name),
        "flavors": _get_flavors(item.get("source_text", name), requested_flavor),
        "address": address,
        "distance_miles": None,
        "menu_url": menu_url,
        "evidence": [
            {
                "claim": (
                    f"{name} is listed on a menu image (OCR)"
                    + (f" at ${item['price']:.2f}" if item["price"] is not None else "")
                    if image_url else
                    f"{name} is listed at ${item['price']:.2f}"
                    if item["price"] is not None else
                    f"{name} is listed on the menu"
                ),
                "source_url": image_url or menu_url,
                "source_text": source_text,
                "checked_at": checked_at,
            }
        ],
        "source_type": "ocr" if image_url else "webpage",
        "verification_status": "unverified",
    }

    return validate_dessert(record)



#  LIVE SEARCH PIPELINE


def _collect_images(soup, base_url):
    """Image links on the page: {url, alt, css, width, height}. Taken before nav and footer are removed."""
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src and img.get("srcset"):
            src = img["srcset"].split(",")[0].split(" ")[0]
        src = src.strip()
        if not src or src.startswith("data:"):
            continue
        images.append({
            "url": urljoin(base_url, src),
            "alt": img.get("alt", "") or "",
            "css": " ".join(img.get("class", []) or []),
            "width": int(img["width"]) if str(img.get("width", "")).isdigit() else None,
            "height": int(img["height"]) if str(img.get("height", "")).isdigit() else None,
        })
    return images


def _browser_images(page):
    """The same image list for a browser-rendered page. Returns [] if it cannot be read."""
    try:
        return page.eval_on_selector_all(
            "img",
            "els => els.map(e => ({url: e.currentSrc || e.src, alt: e.alt || '', "
            "css: e.className || '', width: e.naturalWidth, height: e.naturalHeight}))",
        ) or []
    except Exception:
        return []


def _needs_ocr(menu_items, page):
    """OCR only when the page's own text gave too few priced items and it has images."""
    if not config.OCR_ENABLED or not page.get("images"):
        return False
    priced = [item for item in menu_items if item.get("price") is not None]
    return len(priced) < config.OCR_MIN_ITEMS


def _ocr_menu_items(page, business):
    """Items read from the page's menu images (tools/menu_ocr.py). Never raises."""
    from tools import menu_ocr

    items = []
    try:
        for image in menu_ocr.select_menu_images(page.get("images", []), config.OCR_MAX_IMAGES):
            image_url = image["url"]
            if any(part in image_url.lower() for part in (
                "nutrition-label", "nutrition_label", "nutrition-labels",
                "nutrition_facts", "nutrition-facts"
            )):
                print("OCR SKIP: nutrition label", image_url)
                continue
            print("OCR IMAGE:", image_url)
            try:
                data = menu_ocr.download_image(image_url)
                if not data:
                    print("OCR SKIP: image could not be downloaded")
                    continue
                if not menu_ocr.image_big_enough(data):
                    print("OCR SKIP: image too small to read")
                    continue
                text = menu_ocr.read_image_text(data)
                if not text.strip():
                    print("OCR: no text found in image")
                    continue
                found, method = menu_ocr.interpret_menu(text)
            except menu_ocr.OcrUnavailable as exc:
                print("OCR UNAVAILABLE:", exc)
                break
            except Exception as exc:
                print("OCR SKIP: this image failed, trying the next one:", exc)
                continue
            print(f"OCR ITEMS from {image_url}: {len(found)} (read with {method})")
            for item in found:
                items.append({
                    **item,
                    "source": "ocr",
                    "image_url": image_url,
                    "source_text": f"{item['name']} {item['price_text'] or ''}".strip(),
                })
    except Exception as exc:
        print("OCR FAILED, continuing without it:", exc)
    return items



#  SEARCH PASSES

#
# Pass 1 is the ice cream pipeline. Its queries, extraction, and rows are the same as before.
# Pass 2 covers every other category. It never keeps ice cream items and never filters by the
# request. Ranking and checking decide what fits the request.

def _category_terms(request):
    """Every non-ice-cream category, plus the requested type if it is not already listed."""
    terms = list(CATEGORY_LABELS)
    requested = canonical_type((request or {}).get("dessert_type"))
    if requested and requested != ICE_CREAM and requested not in CATEGORIES:
        terms.insert(0, requested)
    return terms


def _build_category_queries(location, request=None):
    queries = []
    for term in _category_terms(request):
        queries.append(f'"{term}" {location} menu prices')
        queries.append(f'"{location}" {term} bakery shop menu')
    return list(dict.fromkeys(queries))


def _gather_results(queries, location, seen_urls, relevance_words):
    """Run searches and return candidate pages, most menu-like first."""
    all_results = []

    for query in queries:

        print("\nSEARCH QUERY:", query)

        try:
            results = search(query, max_results=config.MAX_RESULTS)
        except Exception as exc:
            print(f"SEARCH ERROR for '{query}': {exc}")
            continue

        for result in results:

            print("TITLE:", result.get("title", ""))
            print("URL:", result.get("url", ""))
            print("SNIPPET:", result.get("snippet", ""))
            print("-" * 50)

            url = result.get("url", "").strip()

            if not url:
                continue

            if _is_unofficial(url):
                print("Skipping directory/social source:", url)
                continue

            if not _is_relevant_result(result, location):
                print("Skipping irrelevant result:", result.get("title"))
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)

            title = result.get("title", "").lower()
            url_path = urlparse(url).path.lower()

            relevance = sum(
                word in title or word in url_path
                for word in relevance_words
            )

            all_results.append((relevance, result))

    all_results.sort(key=lambda item: item[0], reverse=True)
    return all_results


def _non_ice_cream_items(page_text, extra_words):
    """Dessert items for pass 2: never ice cream, and no duplicate names with the same price."""
    items = list(_extract_with_ollama(page_text) or [])
    items += _extract_desserts(page_text, extra_words=extra_words)
    items += _extract_legacy_priced_items(page_text)

    kept, seen = [], set()
    for item in items:
        name = (item.get("name") or "").strip()
        if not name or item.get("dessert_type") == ICE_CREAM or is_ice_cream_name(name):
            continue
        key = (name.casefold(), item.get("price"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _visit_pages(all_results, request, location, checked_at, state, include_ice_cream, extra_words=()):
    """Read each candidate page and turn its items into dessert records."""
    desserts = []
    seen_urls = state["seen_urls"]
    seen_desserts = state["seen_desserts"]
    known_businesses = state["known_businesses"]

    # Visit each candidate website. Menu links found on a page are appended to this list.
    for _, result in all_results:

        url = result["url"]

        page = _fetch_page(url)

        # Retry using Playwright if the page failed
        # or contains almost no visible text.
        if (
            not page
            or len(page.get("text", "").strip()) < 150
        ):

            print(
                "Page has little content. Trying browser extraction..."
            )

            browser_page = fetch_with_browser(url)

            current_length = (
                len(page.get("text", "").strip())
                if page else 0
            )

            if (
                browser_page
                and len(browser_page.get("text", "").strip())
                > current_length
            ):
                page = browser_page

        if not page or not page.get("text", "").strip():

            print(
                "Could not read page:",
                url
            )

            continue

        print("\nREADING PAGE:", page.get("url", url))
        print("PAGE TITLE:", page.get("title", ""))
        print("PAGE TEXT LENGTH:", len(page["text"]))
        print("PAGE PREVIEW:", page["text"][:1000])

        # Reject clearly out-of-area businesses.
        if not _is_correct_location(
            page["text"],
            location
        ):

            print(
                "Skipping business outside requested location:",
                url
            )

            continue

        if include_ice_cream:
            # Pass 1: unchanged ice cream extraction.
            menu_items = _extract_with_ollama(page["text"])

            # Preserve both extraction approaches: Ollama, modern parser,
            # and the legacy priced-item parser used by the earlier agent.
            menu_items += _extract_desserts(page["text"])
            menu_items += _extract_legacy_priced_items(page["text"])
            menu_items += _extract_ice_cream_flavors(page["text"])
            # Other shops use different flavor-card headings and multiline names.
            if not any(item.get("dessert_type") == "ice cream" for item in menu_items):
                menu_items += _extract_flavor_cards(page["text"])
        else:
            # Pass 2: every other category, merged from both extractors.
            menu_items = _non_ice_cream_items(page["text"], extra_words)

        # Keep one copy of each item when extractors overlap.
        unique_items = {}
        for item in menu_items:
            key = ((item.get("name") or "").casefold().strip(), item.get("price"))
            if key[0] and key not in unique_items:
                unique_items[key] = item
        menu_items = list(unique_items.values())

        print(
            "MENU ITEMS EXTRACTED FROM THIS PAGE:",
            len(menu_items)
        )

        actual_url = page.get("url") or url

        # Queue this shop's menu, order, and dessert pages. Only pages found
        # on the main site are queued, and only one level deep.
        if page.get("links") and not result.get("follow_depth"):
            for menu_url, menu_text in _menu_links(page["links"], actual_url):
                if menu_url in seen_urls:
                    continue
                seen_urls.add(menu_url)
                all_results.append((0, {
                    "url": menu_url,
                    "title": menu_text,
                    "snippet": "",
                    "follow_depth": 1,
                }))
                print("FOLLOWING MENU LINK:", menu_url)

        raw_business_name = _get_business_name(
            page.get("title") or result.get("title", ""),
            actual_url
        )

        address = _extract_address(page["text"])

        business_record = _resolve_business(
            name=raw_business_name,
            address=address,
            url=actual_url,
            known_businesses=known_businesses,
        )

        business = business_record["name"]
        business_id = business_record["id"]
        address = business_record["address"]

        # Fallback: read menu images only when the page's own text gave too few priced items.
        '''if _needs_ocr(menu_items, page):
            menu_items += _ocr_menu_items(page, business)'''
        for item in menu_items:

            key = (
                business_id,
                item["name"].lower().strip(),
                item["price"],
            )

            if key in seen_desserts:
                continue

            seen_desserts.add(key)

            dessert = _make_dessert(
                item,
                business,
                actual_url,
                checked_at,
                request.get("flavor"),
                address=address,
                image_url=item.get("image_url"),
            )

            desserts.append(dessert)

    return desserts


def _live_search(request, attempt):
    """Research every category. The request does not narrow what is collected."""

    checked_at = datetime.now(timezone.utc).isoformat()
    location = request.get("location") or "Cookeville, Tennessee"

    state = {"seen_urls": set(), "seen_desserts": set(), "known_businesses": []}

    # Pass 1: the ice cream pipeline, unchanged.
    results = _gather_results(
        _build_queries(request, attempt), location, state["seen_urls"], MENU_WORDS,
    )
    desserts = _visit_pages(
        results, request, location, checked_at, state, include_ice_cream=True,
    )

    # Pass 2: every other category, whatever the request asked for.
    terms = _category_terms(request)
    results = _gather_results(
        _build_category_queries(location, request), location, state["seen_urls"],
        MENU_WORDS + SEARCH_WORDS,
    )
    desserts += _visit_pages(
        results, request, location, checked_at, state, include_ice_cream=False,
        extra_words=tuple(SEARCH_WORDS) + tuple(terms),
    )

    print("\nTOTAL EXTRACTED MENU ITEMS:", len(desserts))
    return desserts



#  RUN RESEARCH AGENT


def main():

    request = {
        "dessert_type": input(
            "Dessert type (optional): "
        ).strip() or None,

        "flavor": input(
            "Flavor (optional): "
        ).strip() or None,

        "max_price": None,

        "location": input(
            "Location (optional): "
        ).strip() or "Cookeville, Tennessee",

        "max_distance_miles": None,
    }

    use_live_search = input(
        "Use live web search? [y/N]: "
    ).strip().lower() in {"y", "yes"}

    original_data_source = config.DATA_SOURCE
    original_search_api_key = config.SEARCH_API_KEY

    config.DATA_SOURCE = (
        "live" if use_live_search else "mock"
    )

    try:

        if use_live_search and not config.SEARCH_API_KEY:

            config.SEARCH_API_KEY = getpass(
                "SerpApi API key (input hidden): "
            ).strip()

        records = research(request)

    except (RuntimeError, ValueError) as exc:

        print(
            f"Research failed: {exc}"
        )

        return

    finally:

        config.DATA_SOURCE = original_data_source
        config.SEARCH_API_KEY = original_search_api_key

    if not records:

        print(
            "\nNo priced dessert menu items found. "
            "Try another search or check official menus manually."
        )

        return

    print(
        f"\nFound {len(records)} dessert(s):"
    )

    for record in records:

        print(f"\nDessert: {record['name']}")
        print(f"Business: {record['business']}")
        print(f"Price: ${record['price']:.2f}" if record['price'] is not None else "Price: not confirmed")
        print(f"Menu: {record['menu_url']}")
        print(f"Status: {record['verification_status']}")
        print(f"Evidence: {record['evidence'][0]['source_text']}")


if __name__ == "__main__":
    main()
