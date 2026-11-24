"""Menu images: download, OCR with Tesseract, and read items from the text.

Used only as a fallback by the research agent, when a page's own text gives too few
priced items. Nothing here invents menu items or prices:

- Ollama proposes items, and each item must appear in the OCR text. Its name words must
  be in the text, and its price must be printed in the text. Anything else is dropped.
- If Ollama is off or fails, a plain-text parser reads the OCR lines instead.
- A missing Tesseract install raises OcrUnavailable. The caller logs it and carries on.
"""

import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

import certifi

import config

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 5_000_000
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff")
SKIP_IMAGE_WORDS = ("logo", "icon", "sprite", "avatar", "favicon", "pixel", "spacer", "badge", "social")
MENU_IMAGE_WORDS = ("menu", "price", "dessert", "donut", "bakery", "pastr", "cake", "cookie")

# Lines that are section titles, not items.
HEADING_LINES = {
    "donut list", "donut holes", "donut menu", "pastries and specials", "raisin bars",
    "biscuits", "menu", "our menu", "desserts", "specials",
}
DESSERT_WORDS = (
    "donut", "twist", "glaze", "cake", "filled", "muffin", "horn", "roll", "brownie",
    "chess", "squares", "long john", "fritter", "turnover", "ear", "lady", "cookie",
    "cupcake", "pie", "cheesecake", "macaron", "pastry", "danish", "bar", "cinnamon",
    "sprinkle", "frosted",
)
PRICE_ANYWHERE = re.compile(r"\$\s*(\d{1,3}(?:\.\d{2})?)")
PRICE_FIRST = re.compile(r"\$\s*(\d{1,3}\.\d{2})\s+([A-Za-z][A-Za-z'’&\- ]{2,40}?)\s*(?:\||$)")
NAME_THEN_PRICE = re.compile(r"^([A-Za-z][A-Za-z'’&()/\- ]{2,60}?)\s*[-–—:|]*\s*\$?\s*(\d{1,3}\.\d{2})\s*$")


class OcrUnavailable(Exception):
    """Tesseract is not installed or cannot be started."""


# ---- images -----------------------------------------------------------------

