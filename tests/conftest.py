import copy
import pytest
import config
from models import normalize_request
import sys
from pathlib import Path

# Add the project root to Python's import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import copy
import pytest
import config
from models import normalize_request
@pytest.fixture(autouse=True)
def stable_unit_settings(monkeypatch):
    monkeypatch.setattr(config, "RANK_MODE", "rules")
    monkeypatch.setattr(config, "REVIEW_SCORING_ENABLED", False)
    monkeypatch.setattr(config, "HOURS_SCORING_ENABLED", False)
    monkeypatch.setattr(config, "MAX_RESEARCH_ATTEMPTS", 1)

@pytest.fixture
def search_request():
    return normalize_request({"dessert_type": "cake", "flavor": "chocolate", "max_price": 10, "location": "Cookeville, TN"})

@pytest.fixture
def dessert():
    def make(dessert_id="one", **changes):
        d = {"dessert_id": dessert_id, "name": "Chocolate cake", "business": "Sample Bakery", "price": 6.0,
             "dessert_type": "cake", "flavors": ["chocolate"], "address": "123 Main St, Cookeville, TN",
             "distance_miles": 1.0, "menu_url": "https://example.org/menu", "evidence": [{"claim": "Chocolate cake $6.00", "source_url": "https://example.org/menu", "source_text": "Chocolate cake $6.00", "checked_at": None}],
             "verification_status": "unverified", "rating": None}
        d.update(changes)
        return copy.deepcopy(d)
    return make

@pytest.fixture
def checked(dessert):
    def make(dessert_id="one", status="verified", **changes):
        d = dessert(dessert_id, **changes)
        d["verification_status"] = status
        return {"dessert": d, "check": {"dessert_id": dessert_id, "status": status,
                "verified_fields": ["name", "price", "flavors"] if status == "verified" else [],
                "flagged_fields": [], "notes": ""}}
    return make
