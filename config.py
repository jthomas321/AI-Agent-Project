"""Configuration. Never commit secrets; read them from environment variables."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path):
    """Load KEY=VALUE lines from a local .env file. Real environment variables win.

    Dependency-free on purpose. The .env file is gitignored; see .env.example.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(BASE_DIR / ".env")

# "mock" uses MOCK_DATA_PATH below. "live" uses real search (once built).
DATA_SOURCE = os.getenv("SWEETERY_DATA_SOURCE", "mock")

# Mock dataset for the app. Pick a file in data/ with the SWEETERY_MOCK_FILE environment
# variable, or change the default below. Options:
#   test_desserts.json               (5 records, used by the committed tests)
#   cookeville_full_test.json        (58 records)
#   cookeville_real_test.json        (9 records)
#   cookeville_chocolate_ice_cream.json (10 chocolate ice creams from real Cookeville shops, no prices yet)
#   mock_ice_cream_test.json         (10 fictional chocolate ice creams)
MOCK_DATA_PATH = BASE_DIR / "data" / os.getenv(
    "SWEETERY_MOCK_FILE",
    "cookeville_data.json"
)

MAX_RESULTS = 3              # the pipeline returns at most this many options
MAX_RESEARCH_ATTEMPTS = 2    # one normal search plus one targeted re-search

# Owners of the live agents fill these in. Keep secrets out of the repo.

#OLLAMA_MODEL = os.getenv("SWE


# Ranking agent configuration

OLLAMA_TIMEOUT = 60

# The model sees at most this many candidates, taken in rule order.
# Any others are ranked after them by the rules.
MODEL_CANDIDATE_LIMIT = 25 # research agent only may change

MAX_RESULTS = 3
SEARCH_API_KEY = os.getenv("SWEETERY_SEARCH_API_KEY", "")

# Ollama ranking. Default mode is "ollama"; set SWEETERY_RANK_MODE=rules to skip the model.
RANK_MODE = os.getenv("SWEETERY_RANK_MODE", "ollama")
OLLAMA_MODEL = os.getenv("SWEETERY_OLLAMA_MODEL", "llama3.2")  # change to the model you pulled
OLLAMA_HOST = os.getenv("SWEETERY_OLLAMA_HOST", "http://localhost:11434")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("SWEETERY_OLLAMA_TIMEOUT", "180"))

# Most candidates the model sees per ranking call. Keeps prompt size fixed.
MODEL_CANDIDATE_LIMIT = int(os.getenv("SWEETERY_MODEL_CANDIDATE_LIMIT", "25"))

# Live research (agents/research_agent.py). Mock mode ignores these.
DATA_SOURCE = os.getenv("SWEETERY_DATA_SOURCE", DATA_SOURCE)  # "mock" or "live"
# How many search results to try. Every result is fetched; blocked or missing pages are skipped.
RESEARCH_MAX_RESULTS = int(os.getenv("SWEETERY_RESEARCH_MAX_RESULTS", "30"))
# Most items kept per shop. Extra items are counted in the shop summary, not listed.
RESEARCH_MAX_ITEMS_PER_SHOP = int(os.getenv("SWEETERY_MAX_ITEMS_PER_SHOP", "5"))
RESEARCH_TOWN = os.getenv("SWEETERY_RESEARCH_TOWN", "Cookeville, TN")
GEOCODER_USER_AGENT = "Sweetery-student-project (CSC 4240)"

# Free web search. SearXNG runs on your computer; see setup steps. No key needed.
SEARXNG_URL = os.getenv("SWEETERY_SEARXNG_URL", "http://localhost:8080")

# Per-shop research: find shops, then search each shop's own results.
RESEARCH_MAX_SHOPS = int(os.getenv("SWEETERY_MAX_SHOPS", "10"))
# If a shop has no online menu, read this many other sources (review, unrelated,
# and failed pages do not count). If it has a menu, only the menu is read.
RESEARCH_RESULTS_PER_SHOP = int(os.getenv("SWEETERY_RESULTS_PER_SHOP", "2"))
# How many search links to look through per shop while looking for usable pages.
RESEARCH_SEARCH_DEPTH = int(os.getenv("SWEETERY_SEARCH_DEPTH", "5"))
# Used only when no usable official menu was found in the first search.
RESEARCH_SEARCH_ESCALATE_DEPTH = int(os.getenv("SWEETERY_SEARCH_ESCALATE_DEPTH", "15"))
RESEARCH_DISCOVERY_RESULTS = int(os.getenv("SWEETERY_DISCOVERY_RESULTS", "5"))
# Used only when fewer than RESEARCH_MAX_SHOPS shops are named in the first results.
RESEARCH_DISCOVERY_ESCALATE_DEPTH = int(os.getenv("SWEETERY_DISCOVERY_ESCALATE_DEPTH", "15"))
# Run the expanded discovery search when fewer than this many unique businesses are found.
RESEARCH_EXPANDED_THRESHOLD = int(os.getenv("SWEETERY_EXPANDED_THRESHOLD", "5"))

