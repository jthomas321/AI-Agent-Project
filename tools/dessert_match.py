"""Dessert type matching for checking and ranking.

Uses the taxonomy in tools/dessert_types.py for keywords, labels, aliases, and
classify(). Only the parent-child rules are defined here. Research keeps using
dessert_types.py unchanged.
"""

from tools import dessert_types as base

# child -> parent. A request for a parent accepts its children, and their children.
PARENTS = {
    "muffin": "cupcake",
    "cupcake": "cake",
    "cheesecake": "cake",
}


def ancestors(key):
    """Parents of a category, nearest first."""
    out = []
    while key in PARENTS:
        key = PARENTS[key]
        out.append(key)
    return out


def qualifies(item_type, requested):
    """True when an item of item_type can satisfy a request for requested.

    An exact match or a child qualifies. A parent never satisfies a child request.
    Unknown types never match.
    """
    if not item_type or not requested:
        return False
    return item_type == requested or requested in ancestors(item_type)


def related_types(requested):
    """Every child that may stand in for a request, nearest first."""
    found, frontier = [], [requested]
    while frontier:
        parent = frontier.pop(0)
        for child, child_parent in PARENTS.items():
            if child_parent == parent and child not in found:
                found.append(child)
                frontier.append(child)
    return tuple(found)


# Same shape ranking.py uses, but built from the rules above.
DESSERT_FALLBACKS = {key: related_types(key) for key in base.CATEGORIES}

# Shared with dessert_types.py, unchanged.
CATEGORIES = base.CATEGORIES
ICE_CREAM = base.ICE_CREAM
SEARCH_WORDS = base.SEARCH_WORDS
CATEGORY_LABELS = base.CATEGORY_LABELS
canonical_type = base.canonical_type
classify = base.classify
categories_in = base.categories_in
is_ice_cream_name = base.is_ice_cream_name