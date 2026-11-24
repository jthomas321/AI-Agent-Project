from agents import screening_agent as screening


def test_valid_dessert_kept(dessert):
    out = screening.screen([dessert()])
    assert len(out) == 1


def test_missing_price_kept(dessert):
    out = screening.screen([dessert(price=None)])
    assert len(out) == 1
    assert out[0]["price"] is None


def test_different_type_kept(dessert):
    out = screening.screen([
        dessert(name="Chocolate Cookie", dessert_type="cookie")
    ])
    assert len(out) == 1


def test_different_flavor_kept(dessert):
    out = screening.screen([
        dessert(name="Vanilla Cake", flavors=["vanilla"])
    ])
    assert len(out) == 1


def test_over_budget_kept(dessert):
    out = screening.screen([dessert(price=15.0)])
    assert len(out) == 1


def test_navigation_text_rejected(dessert):
    assert screening.screen([
        dessert(name="Order Online")
    ]) == []


def test_empty_input():
    assert screening.screen([]) == []