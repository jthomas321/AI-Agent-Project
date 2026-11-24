from pathlib import Path
import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_form_fields_present():
    at = AppTest.from_file(str(APP)).run()

    assert not at.exception

    text_labels = [s.label for s in at.text_input]

    assert "Search desserts" in text_labels
    assert len(text_labels) == 1

def test_submit_calls_live_pipeline(monkeypatch):
    from tools import web_search
    from agents import natural_lang_agent
    import pipeline
    import config

    calls = []

    monkeypatch.setattr(config, "DATA_SOURCE", "live")

    monkeypatch.setattr(
        web_search, "check_available", lambda: True
    )

    # Mock Ollama's interpretation of the search.
    def fake_understand_query(user_query):
        return {
            "request": {
                "dessert_type": "cake",
                "flavor": "chocolate",
                "max_price": 10.0,
                "max_distance_miles": None,
                "location": "Cookeville, TN"
            }
        }

    monkeypatch.setattr(
        natural_lang_agent,
        "understand_query",
        fake_understand_query
    )

    # Mock the pipeline.
    def fake_run(raw, on_step=None):
        calls.append((raw, config.DATA_SOURCE))

        return {
            "status": "no_match",
            "message": "No desserts matched",
            "results": [],
            "all_desserts": [],
            "checking_results": [],
            "log": []
        }

    monkeypatch.setattr(pipeline, "run_pipeline", fake_run)

    at = AppTest.from_file(str(APP)).run()

    # Enter a valid natural-language search.
    at.text_input[0].set_value(
        "Chocolate cake under $10 in Cookeville"
    )

    at.button[0].click().run()

    assert not at.exception
    assert len(calls) == 1
    assert calls[0][1] == "live"
    assert calls[0][0]["location"] == "Cookeville, TN"
    assert calls[0][0]["dessert_type"] == "cake"
    assert calls[0][0]["flavor"] == "chocolate"
    assert calls[0][0]["max_price"] == 10.0


def test_no_search_service_displays_error(monkeypatch):
    from tools import web_search
    import config

    monkeypatch.setattr(config, "DATA_SOURCE", "live")

    monkeypatch.setattr(
        web_search, "check_available", lambda: False
    )

    at = AppTest.from_file(str(APP)).run()

    at.text_input[0].set_value(
        "Chocolate cake in Cookeville"
    )

    at.button[0].click().run()

    assert not at.exception

    assert any(
        "Live search is not running" in e.body
        for e in at.error
    )