def select_menu_images(images: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Pick the images most likely to be menus. Logos and icons are skipped."""
    scored = []
    for image in images or []:
        url = (image.get("url") or "").strip()
        if not url or url.lower().endswith((".svg", ".gif", ".ico")):
            continue
        text = f"{url} {image.get('alt', '')} {image.get('css', '')}".lower()
        if any(word in text for word in SKIP_IMAGE_WORDS):
            continue
        width = image.get("width") or 0
        height = image.get("height") or 0
        if width and height and (width < 200 or height < 200):
            continue
        score = sum(word in text for word in MENU_IMAGE_WORDS) * 2 + (1 if width >= 400 else 0)
        scored.append((score, url, image))
    scored.sort(key=lambda item: item[0], reverse=True)
    seen, chosen = set(), []
    for _, url, image in scored:
        if url in seen:
            continue
        seen.add(url)
        chosen.append(image)
        if len(chosen) >= limit:
            break
    return chosen


def _encode_url(url: str) -> str:
    """Escape spaces and other characters in a URL path or query, for example "Screen Shot.png"."""
    parts = urllib.parse.urlsplit(url.strip())
    path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parts.query, safe="=&%+:/?,;@!$'()*-._~")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def download_image(url: str) -> Optional[bytes]:
    """Image bytes, or None if the download fails or is not an image. Never raises."""
    try:
        url = _encode_url(url)
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            return None
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
            "Accept": "image/*",
        })
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if not content_type.startswith(IMAGE_TYPES):
                logger.info("Not an image (%s): %s", content_type, url)
                return None
            data = response.read(MAX_IMAGE_BYTES + 1)
    except Exception as exc:  # bad URLs, timeouts, and HTTP errors all mean "no image"
        logger.info("Could not download image %s: %s", url, exc)
        return None
    if len(data) > MAX_IMAGE_BYTES:
        return None
    return data


def image_big_enough(data: bytes) -> bool:
    try:
        from PIL import Image
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
    except Exception:
        return False
    return min(width, height) >= config.OCR_MIN_IMAGE_PIXELS


# ---- Tesseract ----------------------------------------------------------------

def read_image_text(data: bytes) -> str:
    """OCR text for one image, using the same preprocessing as test_tesseract_ocr.py.

    Raises OcrUnavailable if Tesseract is not installed. Returns "" if OCR itself fails.
    """
    try:
        return _run_tesseract(data)
    except OcrUnavailable:
        raise
    except Exception as exc:
        logger.warning("OCR failed: %s", exc)
        return ""


def _run_tesseract(data: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError as exc:
        raise OcrUnavailable(f"Install pytesseract and pillow: {exc}") from exc

    if config.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailable(
            "Tesseract is not installed or not on PATH. See the OCR setup steps, "
            "or set SWEETERY_TESSERACT_CMD in .env."
        ) from exc

    image = Image.open(BytesIO(data)).convert("L")
    image = ImageEnhance.Contrast(image).enhance(1.5)
    image = image.filter(ImageFilter.SHARPEN)
    return pytesseract.image_to_string(image, lang="eng", config="--psm 3")


# ---- reading items from text ----------------------------------------------------

def _clean(text: str) -> str:
    return re.sub(r"[^a-z0-9.$ ]+", " ", text.lower().replace("’", "'")).strip()


NON_ITEM_START = ("choose", "add ", "select", "your choice", "any ", "serving", "size", "price",
                  "order", "sign up", "subscribe", "view", "learn more", "click", "call ", "visit ")
NON_ITEM_WORDS = ("serving size", "per serving", "for a ", " or make it", "milkshake or float", "click here")


def is_non_item_text(name: str) -> bool:
    """True for text that describes or instructs rather than naming a menu item."""
    lowered = " ".join(name.lower().split())
    return lowered.startswith(NON_ITEM_START) or any(word in lowered for word in NON_ITEM_WORDS)


def _is_item_name(name: str) -> bool:
    lowered = name.lower().strip()
    if len(lowered) < 4 or len(lowered) > 60:
        return False
    if lowered in HEADING_LINES or "doz" in lowered or "dozen" in lowered:
        return False
    if is_non_item_text(lowered) or len(lowered.split()) > 6:
        return False
    return True


COLUMN_BREAK = re.compile(
    r"(?i)\b(donut holes|biscuits|raisin bars|pastries and specials|donut list|sausage|ham|"
    r"tenderloin|bacon|half doz|per doz|dozen)\b|\$"
)


def _clean_name_only(line: str) -> str:
    """Item name from a line with no price. OCR merges menu columns and adds noise, so:
    cut at other columns' headings and at the first number, drop {notes} and symbols."""
    text = re.sub(r"\{[^}]*\}?", " ", line)
    text = COLUMN_BREAK.split(text, maxsplit=1)[0]
    words = []
    for word in text.split():
        if any(ch.isdigit() for ch in word):
            break
        words.append(word)
    text = " ".join(words)
    text = re.sub(r"[^A-Za-z’'.&()/\- ]", " ", text)
    tokens = text.split()
    while tokens and len(tokens[-1].strip("-.’'")) <= 2:
        tokens.pop()
    return " ".join(tokens).strip(" -–—.:")


def _add_name_only(items: List[Dict[str, Any]], name: str) -> None:
    if _is_item_name(name) and "menu" not in name.lower() and any(
        word in name.lower() for word in DESSERT_WORDS
    ):
        items.append({"name": name, "price": None, "price_text": None})


def parse_menu_lines(text: str) -> List[Dict[str, Any]]:
    """Plain-text reading of OCR output. Handles "$2.50 Name", "Name 2.50", and names with no price.

    A line can hold a left-column name and a right-column priced item, for example
    "Donut Sticks- $2.50 Cranberry Muffin". The left name is kept without a price.
    """
    items: List[Dict[str, Any]] = []
    for raw in text.splitlines():
        line = " ".join(raw.split()).strip(" -–—•|")
        if not line:
            continue
        priced = []
        for price_text, name in PRICE_FIRST.findall(line):
            name = name.strip(" -–—|")
            if _is_item_name(name):
                priced.append({"name": name, "price": float(price_text), "price_text": f"${price_text}"})
        match = None if priced else NAME_THEN_PRICE.match(line)
        if match:
            name = re.sub(r"\s*(?:price|cost)\s*:?\s*$", "", match.group(1), flags=re.I).strip(" -–—:|")
            if _is_item_name(name):
                priced.append({"name": name, "price": float(match.group(2)),
                               "price_text": f"${match.group(2)}"})
        items.extend(priced)

        if priced or match:
            # A name in a left column may sit before the first price on the same line.
            if "$" in line:
                _add_name_only(items, _clean_name_only(line[:line.index("$")]))
            continue

        if "$" in line:
            _add_name_only(items, _clean_name_only(line[:line.index("$")]))
            continue
        _add_name_only(items, _clean_name_only(line))
    return _dedupe(items)


def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for item in items:
        key = (item["name"].lower(), item["price"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def validate_items(items: List[Dict[str, Any]], ocr_text: str) -> List[Dict[str, Any]]:
    """Keep only items the OCR text actually supports."""
    text = _clean(ocr_text)
    numbers = set(re.findall(r"\d{1,3}\.\d{2}", ocr_text))
    kept = []
    for item in items:
        name = str(item.get("name") or "").strip()
        if not _is_item_name(name):
            continue
        words = [w for w in _clean(name).split() if len(w) >= 3]
        if not words:
            continue
        present = sum(1 for w in words if w in text)
        if present / len(words) < 0.7:
            logger.info("Dropped OCR item not found in text: %s", name)
            continue
        price = item.get("price")
        if price is not None:
            printed = f"{float(price):.2f}"
            if printed not in numbers:
                logger.info("Dropped OCR item with a price not printed in the text: %s %s", name, price)
                continue
        kept.append({"name": name, "price": float(price) if price is not None else None,
                     "price_text": item.get("price_text")})
    return _dedupe(kept)


def _ollama_items(ocr_text: str, ask: Callable[..., Any]) -> List[Dict[str, Any]]:
    '''
    prompt = (
        "The text below is OCR output from a dessert menu photo. OCR can garble letters.\n"
        "List each dessert item that has a name on the menu. For each item give:\n"
        "- name: the item name as printed (fix only an obvious OCR letter error)\n"
        "- price: the number printed next to that item, or null if none is printed\n"
        "Rules: use only names and prices that appear in the text. Do not guess or add items. "
        "Section headings are not items.\n"
        'Return only JSON: {"items": [{"name": "...", "price": 2.5}]}\n\n'
        f"OCR TEXT:\n{ocr_text[:config.OLLAMA_PAGE_CHARS]}"
    )
    '''
    prompt = (
    "You are a dessert menu extraction agent.\n"
    "The following text comes from a website or OCR menu image.\n\n"

    "RULES:\n"
    "1. Extract only actual dessert items.\n"
    "2. Preserve the dessert names shown in the source.\n"
    "3. Extract the price associated with each dessert.\n"
    "4. If no price is available, return null.\n"
    "5. Never invent desserts, prices, or flavors.\n"
    "6. Ignore navigation, advertisements, and headings.\n"
    "7. Do not confuse individual prices with dozen prices.\n"
    "8. Do not treat ingredients as separate products.\n"
    "9. Ignore non-dessert items.\n"
    "10. Return only JSON.\n\n"

    'JSON FORMAT:\n'
    '{"items": [{"name": "Chocolate Donut", "price": 2.50}]}\n\n'

    f"MENU TEXT:\n{ocr_text[:config.OLLAMA_PAGE_CHARS]}"
)
    response = ask(prompt, model=config.OLLAMA_MODEL, host=config.OLLAMA_HOST,
                   timeout=config.OLLAMA_TIMEOUT_SECONDS)
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        return []
    items = []
    for item in response["items"]:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            price = item.get("price")
            if isinstance(price, str):
                try:
                    price = float(price.replace("$", "").strip())
                except ValueError:
                    price = None
            if isinstance(price, bool) or (price is not None and not isinstance(price, (int, float))):
                price = None
            items.append({"name": item["name"], "price": price,
                          "price_text": f"${price:.2f}" if price is not None else None})
    return items


def interpret_menu(ocr_text: str, ask: Optional[Callable[..., Any]] = None) -> Tuple[List[Dict[str, Any]], str]:
    """Items from OCR text, and how they were read: "ollama" or "rules". Items are always validated."""
    if config.OCR_OLLAMA and config.OLLAMA_MODEL:
        try:
            if ask is None:
                from tools.ollama_client import ask_json as ask
            items = validate_items(_ollama_items(ocr_text, ask), ocr_text)
            if items:
                return items, "ollama"
        except Exception as exc:
            logger.info("Ollama could not read the menu text; using rules: %s", exc)
    return validate_items(parse_menu_lines(ocr_text), ocr_text), "rules"
