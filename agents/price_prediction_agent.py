
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd

MODEL_FILE = (
    Path(__file__).resolve().parent.parent
    / "models"
    / "sweetery_single_price_model.joblib"
)


@lru_cache(maxsize=1)
def load_model():
    if not MODEL_FILE.is_file():
        raise FileNotFoundError(
            f"Trained Sweetery model not found: {MODEL_FILE}"
        )
    return joblib.load(MODEL_FILE)


def predict_price(name: str, dessert_type: str) -> dict:
    """Estimate the price of one dessert serving."""

    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")

    if not isinstance(dessert_type, str) or not dessert_type.strip():
        raise ValueError("dessert_type must be a non-empty string")

    saved = load_model()

    item = pd.DataFrame([{
        "name": name.strip().lower(),
        "dessert_type": dessert_type.strip().lower(),
        "serving_type": "single"
    }])

    estimate = max(
        0.0,
        float(saved["pipeline"].predict(item)[0])
    )
    #2. margin
    margin =2.50
    lower = max(0.0, estimate - margin)
    upper = estimate + margin
    return {
        "name": name,
        "dessert_type": dessert_type,
        "serving_type": "single",
        "price": round(estimate, 2),
         "price_lower": round(lower, 2),
        "price_upper": round(upper, 2),
        "price_status": "estimated",
        "verified": False,
        "source": "sweetery_single_price_model"
    }
def fallback_price() -> dict:
    """Assign a default price range to unpriced desserts."""
    return {
        "price": 10.00,
        "price_lower": 8.00,
        "price_upper": 12.00,
        "price_status": "estimated",
        "price_verified": False,
        "price_prediction_source": "fallback_price"
    }

if __name__ == "__main__":
    print(predict_price("chocolate chip cookie", "cookie"))
    print(predict_price("vanilla milkshake", "milkshake"))
