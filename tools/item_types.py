"""Item-level dessert type helpers for screening, pricing, and checking.

Kept separate from tools/dessert_types.py so research's imports stay unchanged.
"""

import re

TYPE_WORDS = {
    "cake": "cake", "cakes": "cake", "cake pop": "cake", "cake pops": "cake",
    "cupcake": "cupcake", "cupcakes": "cupcake",
    "muffin": "muffin", "muffins": "muffin",
    "cookie": "cookie", "cookies": "cookie",
    "brownie": "brownie", "brownies": "brownie", "blondie": "brownie",
    "donut": "donut", "donuts": "donut", "doughnut": "donut",
    "pie": "pie", "pies": "pie",
    "cheesecake": "cheesecake", "cheesecakes": "cheesecake",
    "scone": "pastry", "scones": "pastry", "croissant": "pastry",
    "tart": "pastry", "tarts": "pastry", "pastry": "pastry",
    "ice cream": "ice cream", "cone": "ice cream", "float": "ice cream", "floats": "ice cream",
    "scoop": "ice cream", "sherbet": "ice cream", "sorbet": "ice cream", "gelato": "ice cream",
    "sundae": "sundae", "sundaes": "sundae",
    "milkshake": "milkshake", "milkshakes": "milkshake", "shake": "milkshake",
}
_TYPE_RE = re.compile(
    r"(?<!\w)(" + "|".join(sorted(map(re.escape, TYPE_WORDS), key=len, reverse=True)) + r")(?!\w)"
)
BAKED_ONLY = {"cupcake", "donut", "muffin", "pastry", "scone", "croissant"}
ICE_CREAM_FORMS = {"ice cream", "sundae", "milkshake"}
# Checked in order against the business name with non-letters removed.
BUSINESS_HINTS = (
    (("cheesecake",), "cheesecake"),
    (("cakery", "cake"), "cake"),
    (("creamery", "cream", "icecream", "gelato", "custard"), "ice cream"),
)


def _norm(text):
    text = (text or "").casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def head_type(text):
    """Type of the last dessert word: 'Cookie Cake' -> cake."""
    matches = list(_TYPE_RE.finditer(_norm(text)))
    return TYPE_WORDS[matches[-1].group(1)] if matches else None


def business_type(business_name):
    collapsed = re.sub(r"[^a-z]", "", (business_name or "").casefold())
    for hints, dtype in BUSINESS_HINTS:
        if any(h in collapsed for h in hints):
            return dtype
    return None


def resolve_item_type(name, business_name):
    """Return (dessert_type or None, source)."""
    own = head_type(name)
    context = business_type(business_name)
    words = set(_norm(name).split())
    if own in ICE_CREAM_FORMS:
        return own, "item"
    if context == "ice cream" and not (words & BAKED_ONLY):
        return "ice cream", "business"
    if own:
        return own, "item"
    if context:
        return context, "business"
    return None, "unresolved"


def split_parts(name):
    """Split a line that names several desserts. Return [name] unless two or more parts are dessert words."""
    parts = [p.strip() for p in re.split(r"\s*[/,]\s*", name) if p.strip()]
    if len(parts) == 1:
        pieces = re.split(r"\s+(?:&|and)\s+", name, maxsplit=1)
        if len(pieces) == 2:
            parts = pieces
    typed = [p for p in parts if head_type(p)]
    return parts if len(typed) >= 2 else [name]