# Flavor limits. When a flavor is requested, only matching items are kept. If at least
# RESEARCH_BROAD_SHOP_COUNT shops have that flavor, each shop is limited to
# RESEARCH_FLAVORS_BROAD items so the list stays short.
RESEARCH_BROAD_SHOP_COUNT = int(os.getenv("SWEETERY_BROAD_SHOP_COUNT", "3"))
RESEARCH_FLAVORS_BROAD = int(os.getenv("SWEETERY_FLAVORS_PER_SHOP_BROAD", "5"))

# Review, social, delivery, and listing sites. Pages from these are not downloaded.
# Reviews are handled by a separate agent later.
RESEARCH_SKIP_DOMAINS = [
    "yelp.com", "tripadvisor.com", "google.com", "facebook.com", "instagram.com",
    "tiktok.com", "reddit.com", "happycow.net", "restaurantguru.com", "superpages.com",
    "chamberofcommerce.com", "checkle.com", "sluurpy.us", "mapquest.com",
    "doordash.com", "grubhub.com", "postmates.com", "ubereats.com", "order.online",
    "wedeliverinc.com",
    "x.com", "twitter.com", "linkedin.com", "pinterest.com", "youtube.com", "threads.net",
]

# Stop reading a shop once its own menu page has been read and has the requested flavor.
# Set SWEETERY_STOP_AT_OFFICIAL_MENU=0 to keep reading all of the shop's pages.
RESEARCH_STOP_AT_OFFICIAL_MENU = os.getenv("SWEETERY_STOP_AT_OFFICIAL_MENU", "1") != "0"

# Pass 1 reads up to this many of the shop's own pages (pages on the shop's website).
# Pass 2 (other sites) runs only if pass 1 did not find the requested flavor.
RESEARCH_OFFICIAL_PAGES = int(os.getenv("SWEETERY_OFFICIAL_PAGES", "1"))
# Most own-website pages inspected when the first one has no usable menu.
RESEARCH_OFFICIAL_PAGES_MAX = int(os.getenv("SWEETERY_OFFICIAL_PAGES_MAX", "3"))

# Concurrent page downloads (conservative). Ollama calls stay one at a time.
RESEARCH_DOWNLOAD_WORKERS = int(os.getenv("SWEETERY_DOWNLOAD_WORKERS", "4"))
# Characters of page text sent to Ollama. Only menu-relevant parts are kept.
OLLAMA_PAGE_CHARS = int(os.getenv("SWEETERY_OLLAMA_PAGE_CHARS", "6000"))


# ---------------------------------------------------------------------------
# Recommendation agent: review sources and scoring (agents/recommendation_agent.py)
# Keys come from environment variables or a local .env file. Never commit real keys.
# Ollama settings above (OLLAMA_MODEL, OLLAMA_HOST, OLLAMA_TIMEOUT_SECONDS) are reused.
# ---------------------------------------------------------------------------
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
YELP_API_KEY = os.getenv("YELP_API_KEY", "")
# Which review platforms to query. A source with no key is skipped, not treated as an error.
REVIEW_SOURCES = [
    s.strip().lower()
    for s in os.getenv("SWEETERY_REVIEW_SOURCES", "google,yelp").split(",")
    if s.strip()
]
REVIEW_HTTP_TIMEOUT_SECONDS = int(os.getenv("SWEETERY_REVIEW_TIMEOUT", "10"))
# Yelp data is cached on disk for this many hours (Yelp's guidance). 0 disables disk caching.
REVIEW_CACHE_DIR = BASE_DIR / "data" / "review_cache"
REVIEW_CACHE_TTL_HOURS = float(os.getenv("SWEETERY_REVIEW_CACHE_HOURS", "24"))
# Google data is kept in memory only, never on disk, for this many minutes. 0 disables it.
GOOGLE_MEMORY_CACHE_MINUTES = float(os.getenv("SWEETERY_GOOGLE_MEMORY_CACHE_MINUTES", "60"))
# Set to 0 to skip review scoring in the pipeline (ranking then runs exactly as before).
REVIEW_SCORING_ENABLED = os.getenv("SWEETERY_REVIEW_SCORING", "1") != "0"
REVIEW_OUTPUT_PATH = BASE_DIR / "data" / "recommendation_output" / "business_scores.json"
# Most reviews sent to Ollama per business, and characters kept from each review.
REVIEW_MAX_TEXTS = int(os.getenv("SWEETERY_REVIEW_MAX_TEXTS", "15"))
REVIEW_TEXT_CHARS = int(os.getenv("SWEETERY_REVIEW_TEXT_CHARS", "600"))
# Scoring weights. They are relative and are renormalized over the components that have evidence.
WEIGHT_RATINGS = float(os.getenv("SWEETERY_WEIGHT_RATINGS", "40"))
WEIGHT_SENTIMENT = float(os.getenv("SWEETERY_WEIGHT_SENTIMENT", "30"))
WEIGHT_DESSERT_QUALITY = float(os.getenv("SWEETERY_WEIGHT_DESSERT_QUALITY", "20"))
WEIGHT_RECENCY = float(os.getenv("SWEETERY_WEIGHT_RECENCY", "10"))
# Bayesian smoothing for star ratings: a shop with few reviews is pulled toward the prior mean.
RATING_PRIOR_MEAN = float(os.getenv("SWEETERY_RATING_PRIOR_MEAN", "3.8"))
RATING_PRIOR_COUNT = float(os.getenv("SWEETERY_RATING_PRIOR_COUNT", "10"))
# A review's recency value halves after this many days.
RECENCY_HALF_LIFE_DAYS = float(os.getenv("SWEETERY_RECENCY_HALF_LIFE_DAYS", "365"))


