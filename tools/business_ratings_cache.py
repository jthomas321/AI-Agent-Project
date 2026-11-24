"""Centralized business ratings CSV."""

import csv
from datetime import datetime, timezone

import config


FIELDS = [
    "business_key",
    "business_name",
    "yelp_rating",
    "yelp_review_count",
    "retrieved_at",
]


def initialize_csv():
    """Create the CSV if it does not exist."""

    path = config.BUSINESS_RATINGS_PATH

    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        with path.open(
            "w", newline="", encoding="utf-8"
        ) as file:

            writer = csv.DictWriter(
                file, fieldnames=FIELDS
            )

            writer.writeheader()


def _number(value):
    """Convert a CSV value back into a number."""

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def load_business_ratings():
    """Load business records for the ranking agent."""

    initialize_csv()

    records = []

    with config.BUSINESS_RATINGS_PATH.open(
        "r", newline="", encoding="utf-8"
    ) as file:

        for row in csv.DictReader(file):

            records.append({
                "business_key": row["business_key"],
                "business_name": row["business_name"],
                "yelp_rating": _number(
                    row.get("yelp_rating")
                ),
                "yelp_review_count": _number(
                    row.get("yelp_review_count")
                ),
                "google_rating": None,
                "google_review_count": None,
                "retrieved_at": row.get("retrieved_at"),
            })

    return records