import pipeline
import config


def _setup(monkeypatch, dessert, search_request, *, empty=False):
    events = []

    # Disable external services and caching during tests.
    monkeypatch.setattr(config, "PROCESSED_CACHE_ENABLED", False)
    monkeypatch.setattr(config, "DEMO_MODE", False)
    monkeypatch.setattr(config, "REVIEW_SCORING_ENABLED", False)

    monkeypatch.setattr(pipeline, "initialize_csv", lambda: None)
    monkeypatch.setattr(
        pipeline, "hours_for_businesses", lambda records: []
    )

    def research(req, attempt=1):
        events.append("research")
        return [] if empty else [dessert()]

    def screen(records, log=None):
        events.append("screen")
        return records

    def pricing(records, log=None):
        events.append("pricing")
        return records

    def check(items, request=None):
        events.append("check")
        return [
            {
                "dessert": d,
                "check": {
                    "dessert_id": d["dessert_id"],
                    "status": "verified",
                    "verified_fields": ["name", "flavors"],
                    "flagged_fields": [],
                    "eligible_for_ranking": True,
                    "notes": ""
                }
            }
            for d in items
        ]

    def rank(req, candidates, recommendation_scores=None,
             hours_records=None):
        events.append("rank")
        return [
            {
                "rank": 1,
                "dessert": candidates[0]["dessert"],
                "check": candidates[0]["check"]
            }
        ] if candidates else []

    monkeypatch.setattr(pipeline, "research", research)
    monkeypatch.setattr(pipeline, "screen", screen)
    monkeypatch.setattr(pipeline, "estimate_missing_prices", pricing)
    monkeypatch.setattr(pipeline, "check", check)
    monkeypatch.setattr(pipeline, "rank", rank)

    return events


def test_agent_order(monkeypatch, dessert, search_request):
    events = _setup(monkeypatch, dessert, search_request)
    out = pipeline.run_pipeline(search_request)

    assert out["status"] == "ok"
    assert events == [
        "research", "screen", "pricing", "check", "rank"
    ]


def test_pipeline_preserves_evidence(
    monkeypatch, dessert, search_request
):
    _setup(monkeypatch, dessert, search_request)
    out = pipeline.run_pipeline(search_request)

    assert out["status"] == "ok"
    assert out["results"][0]["dessert"]["evidence"][0]["source_url"]


def test_no_match(monkeypatch, dessert, search_request):
    _setup(monkeypatch, dessert, search_request, empty=True)
    out = pipeline.run_pipeline(search_request)

    assert out["status"] == "no_match"
    assert out["results"] == []


def test_bad_request_is_error():
    assert pipeline.run_pipeline(
        {"max_price": -1}
    )["status"] == "error"


def test_progress_callback(monkeypatch, dessert, search_request):
    _setup(monkeypatch, dessert, search_request)
    stages = []

    pipeline.run_pipeline(
        search_request,
        on_step=lambda stage, message: stages.append(stage)
    )

    assert stages == [
        "cache",
        "research",
        "screening",
        "cache",
        "ranking"
    ]