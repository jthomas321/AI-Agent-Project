"""Shared web-search wrapper. Owner: Person 1.

Only the research agent should call this. Search runs on SearXNG, a free search server
you run on your own computer (config.SEARXNG_URL). No API key is needed.

SearXNG must allow JSON output. In its settings.yml, under search: formats, include "json".
"""

import json
import urllib.error
import urllib.parse
import urllib.request

import config


class SearchUnavailable(Exception):
    """SearXNG cannot be reached or did not return usable results."""


def search(query, max_results=5):
    """Return a list of {"title", "url", "snippet"} dicts, at most max_results long."""
    params = urllib.parse.urlencode({"q": query, "format": "json"})
    url = config.SEARXNG_URL.rstrip("/") + "/search?" + params
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SearchUnavailable(
            f"SearXNG returned HTTP {exc.code}. Check that JSON output is enabled in settings.yml."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SearchUnavailable(f"Cannot reach SearXNG at {config.SEARXNG_URL}: {exc}") from exc
    except ValueError as exc:
        raise SearchUnavailable("SearXNG did not return JSON. Enable json in settings.yml.") from exc

    results = []
    for item in data.get("results", []):
        title = (item.get("title") or "").strip()
        page_url = (item.get("url") or "").strip()
        if not title or not page_url:
            continue
        results.append({"title": title, "url": page_url, "snippet": item.get("content") or ""})
        if len(results) >= max_results:
            break
    return results


def check_available():
    """True if SearXNG answers. Used by the app to show a clear message before a search."""
    try:
        search("test", max_results=1)
        return True
    except SearchUnavailable:
        return False
