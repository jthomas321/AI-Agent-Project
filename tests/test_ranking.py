from agents.ranking_agent import rank
import config

def test_top_three(search_request, checked, monkeypatch):
    monkeypatch.setattr(config, "RANK_MAX_PER_BUSINESS", 0)
    out = rank(search_request, [checked(str(i)) for i in range(6)])
    assert len(out) == 3
    assert [x["rank"] for x in out] == [1, 2, 3]

def test_wrong_type_excluded(search_request, checked):
    assert rank(search_request, [checked(dessert_type="cookie")]) == []

def test_over_budget_excluded(search_request, checked):
    assert rank(search_request, [checked(price=20.0)]) == []

def test_out_of_town_excluded(search_request, checked):
    assert rank(search_request, [checked(address="123 Main St, Nashville, TN")]) == []

def test_needs_research_not_ranked(search_request, checked):
    assert rank(search_request, [checked(status="needs_research")]) == []

def test_verified_beats_unknown_when_other_factors_equal(search_request, checked, monkeypatch):
    monkeypatch.setattr(config, "RANK_MAX_PER_BUSINESS", 0)
    out = rank(search_request, [checked("unknown", status="unknown"), checked("verified")])
    assert out[0]["dessert"]["dessert_id"] == "verified"

def test_missing_ratings_and_hours_are_allowed(search_request, checked):
    out = rank(search_request, [checked()], recommendation_scores=[], hours_records=[])
    assert len(out) == 1
    assert out[0]["ratings"]["google"]["rating"] is None

def test_duplicate_ids_skipped(search_request, checked, monkeypatch):
    monkeypatch.setattr(config, "RANK_MAX_PER_BUSINESS", 0)
    out = rank(search_request, [checked("same"), checked("same")])
    assert len(out) == 1

def test_top_three_overall_regardless_of_business(search_request, checked, monkeypatch):
    monkeypatch.setattr(config, "RANK_MAX_PER_BUSINESS", 0)

    candidates = [
        checked("a", business="Sample Bakery"),
        checked("b", business="Sample Bakery"),
        checked("c", business="Other Bakery"),
        checked("d", business="Sample Bakery"),
    ]

    out = rank(search_request, candidates)

    assert len(out) == 3
    assert [result["rank"] for result in out] == [1, 2, 3]