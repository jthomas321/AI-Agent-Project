
import pandas as pd
import re
import html
from pathlib import Path

# -----------------------------------------
# 1. File paths
# -----------------------------------------

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "restaurant-menus.csv"
OUTPUT_DIR = BASE_DIR / "data"

OUTPUT_DIR.mkdir(exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "sweetery_dessert_prices_v2.csv"

# -----------------------------------------
# 2. Dessert categories
# -----------------------------------------

dessert_types = {
    "brownie": r"\bbrownies?\b",
    "cookie": r"\bcookies?\b",
    "ice cream": r"\bice cream\b|\bgelato\b",
    "milkshake": r"\bmilkshakes?\b|\bshakes?\b",
    "cheesecake": r"\bcheesecakes?\b",
    "cake": r"\bcakes?\b|\bcupcakes?\b",
    "donut": r"\bdonuts?\b|\bdoughnuts?\b",
    "pie": r"\bpies?\b|\btarts?\b",
    "pudding": r"\bpuddings?\b",
    "frozen yogurt": r"\bfrozen yogurt\b|\bfroyo\b",
    "sundae": r"\bsundaes?\b",
    "macaron": r"\bmacarons?\b",
    "churro": r"\bchurros?\b",
    "pastry": r"\bcroissants?\b|\bdanish\b|\bpastries?\b",
    "banana split": r"\bbanana splits?\b",
    "candy": r"\bcand(y|ies)\b|\bchocolate bars?\b"
}

# -----------------------------------------
# 3. Exclude non-dessert items
# -----------------------------------------

non_dessert_patterns = [
    r"\bcrab cakes?\b",
    r"\bfish cakes?\b",
    r"\bpizza\b",
    r"\bsandwich(es)?\b",
    r"\bburger(s)?\b",
    r"\bice cream maker\b",
    r"\bice cream truck\b",
    r"\bknife\b",
    r"\btoy\b",
    r"\bprotein shakes?\b",
    r"\bshake seasoning\b",
    r"\bbread rolls?\b",
    r"\bchicken\b",
    r"\bshrimp\b",
    r"\bsteak\b"
]

def is_non_dessert(name):
    name = str(name).lower()

    return any(
        re.search(pattern, name)
        for pattern in non_dessert_patterns
    )

# -----------------------------------------
# 4. Classify dessert type
# -----------------------------------------

def classify_dessert(name, category):
    name = str(name).lower()
    category = str(category).lower()

    # Prioritize specific dessert types
    priority = [
        "cheesecake",
        "brownie",
        "cookie",
        "milkshake",
        "ice cream",
        "frozen yogurt",
        "donut",
        "sundae",
        "macaron",
        "churro",
        "pudding",
        "banana split",
        "pastry",
        "pie",
        "cake",
        "candy"
    ]

    # First check name
    for dessert_type in priority:
        if re.search(dessert_types[dessert_type], name):
            return dessert_type

    # Then check category
    for dessert_type in priority:
        if re.search(dessert_types[dessert_type], category):
            return dessert_type

    return "other"

# -----------------------------------------
# 5. Classify serving type
# -----------------------------------------

def classify_serving(name, description):
    text = (
        str(name) + " " + str(description)
    ).lower()

    bulk_patterns = [
        r"\bdozen\b",
        r"\b\d+\s*count\b",
        r"\b\d+\s*pack\b",
        r"\b\d+\s*pk\b",
        r"\bparty box\b",
        r"\bcatering\b",
        r"\btower of \d+\b",
        r"\bbox of \d+\b",
        r"\b\d+\s*dozen\b",
        r"\b\d+\s*cupcakes?\b",
        r"\b\d+\s*cookies?\b"
    ]

    packaged_patterns = [
        r"\bpint\b",
        r"\bquart\b",
        r"\b\d+\s*oz\b",
        r"\b\d+\s*fl oz\b",
        r"\bcontainer\b"
    ]

    single_patterns = [
        r"\bslice\b",
        r"\bsingle\b",
        r"\bpiece\b",
        r"\bscoop\b"
    ]

    for pattern in bulk_patterns:
        if re.search(pattern, text):
            return "bulk"

    for pattern in packaged_patterns:
        if re.search(pattern, text):
            return "packaged"

    for pattern in single_patterns:
        if re.search(pattern, text):
            return "single"

    return "unspecified"

# -----------------------------------------
# 6. Clean the dataset in chunks
# -----------------------------------------

dessert_chunks = []

# Match dessert names or categories
dessert_pattern = "|".join(dessert_types.values())

total_rows = 0

for chunk in pd.read_csv(
    INPUT_FILE,
    chunksize=100000
):

    total_rows += len(chunk)

    # Clean text columns
    for col in ["name", "category", "description"]:
        chunk[col] = (
            chunk[col]
            .fillna("")
            .astype(str)
            .map(html.unescape)
            .str.strip()
        )

    # Filter non-desserts
    chunk = chunk[
        ~chunk["name"].apply(is_non_dessert)
    ].copy()

    # Find dessert-related records
    search_text = (
        chunk["name"] + " " + chunk["category"]
    )

    chunk = chunk[
        search_text.str.contains(
            dessert_pattern,
            case=False,
            regex=True,
            na=False
        )
    ].copy()

    # Convert prices to numeric
    chunk["price"] = pd.to_numeric(
        chunk["price"]
        .astype(str)
        .str.replace(
            r"\s*USD\s*$", "", regex=True
        )
        .str.replace("$", "", regex=False)
        .str.strip(),
        errors="coerce"
    )

    # Remove invalid prices
    chunk = chunk.dropna(subset=["price"])
    chunk = chunk[chunk["price"] > 0]

    # Remove empty names
    chunk = chunk[chunk["name"] != ""]

    # Classify dessert type
    chunk["dessert_type"] = chunk.apply(
        lambda row: classify_dessert(
            row["name"],
            row["category"]
        ),
        axis=1
    )

    # Classify serving type
    chunk["serving_type"] = chunk.apply(
        lambda row: classify_serving(
            row["name"],
            row["description"]
        ),
        axis=1
    )

    # Flag expensive items for investigation
    chunk["price_flag"] = chunk["price"].apply(
        lambda price: "review" if price > 50
        else "normal"
    )

    dessert_chunks.append(chunk)

    print(f"Processed {total_rows:,} rows")

# -----------------------------------------
# 7. Combine cleaned records
# -----------------------------------------

desserts = pd.concat(
    dessert_chunks,
    ignore_index=True
)

# Remove duplicate records
desserts = desserts.drop_duplicates(
    subset=["restaurant_id", "name", "price"]
)

# Keep relevant columns
desserts = desserts[
    [
        "restaurant_id",
        "name",
        "dessert_type",
        "serving_type",
        "category",
        "description",
        "price",
        "price_flag"
    ]
]
# -----------------------------------------
# Remove price outliers by dessert type
# -----------------------------------------

def remove_outliers(group):
    Q1 = group["price"].quantile(0.25)
    Q3 = group["price"].quantile(0.75)

    IQR = Q3 - Q1

    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR

    return group[
        (group["price"] >= lower_bound) &
        (group["price"] <= upper_bound)
    ]

before = len(desserts)

desserts = pd.concat(
    [
        remove_outliers(group)
        for _, group in desserts.groupby(["dessert_type", "serving_type"])
    ],
    ignore_index=True
)

print("\nOutliers removed:", before - len(desserts))
# -----------------------------------------
# 8. Save cleaned dataset
# -----------------------------------------

desserts.to_csv(
    OUTPUT_FILE,
    index=False
)

# -----------------------------------------
# 9. Display results
# -----------------------------------------

print("\nCleaning complete!")

print("\nOriginal rows processed:")
print(total_rows)

print("\nCleaned dessert records:")
print(len(desserts))

print("\nDessert categories:")
print(desserts["dessert_type"].value_counts())

print("\nServing types:")
print(desserts["serving_type"].value_counts())

print("\nFlagged expensive items:")
print(desserts["price_flag"].value_counts())

print("\nPrice statistics:")
print(
    desserts.groupby("dessert_type")["price"].agg(
        ["count", "min", "max", "mean", "median", "std"]
    )
)

print("\nSaved cleaned dataset to:")
print(OUTPUT_FILE)
