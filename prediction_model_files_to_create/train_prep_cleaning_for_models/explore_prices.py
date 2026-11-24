import pandas as pd

desserts = pd.read_csv(
    "data/sweetery_dessert_prices.csv"
)

# Find unusually expensive items
expensive = desserts[
    desserts["price"] > 50
]

print("Items over $50:", len(expensive))

print(
    expensive[
        ["name", "dessert_type", "price"]
    ].sort_values(
        "price", ascending=False
    ).head(30).to_string(index=False)
)

# Examine unclassified desserts
other = desserts[
    desserts["dessert_type"] == "other"
]

print("\nSample of other desserts:")
print(
    other[
        ["name", "category", "price"]
    ].sample(
        min(30, len(other)),
        random_state=42
    ).to_string(index=False)
)