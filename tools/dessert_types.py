"""Shared dessert taxonomy.

One source of truth for research, ranking, checking, and screening. Adding a category here
makes research cover it, recognize it in item names, and accept its plural and alias forms.

Matching is whole-word, so "cheesecake" is not "cake" and "cupcake" is not "cake".
"""

import re

ICE_CREAM = "ice cream"

# Order matters only for classify(), which returns the first category whose keyword matches.
CATEGORIES = {
    "cheesecake": {"label": "cheesecakes", "keywords": ["cheesecake"]},
    "cupcake": {"label": "cupcakes", "keywords": ["cupcake"]},
    "cake": {"label": "cakes", "keywords": ["cake", "torte"]},
    "cookie": {"label": "cookies", "keywords": ["cookie"]},
    "macaron": {"label": "macarons", "keywords": ["macaron", "macaroon"]},
    "ice cream": {"label": "ice cream", "keywords": ["ice cream", "gelato", "sorbet"]},
    "donut": {"label": "donuts", "keywords": ["donut", "doughnut", "twist", "fritter"]},
    "brownie": {"label": "brownies", "keywords": ["brownie", "blondie"]},
    "pie": {"label": "pies", "keywords": ["pie", "tart"]},
    "pastry": {"label": "pastries", "keywords": ["pastry", "croissant", "danish"]},
    "frozen yogurt": {"label": "frozen yogurt", "keywords": ["frozen yogurt", "froyo", "yogurt"]},
    "muffin": {"label": "muffins", "keywords": ["muffin"]},
}

# Words that mark an item as ice cream. Ice cream is handled by its own pipeline.
ICE_CREAM_KEYWORDS = ("ice cream", "gelato", "sorbet", "soft serve", "frozen custard")

# Subtype hierarchy. A muffin is a kind of cake, so a cake request accepts a muffin.
# A cake is not a muffin, so a muffin request does not accept a cake.
PARENTS = {
    "cupcake": "cake",
    "cheesecake": "cake",
    "muffin": "cake",
}


def ancestors(key):
    """Parents of a category, nearest first (empty for top-level categories)."""
    out = []
    while key in PARENTS:
        key = PARENTS[key]
        out.append(key)
    return out


def qualifies(item_type, requested):
    """True when an item of type item_type can satisfy a request for requested.

    Exact matches and subtypes qualify: a muffin satisfies a cake request.
    A parent never satisfies a child request: a cake does not satisfy a muffin request.
    Unknown types are never treated as a match.
    """
    if not item_type or not requested:
        return False
    return item_type == requested or requested in ancestors(item_type)


def related_types(requested):
    """Subtypes that may stand in for a request (used by ranking after exact matches)."""
    found = []
    frontier = [requested]
    while frontier:
        parent = frontier.pop(0)
        for child, parent_of_child in PARENTS.items():
            if parent_of_child == parent and child not in found:
                found.append(child)
                frontier.append(child)
    return tuple(found)


# Kept as a name for existing imports. Derived from the hierarchy, not hand-written.
DESSERT_FALLBACKS = {key: related_types(key) for key in CATEGORIES}


def _pattern(keywords):
    alternation = "|".join(re.escape(k) for k in sorted(set(keywords), key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternation})s?(?!\w)", re.IGNORECASE)


_PATTERNS = {key: _pattern(info["keywords"]) for key, info in CATEGORIES.items()}
_ICE_CREAM_PATTERN = _pattern(ICE_CREAM_KEYWORDS)


def categories_in(name):
    """Every category whose keyword appears in the name, in the order they appear."""
    text = " ".join((name or "").split())
    hits = []
    for key, pattern in _PATTERNS.items():
        match = pattern.search(text)
        if match:
            hits.append((match.start(), key))
    return [key for _, key in sorted(hits)]


def classify(name):
    """The item's category, or None. The rightmost noun wins, so "Blueberry Cheesecake Muffin"
    is a muffin (flavor first, dessert type last)."""
    text = " ".join((name or "").split())
    best = None
    for key, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            if best is None or match.start() > best[0]:
                best = (match.start(), key)
    return best[1] if best else None


def is_ice_cream_name(name):
    text = " ".join((name or "").split())
    return bool(text) and _ICE_CREAM_PATTERN.search(text) is not None


def _build_aliases():
    table = {}
    for key, info in CATEGORIES.items():
        table[key] = key
        table[info["label"]] = key
        for keyword in info["keywords"]:
            table.setdefault(keyword, key)
    return table


ALIASES = _build_aliases()


def canonical_type(value):
    """Map a requested type to its category key. Unknown types are kept, lowercased."""
    text = " ".join(str(value or "").casefold().split())
    if not text:
        return None
    if text in ALIASES:
        return ALIASES[text]
    if text.endswith("s") and text[:-1] in ALIASES:
        return ALIASES[text[:-1]]
    return text


# Every non-ice-cream category, by its search label. Ice cream is researched by pass 1.
CATEGORY_LABELS = tuple(info["label"] for key, info in CATEGORIES.items() if key != ICE_CREAM)

# Words used to recognize dessert names and to judge search results.
SEARCH_WORDS = tuple(dict.fromkeys(
    word for info in CATEGORIES.values() for word in [info["label"], *info["keywords"]]
))
