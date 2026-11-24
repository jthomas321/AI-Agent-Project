
"""Tests for Sweetery's updated weighted ranking logic."""

from agents.ranking_agent import _sort_key


def make_entry(
    name,
    score,
    flavor_priority=1,
    reviews=100,
):
    dessert = {
        "name": name,
        "dessert_id": name,
        "dessert_type": "cake",
    }

    candidate = {
        "dessert": dessert,
        "check": {"verified_fields": ["flavors"]},
    }

    facts = {
        "dessert_id": name,
        "flavor_priority": flavor_priority,
        "total_reviews": reviews,
        "score": score,
    }

    return (score, candidate, None, facts)


def test_exact_flavor_before_combination():
    exact = make_entry(
        "Vanilla Bean", 80, flavor_priority=0
    )
    combination = make_entry(
        "Cookie Dough", 95, flavor_priority=2
    )

    assert sorted(
        [combination, exact], key=_sort_key
    )[0] is exact


def test_plain_before_combination():
    plain = make_entry(
        "Plain Ice Cream", 75, flavor_priority=1
    )
    combination = make_entry(
        "Pralines and Cream", 90, flavor_priority=2
    )

    assert sorted(
        [combination, plain], key=_sort_key
    )[0] is plain


def test_higher_weighted_score_wins():
    high = make_entry(
        "High Score", 92, flavor_priority=0
    )
    low = make_entry(
        "Low Score", 85, flavor_priority=0
    )

    assert sorted([low, high], key=_sort_key)[0] is high


def test_review_count_breaks_ties():
    more = make_entry(
        "More Reviews", 90,
        flavor_priority=0, reviews=1200
    )
    fewer = make_entry(
        "Fewer Reviews", 90,
        flavor_priority=0, reviews=100
    )

    assert sorted([fewer, more], key=_sort_key)[0] is more
