import joblib
import pandas as pd
from pathlib import Path
from sklearn.metrics import mean_absolute_error, mean_squared_error
import numpy as np

BASE_DIR = Path(__file__).resolve().parent

MODEL_FILE = BASE_DIR / "models" / "sweetery_price_model.joblib"
DATA_FILE = BASE_DIR / "data" / "sweetery_cookeville_menu_price_validation.csv"

# Load saved model
saved = joblib.load(MODEL_FILE)

model = saved["ridge_model"]
margin = saved["ridge_margin"]

# Load Cookeville dataset
df = pd.read_csv(DATA_FILE)

print("Total records:", len(df))

# Only evaluate items with usable actual prices
df["price"] = pd.to_numeric(df["price"], errors="coerce")

df = df[
    df["price"].notna()
    & (df["price"] > 0)
].copy()

# Exclude per-unit and custom starting prices
df = df[
    ~df["price_status"].isin([
        "starting_unit_price"
    ])
].copy()

df = df[
    ~df["name"].str.contains(
        "per oz",
        case=False,
        na=False
    )
].copy()

# Keep model features
features = saved["features"]

X = df[features].copy()

for col in features:
    X[col] = (
        X[col]
        .fillna("unknown")
        .astype(str)
        .str.lower()
        .str.strip()
    )

# Predict prices
df["predicted_price"] = np.maximum(
    model.predict(X),
    0
)

# Calculate prediction intervals
df["lower_bound"] = np.maximum(
    df["predicted_price"] - margin,
    0
)

df["upper_bound"] = df["predicted_price"] + margin

# Compare predicted and actual prices
df["absolute_error"] = (
    df["price"] - df["predicted_price"]
).abs()

df["within_interval"] = (
    (df["price"] >= df["lower_bound"])
    & (df["price"] <= df["upper_bound"])
)

# Evaluate
mae = mean_absolute_error(
    df["price"],
    df["predicted_price"]
)

rmse = np.sqrt(
    mean_squared_error(
        df["price"],
        df["predicted_price"]
    )
)

coverage = df["within_interval"].mean() * 100
# Evaluate single-serving desserts only
single_df = df[
    df["serving_type"] == "single"
].copy()
# Get category median prices from saved model
type_medians = saved["type_medians"]
global_median = saved["global_median"]

# Predict prices using category medians
single_df["baseline_prediction"] = (
    single_df["dessert_type"]
    .map(type_medians)
    .fillna(global_median)
)

# Calculate baseline absolute errors
single_df["baseline_error"] = (
    single_df["price"] -
    single_df["baseline_prediction"]
).abs()

