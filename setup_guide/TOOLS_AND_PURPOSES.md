# Sweetery — Tools and Their Purposes

This document explains the tools and libraries used in the Sweetery AI Dessert Concierge project. Sweetery searches for dessert options in Cookeville, Tennessee, checks evidence, and ranks up to three recommendations in a Streamlit interface.

## External tools and software

| Tool | Purpose in Sweetery | Notes |
| --- | --- | --- |
| **Python** | Runs the research, screening, checking, and ranking agents and the Streamlit app. | Main programming language. |
| **Python `venv`** | Creates an isolated environment for project dependencies. | Built into Python; `.venv` is not a separate download. |
| **Git / GitHub** | Tracks code changes and supports team collaboration. | Git is installed locally; GitHub hosts the repository. |
| **Docker Desktop** | Runs containerized services needed by the project. | Docker must be running to use a locally hosted SearXNG container. |
| **SearXNG** | Finds live web search results and official dessert-shop/menu pages. | Search service; it does not itself extract structured menu items. |
| **Ollama** | Runs a local language model for AI-assisted interpretation/reasoning where configured. | Requires the Ollama application and a downloaded model. |
| **Llama 3.2** | Local model used through Ollama. | Check the model name configured in the project. |
| **Tesseract OCR** | Recognizes text in menu images when webpage text is insufficient. | Separate executable; Python OCR wrappers do not install it. |
| **Playwright Chromium** | Loads JavaScript-rendered pages and exposes their visible text. | Downloaded with `python -m playwright install chromium`. |
| **Google Places API (New)** | Optional business details, ratings, review counts, and possibly opening hours, depending on enabled fields and implementation. | API key and Google Cloud billing configuration may be required. |
| **Yelp Fusion API** | Optional business information/reviews where endpoints and account access permit. | Availability, pricing, and endpoint access depend on Yelp's current terms. |

## Python libraries

| Library | Purpose | Installation / verification |
| --- | --- | --- |
| **`streamlit`** | Builds the web interface for search inputs, progress, and Top 3 results. | `pip install streamlit` |
| **`beautifulsoup4` (`bs4`)** | Parses downloaded HTML and extracts text, links, and images. | `pip install beautifulsoup4` |
| **`playwright`** | Controls Chromium as a fallback for dynamic webpages. | `pip install playwright` and install Chromium separately |
| **`certifi`** | Supplies trusted CA certificates for HTTPS requests. | `pip install certifi` |
| **`pytest`** | Runs automated tests for agents and the pipeline. | `pip install pytest` |
| **`requests`** | Common HTTP client for web/API requests, **if imported by your current modules**. | Check `tools/` and `requirements.txt` |
| **`python-dotenv`** | Loads `.env` configuration, **if the project uses it**. | Check `config.py` |
| **`pytesseract`** | Calls the Tesseract executable from Python, **if used by `tools/menu_ocr.py`**. | Check OCR module imports |
| **`Pillow` (`PIL`)** | Opens and processes images for OCR, **if used by the OCR module**. | Check OCR module imports |

> **Dependency note:** The first five libraries are supported by code or setup information shared for Sweetery. The final four are likely or previously discussed dependencies, but should be confirmed against the latest repository before being listed as mandatory. Install project dependencies with `python -m pip install -r requirements.txt` rather than installing each manually.

## Built-in Python modules (no separate installation)

The research agent uses standard-library modules such as `hashlib`, `re`, `ssl`, `datetime`, `urllib`, and `getpass`. Other project modules use standard libraries such as `json`, `copy`, and `logging`. These come with Python.

## How the tools fit together

```text
User enters preferences in Streamlit
                |
                v
        Python pipeline
                |
                v
   SearXNG searches the web
                |
                v
  HTML retrieval + BeautifulSoup
                |
       Dynamic page? ----> Playwright + Chromium
                |
                v
  Extract menu text and products
                |
  Image-only menu? ----> Tesseract OCR fallback
                |
                v
  Screening -> Checking -> Ranking
        (Ollama where configured)
                |
                v
     Top 3 results in Streamlit
```

 Google Places and Yelp integrations can enrich business information, ratings, and hours when credentials and permitted API access are available. Python validation and the checking agent should still distinguish confirmed facts from missing or uncertain data.


