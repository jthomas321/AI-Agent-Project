import json
import joblib
import numpy as np
import pandas as pd

from pathlib import Path

from sklearn.model_selection import GroupShuffleSplit
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, mean_squared_error

# ------------------------------------------
# 1. Configuration
# ------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

DATA_FILE = BASE_DIR / "data" / "sweetery_training_data.csv"
MODEL_DIR = BASE_DIR / "models"

MODEL_DIR.mkdir(parents=True, exist_ok=True)

RANDOM_STATE = 42
COVERAGE_TARGET = 0.90

# These are the features available in both
# Sweetery and the training dataset.
FEATURES = ["name", "dessert_type"]
TARGET = "price"

# ------------------------------------------
# 2. Load and prepare dataset
# ------------------------------------------

print("Loading dessert dataset...")

df = pd.read_csv(DATA_FILE)

required_columns = [
    "restaurant_id",
    "name",
    "dessert_type",
    "price"
]

missing_columns = [
    col for col in required_columns
    if col not in df.columns
]

if missing_columns:
    raise ValueError(
        f"Missing required columns: {missing_columns}"
    )

df = df.dropna(
    subset=["restaurant_id", "name", "price"]
).copy()

df["price"] = pd.to_numeric(
    df["price"], errors="coerce"
)

df = df.dropna(subset=["price"])

df = df[
    (df["price"] >=1) &
    (df["price"] <= 50)
].copy()

for col in FEATURES:
    df[col] = (
        df[col]
        .fillna("unknown")
        .astype(str)
        .str.lower()
        .str.strip()
    )

df = df[
    (df["name"] != "") &
    (df["dessert_type"] != "unknown")
].copy()

print(f"Total records: {len(df):,}")
print(
    f"Unique restaurants: "
    f"{df['restaurant_id'].nunique():,}"
)

# ------------------------------------------
# 3. Split by restaurant
# ------------------------------------------

# 70% training, approximately 15%
# calibration, and 15% testing.
# Grouping prevents the same restaurant
# appearing across splits.

splitter = GroupShuffleSplit(
    n_splits=1,
    test_size=0.30,
    random_state=RANDOM_STATE
)

train_idx, remaining_idx = next(
    splitter.split(
        df,
        groups=df["restaurant_id"]
    )
)

train = df.iloc[train_idx].copy()
remaining = df.iloc[remaining_idx].copy()

splitter2 = GroupShuffleSplit(
    n_splits=1,
    test_size=0.50,
    random_state=RANDOM_STATE
)

cal_idx, test_idx = next(
    splitter2.split(
        remaining,
        groups=remaining["restaurant_id"]
    )
)

calibration = remaining.iloc[cal_idx].copy()
test = remaining.iloc[test_idx].copy()

print("\nDataset split:")
print(f"Training: {len(train):,}")
print(f"Calibration: {len(calibration):,}")
print(f"Testing: {len(test):,}")

# ------------------------------------------
# 4. Category-based baseline
# ------------------------------------------

# Predict median price for each dessert type.
# This provides a simple comparison against ML.

type_medians = train.groupby(
    "dessert_type"
)["price"].median().to_dict()
type_minimums = train.groupby(
    "dessert_type"
)["price"].quantile(0.05).to_dict()

global_minimum = float(
    train["price"].quantile(0.05)
)
global_median = float(
    train["price"].median()
)

def baseline_predict(data):
    return np.array(
        [
            type_medians.get(
                dessert_type,
                global_median
            )
            for dessert_type in data["dessert_type"]
        ],
        dtype=float
    )

baseline_cal = baseline_predict(calibration)
baseline_test = baseline_predict(test)

# ------------------------------------------
# 5. TF-IDF + Ridge Regression
# ------------------------------------------

# TF-IDF extracts words and phrases from
# dessert names.
#
# OneHotEncoder converts dessert types into
# numerical features.
#
# Ridge Regression learns how these features
# relate to menu prices.

preprocessor = ColumnTransformer(
    transformers=[
        (
            "dessert_name",
            TfidfVectorizer(
                ngram_range=(1, 2),
                min_df=3,
                max_features=30000,
                sublinear_tf=True
            ),
            "name"
        ),
        (
            "dessert_type",
            OneHotEncoder(
                handle_unknown="ignore"
            ),
            ["dessert_type"]
        )
    ]
)

ridge_model = Pipeline([
    ("preprocessor", preprocessor),
    ("regression", Ridge(alpha=10.0))
])

print("\nTraining TF-IDF + Ridge Regression...")

ridge_model.fit(
    train[FEATURES],
    train[TARGET]
)

print("Training complete!")

ridge_cal = ridge_model.predict(
    calibration[FEATURES]
)

ridge_test = ridge_model.predict(
    test[FEATURES]
)

# ------------------------------------------
# 6. Calibrate price prediction intervals
# ------------------------------------------

# Split conformal prediction:
# calculate absolute errors on the
# calibration set, then use their quantile
# as a prediction margin.

def calibrate_margin(actual, predicted, coverage=0.90):
    errors = np.abs(
        np.asarray(actual, dtype=float) -
        np.asarray(predicted, dtype=float)
    )

    n = len(errors)

    if n == 0:
        raise ValueError(
            "Calibration dataset cannot be empty."
        )

    quantile_level = min(
        1.0,
        np.ceil((n + 1) * coverage) / n
    )

    return float(
        np.quantile(
            errors,
            quantile_level,
            method="higher"
        )
    )

baseline_margin = calibrate_margin(
    calibration[TARGET],
    baseline_cal,
    COVERAGE_TARGET
)

