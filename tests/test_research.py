from agents import research_agent as research
import config


def test_live_mode_calls_live_search(monkeypatch, search_request):
    seen = []

    monkeypatch.setattr(config, "DATA_SOURCE", "live")
    monkeypatch.setattr(research, "get_cached", lambda req: None)

    monkeypatch.setattr(
        research,
        "_live_search",
        lambda req, attempt: seen.append((req, attempt)) or []
    )

    assert research.research(search_request) == []
    assert seen[0][0]["location"] == "Cookeville, TN"


def test_search_queries_include_local_context(search_request):
    queries = research._build_queries(search_request, 1)

    assert queries
    assert any("cookeville" in str(q).lower() for q in queries)


def test_location_validation_rejects_wrong_city():
    assert not research._is_correct_location(
        "123 Main St, Crossville, TN",
        "Cookeville, TN"
    )

    assert not research._is_correct_location(
        "123 Main St, Rossville, TN",
        "Cookeville, TN"
    )


def test_location_validation_accepts_cookeville():
    assert research._is_correct_location(
        "123 Main St, Cookeville, TN",
        "Cookeville, TN"
    )


def test_extracts_priced_menu_items():
    items = research._extract_desserts(
        "Chocolate Cake $6.00\nVanilla Cake $7.00"
    )

    assert isinstance(items, list)
    assert any("chocolate" in str(item).lower() for item in items)


def test_evidence_schema_preserved(dessert):
    from models import validate_dessert

    d = dessert()
    assert validate_dessert(d)["evidence"][0]["source_url"]


def test_empty_live_search_is_safe(monkeypatch, search_request):
    monkeypatch.setattr(config, "DATA_SOURCE", "live")
    monkeypatch.setattr(research, "get_cached", lambda req: None)
    monkeypatch.setattr(
        research, "_live_search", lambda req, attempt: []
    )

    assert research.research(search_request) == []


def test_research_cache_hit(monkeypatch, search_request, dessert):
    monkeypatch.setattr(config, "DATA_SOURCE", "live")
    monkeypatch.setattr(
        research, "get_cached", lambda req: [dessert()]
    )

    def unexpected_live_search(*args, **kwargs):
        raise AssertionError("Live search should not run on cache hit")

    monkeypatch.setattr(
        research, "_live_search", unexpected_live_search
    )

    results = research.research(search_request)

    assert len(results) == 1
    assert results[0]["name"] == "Chocolate cake"