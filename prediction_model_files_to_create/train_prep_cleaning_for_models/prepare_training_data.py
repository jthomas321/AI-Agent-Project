import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Load cleaned data
desserts = pd.read_csv(
    BASE_DIR / "data/sweetery_dessert_prices_v2.csv"
)

# Remove candy and unclassified items
desserts = desserts[
    ~desserts["dessert_type"].isin(["candy", "other"])
].copy()

# Exclude records flagged for review
desserts = desserts[
    desserts["price_flag"] == "normal"
].copy()

# Keep all serving types, but remove invalid prices
desserts = desserts[
    desserts["price"] > 0
].copy()

# Keep model features and target
training_data = desserts[
    [
        "restaurant_id",
        "name",
        "dessert_type",
        "serving_type",
        "price"
    ]
].copy()

# Save training dataset
training_data.to_csv(
    BASE_DIR / "data/sweetery_training_data.csv",
    index=False
)

print("Training records:", len(training_data))

print("\nDessert types:")
print(training_data["dessert_type"].value_counts())

print("\nServing types:")
print(training_data["serving_type"].value_counts())

print("\nPrice statistics:")
print(training_data["price"].describe())