# ---------------------------------------------------------------------------
# Ranking agent (agents/ranking_agent.py)
# Essential requirements are pass/fail and are not configurable here.
# Ranking preferences are a 0-100 weighted score. Weights are relative: they are divided by
# their sum. A component that does not apply (for example flavor when no flavor was requested)
# is left out of that sum.
# ---------------------------------------------------------------------------
RANK_WEIGHT_RATING = float(os.getenv("SWEETERY_RANK_WEIGHT_RATING", "35"))
RANK_WEIGHT_REVIEW_COUNT = float(os.getenv("SWEETERY_RANK_WEIGHT_REVIEW_COUNT", "15"))
RANK_WEIGHT_FLAVOR = float(os.getenv("SWEETERY_RANK_WEIGHT_FLAVOR", "25"))
RANK_WEIGHT_HOURS = float(os.getenv("SWEETERY_RANK_WEIGHT_HOURS", "10"))
RANK_WEIGHT_VERIFICATION = float(os.getenv("SWEETERY_RANK_WEIGHT_VERIFICATION", "15"))
# Score given to a missing value. It is never 0, so missing data is not penalized.
RANK_NEUTRAL_SCORE = float(os.getenv("SWEETERY_RANK_NEUTRAL_SCORE", "50"))
# Total reviews at which the review-count component reaches 100 (logarithmic below this).
RANK_REVIEW_COUNT_REFERENCE = float(os.getenv("SWEETERY_RANK_REVIEW_REFERENCE", "500"))
RANK_VERIFICATION_SCORES = {"verified": 100.0, "unknown": 40.0}
# Essential location requirement: the address must contain this text (lowercase).
RANK_LOCATION_TOWN = "cookeville"
# At most this many results from one shop in the top results. 0 means no limit.
RANK_MAX_PER_BUSINESS = int(os.getenv("SWEETERY_RANK_MAX_PER_BUSINESS", "1"))
# Look up business hours (Yelp) for the ranking. Needs YELP_API_KEY; without it, nothing runs.
HOURS_SCORING_ENABLED = os.getenv("SWEETERY_HOURS_SCORING", "1") != "0"

# Choices offered in the Streamlit search form. Keep these in line with the dessert data.
DESSERT_TYPE_CHOICES = ["cake", "cheesecake", "brownie", "cookie", "cupcake","ice cream", "macaron", "muffin", "pastry", "pie", "donut"]
FLAVOR_CHOICES = ["chocolate", "vanilla", "strawberry", "blueberry", "lemon", "ginger", "molasses", "apple"]


# ---- Menu images (OCR fallback, tools/menu_ocr.py) -----------------------------
# OCR runs only when a page's own text gives fewer than OCR_MIN_ITEMS priced items.
OCR_ENABLED = os.getenv("SWEETERY_OCR", "1") != "0"
OCR_OLLAMA = os.getenv("SWEETERY_OCR_OLLAMA", "1") != "0"   # let Ollama read OCR text (rules otherwise)
OCR_MIN_ITEMS = int(os.getenv("SWEETERY_OCR_MIN_ITEMS", "2"))
OCR_MAX_IMAGES = int(os.getenv("SWEETERY_OCR_MAX_IMAGES", "3"))
OCR_MIN_IMAGE_PIXELS = int(os.getenv("SWEETERY_OCR_MIN_PIXELS", "300"))
# Only needed if Tesseract is not on PATH, for example r"C:\Program Files\Tesseract-OCR\tesseract.exe".
TESSERACT_CMD = os.getenv("SWEETERY_TESSERACT_CMD", "")

MAX_RESULTS = 3
# Processed cache settings
PROCESSED_CACHE_ENABLED = True

PROCESSED_CACHE_DIR = BASE_DIR / "data" / "processed_cache"

DEMO_MODE = False

# Business ratings cache
BUSINESS_RATINGS_PATH = BASE_DIR / "data" / "business_ratings.csv"

BUSINESS_RATINGS_EXPORT_ENABLED = False