# Compare both models
if len(single_df) > 0:

    ridge_mae = mean_absolute_error(
        single_df["price"],
        single_df["predicted_price"]
    )

    baseline_mae = mean_absolute_error(
        single_df["price"],
        single_df["baseline_prediction"]
    )

    ridge_rmse = np.sqrt(
        mean_squared_error(
            single_df["price"],
            single_df["predicted_price"]
        )
    )

    baseline_rmse = np.sqrt(
        mean_squared_error(
            single_df["price"],
            single_df["baseline_prediction"]
        )
    )

    print("\n========== MODEL COMPARISON ==========")
    print("Single-serving records:", len(single_df))

    print("\nTF-IDF + Ridge Regression")
    print(f"MAE: ${ridge_mae:.2f}")
    print(f"RMSE: ${ridge_rmse:.2f}")

    print("\nCategory Median Baseline")
    print(f"MAE: ${baseline_mae:.2f}")
    print(f"RMSE: ${baseline_rmse:.2f}")

    if ridge_mae < baseline_mae:
        print("\nWinner: TF-IDF + Ridge Regression")
    elif baseline_mae < ridge_mae:
        print("\nWinner: Category Median Baseline")
    else:
        print("\nBoth models have the same MAE")
    # ========== HYBRID MODEL ==========

    # Average Ridge and Category Median predictions
    single_df["hybrid_prediction"] = (
        single_df["predicted_price"] +
        single_df["baseline_prediction"]
    ) / 2

    # Calculate hybrid errors
    single_df["hybrid_error"] = (
        single_df["price"] -
        single_df["hybrid_prediction"]
    ).abs()

    hybrid_mae = mean_absolute_error(
        single_df["price"],
        single_df["hybrid_prediction"]
    )

    hybrid_rmse = np.sqrt(
        mean_squared_error(
            single_df["price"],
            single_df["hybrid_prediction"]
        )
    )

    print("\n========== HYBRID MODEL ==========")
    print(f"MAE: ${hybrid_mae:.2f}")
    print(f"RMSE: ${hybrid_rmse:.2f}")

    # Compare all three models
    results = {
        "Ridge Regression": ridge_mae,
        "Category Median": baseline_mae,
        "Hybrid": hybrid_mae
    }

    best_model = min(results, key=results.get)

    print("\n========== FINAL MODEL COMPARISON ==========")

    for name, model_mae in results.items():
        print(f"{name}: ${model_mae:.2f} MAE")

    print(f"\nLowest MAE: {best_model}")
    print("\n========== SINGLE-SERVING VALIDATION ==========")

    if len(single_df) > 0:

        single_mae = mean_absolute_error(
            single_df["price"],
            single_df["predicted_price"]
        )

        single_rmse = np.sqrt(
            mean_squared_error(
                single_df["price"],
                single_df["predicted_price"]
            )
        )

        single_coverage = (
            single_df["within_interval"].mean() * 100
        )

        print("Evaluated records:", len(single_df))
        print(f"MAE: ${single_mae:.2f}")
        print(f"RMSE: ${single_rmse:.2f}")
        print(f"Coverage: {single_coverage:.2f}%")

    print("\n========== SINGLE-SERVING RESULTS ==========")

    print(
        single_df[
            [
                "restaurant",
                "name",
                "price",
                "predicted_price",
                "absolute_error",
                "within_interval"
            ]
        ].to_string(index=False)
    )

    # Save results
    output_file = (
        BASE_DIR / "data" / "single_serving_predictions.csv"
    )

    single_df.to_csv(output_file, index=False)

    print("\nResults saved to:", output_file)

else:
    print("No single-serving desserts found.")
print("\n========== COOKEVILLE VALIDATION ==========")
print("Evaluated records:", len(df))
print(f"MAE: ${mae:.2f}")
print(f"RMSE: ${rmse:.2f}")
print(f"Coverage: {coverage:.2f}%")
print("\n========== BASELINE BY RESTAURANT ==========")

for restaurant, group in single_df.groupby("restaurant"):
    print(f"\n{restaurant}")
    print("Items:", len(group))
    print(
        "Baseline MAE:",
        round(group["baseline_error"].mean(), 2)
    )
    print(
        "Ridge MAE:",
        round(group["absolute_error"].mean(), 2)
    )
    print(
        "Hybrid MAE:",
        round(group["hybrid_error"].mean(), 2)
    )
print("\n========== MODEL COMPARISON BY DESSERT TYPE ==========")

for dessert_type, group in single_df.groupby("dessert_type"):

    ridge_error = group["absolute_error"].mean()
    baseline_error = group["baseline_error"].mean()
    hybrid_error = group["hybrid_error"].mean()

    print(f"\nDessert Type: {dessert_type}")
    print("Items:", len(group))
    print(f"Ridge MAE: ${ridge_error:.2f}")
    print(f"Baseline MAE: ${baseline_error:.2f}")
    print(f"Hybrid MAE: ${hybrid_error:.2f}")
print("\n========== RESTAURANT RESULTS ==========")

for restaurant, group in df.groupby("restaurant"):
    restaurant_mae = group["absolute_error"].mean()

    print(f"\n{restaurant}")
    print("Items:", len(group))
    print(f"MAE: ${restaurant_mae:.2f}")

# Save predictions for review
OUTPUT_FILE = BASE_DIR / "data" / "cookeville_predictions.csv"

df.to_csv(OUTPUT_FILE, index=False)

print("\nPredictions saved to:", OUTPUT_FILE)