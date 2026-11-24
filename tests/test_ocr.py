from agents import research_agent as research
from tools import menu_ocr
import config

def test_ocr_fallback_when_no_items(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    assert research._needs_ocr([], {"images": [{"url": "https://example.org/menu.jpg"}]})

def test_ocr_not_needed_when_menu_is_readable(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(config, "OCR_MIN_ITEMS", 1)
    assert not research._needs_ocr([{"name": "Cake", "price": 5.0}], {"images": [{"url": "https://example.org/menu.jpg"}]})

def test_ocr_does_not_run_without_images(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    assert not research._needs_ocr([], {"images": []})

def test_ocr_rejects_unsupported_model_items():
    ocr_text = "Chocolate Cake $6.00"
    fabricated = [{"name": "Unicorn Pie", "price": 99.0}]
    assert menu_ocr.validate_items(fabricated, ocr_text) == []