ridge_margin = calibrate_margin(
    calibration[TARGET],
    ridge_cal,
    COVERAGE_TARGET
)
# ------------------------------------------
# 6B. Dessert-specific calibration margins
# ------------------------------------------

# Calculate the absolute prediction error
# for every dessert in the calibration set.

# ------------------------------------------
# 6B. Dessert-specific calibration margins
# ------------------------------------------

calibration = calibration.copy()

calibration["ridge_error"] = np.abs(
    calibration["price"].to_numpy() - ridge_cal
)
category_margins = {}

for dessert_type, group in calibration.groupby("dessert_type"):

    errors = group["ridge_error"].to_numpy()
    n = len(errors)

    quantile_level = min(
        1.0,
        np.ceil((n + 1) * COVERAGE_TARGET) / n
    )

    category_margins[dessert_type] = float(
        np.quantile(
            errors,
            quantile_level,
            method="higher"
        )
    )

print("\nDessert-specific margins:")

for dessert_type, margin in sorted(category_margins.items()):
    print(f"{dessert_type}: ${margin:.2f}")
# ------------------------------------------
# 7. Evaluate both methods
# ------------------------------------------

def evaluate(name, actual, predicted, margin):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    lower = np.maximum(
        0,
        predicted - margin
    )

    upper = np.maximum(
        0,
        predicted + margin
    )

    coverage = np.mean(
        (actual >= lower) &
        (actual <= upper)
    )

    average_width = np.mean(
        upper - lower
    )

    mae = mean_absolute_error(
        actual, predicted
    )

    rmse = np.sqrt(
        mean_squared_error(
            actual, predicted
        )
    )

    print(f"\n{name}")
    print(f"MAE: ${mae:.2f}")
    print(f"RMSE: ${rmse:.2f}")
    print(f"Coverage: {coverage:.2%}")
    print(
        f"Average interval width: "
        f"${average_width:.2f}"
    )
    print(
        f"Calibrated margin: ${margin:.2f}"
    )

    return {
        "method": name,
        "mae": float(mae),
        "rmse": float(rmse),
        "coverage": float(coverage),
        "average_width": float(average_width),
        "margin": float(margin)
    }

print("\n========== MODEL COMPARISON ==========")

baseline_results = evaluate(
    "Category Baseline",
    test[TARGET],
    baseline_test,
    baseline_margin
)

ridge_results = evaluate(
    "TF-IDF + Ridge Regression",
    test[TARGET],
    ridge_test,
    ridge_margin
)
# ------------------------------------------
# Evaluate category-specific intervals
# ------------------------------------------

test_margins = test["dessert_type"].map(
    category_margins
).fillna(ridge_margin).to_numpy()

test_floors = test["dessert_type"].map(
    type_minimums
).fillna(global_minimum).to_numpy()

lower = np.maximum(
    test_floors,
    ridge_test - test_margins
)

upper = np.maximum(
    lower,
    ridge_test + test_margins
)

actual = test["price"].to_numpy()

coverage = np.mean(
    (actual >= lower) & (actual <= upper)
)

average_width = np.mean(upper - lower)

print("\n========== IMPROVED INTERVAL RESULTS ==========")
print(f"Coverage: {coverage:.2%}")
print(f"Average interval width: ${average_width:.2f}")

print("\nCoverage by dessert type:")

for dessert_type in sorted(test["dessert_type"].unique()):
    mask = test["dessert_type"].to_numpy() == dessert_type

    category_coverage = np.mean(
        (actual[mask] >= lower[mask]) &
        (actual[mask] <= upper[mask])
    )

    print(f"{dessert_type}: {category_coverage:.2%}")

# ------------------------------------------
# 8. Select preferred method
# ------------------------------------------

# Choose the method with better test
# coverage and narrower intervals.
#
# This is exploratory model selection;
# an independent final test would be
# needed for unbiased evaluation.

results = [
    baseline_results,
    ridge_results
]

eligible = [
    result for result in results
    if result["coverage"] >= COVERAGE_TARGET
]

if eligible:
    best = min(
        eligible,
        key=lambda result: (
            result["average_width"],
            result["mae"]
        )
    )
else:
    best = min(
        results,
        key=lambda result: (
            -result["coverage"],
            result["average_width"],
            result["mae"]
        )
    )

best_method = best["method"]

print("\nPreferred method:", best_method)

# ------------------------------------------
# 9. Save trained model
# ------------------------------------------

model_bundle = {
    "ridge_model": ridge_model,
    "type_medians": type_medians,
    "global_median": global_median,
    "baseline_margin": baseline_margin,
    "ridge_margin": ridge_margin,
    "preferred_method": best_method,
    "features": FEATURES,
    "coverage_target": COVERAGE_TARGET,
    "type_minimums": type_minimums,
    "global_minimum": global_minimum,
    "category_margins": category_margins,
    "location_supported": False
}

MODEL_FILE = (
    MODEL_DIR / "sweetery_price_model.joblib"
)

joblib.dump(
    model_bundle,
    MODEL_FILE
)

# Save evaluation metrics
results_file = (
    MODEL_DIR / "evaluation_results.json"
)

with open(
    results_file,
    "w",
    encoding="utf-8"
) as file:
    json.dump(
    {
        "baseline": baseline_results,
        "ridge": ridge_results,
        "improved_ridge": {
            "method": "Category-Calibrated Ridge",
            "mae": float(
                mean_absolute_error(actual, ridge_test)
            ),
            "coverage": float(coverage),
            "average_width": float(average_width),
            "category_margins": category_margins,
            "type_minimums": type_minimums
        },
        "preferred_method": best_method
    },
    file,
    indent=2
)
print("\nModel saved successfully!")
print("Model:", MODEL_FILE)
print("Evaluation:", results_file)
