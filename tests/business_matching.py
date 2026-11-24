from agents.research_agent import _same_business
def test_same_business_website():
    existing = {
        "name": "Cream City Ice Cream",
        "address": "119 W Broad St, Cookeville, TN",
        "url": "https://example.com/menu",
    }

    new = {
        "name": "Cream City Ice Cream & Coffee House",
        "address": "119 W Broad St, Cookeville, TN",
        "url": "https://example.com/flavors",
    }

    assert _same_business(existing, new) is True


def test_different_business_addresses():
    existing = {
        "name": "Dessert Shop",
        "address": "100 Main St, Cookeville, TN",
        "url": "https://example.com/location-one",
    }

    new = {
        "name": "Dessert Shop",
        "address": "200 Main St, Cookeville, TN",
        "url": "https://example.com/location-two",
    }

    assert _same_business(existing, new) is False