"""Compare Sweetery dessert price models without overwriting the production model.

Run from C:\\Sweetery\\prediction_model:
    python compare_price_models.py

Required: pandas numpy scipy scikit-learn
Optional: catboost  (pip install catboost)

Uses restaurant-grouped train/validation/test splits. The validation split is used
for choosing hyperparameters; the test split is held out for final comparison.
The script only evaluates single-serving records when --single-only is passed.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import ElasticNet, Lasso, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = BASE_DIR / "data" / "sweetery_training_data.csv"
OUTPUT_DIR = BASE_DIR / "models" / "comparison"
COOKEVILLE_FILE = BASE_DIR / "data" / "sweetery_cookeville_menu_price_validation.csv"
SEED = 42


def metrics(y_true, predictions):
    predictions = np.maximum(np.asarray(predictions, dtype=float), 0.0)
    return {
        "MAE": round(float(mean_absolute_error(y_true, predictions)), 4),
        "RMSE": round(float(np.sqrt(mean_squared_error(y_true, predictions))), 4),
    }


def make_splits(data):
    # 70% training, 15% validation, 15% test by RESTAURANT, not by row.
    outer = GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=SEED)
    train_val_idx, test_idx = next(outer.split(data, groups=data["restaurant_id"]))
    train_val = data.iloc[train_val_idx].copy()
    test = data.iloc[test_idx].copy()
    inner = GroupShuffleSplit(n_splits=1, test_size=0.15 / 0.85, random_state=SEED + 1)
    train_idx, val_idx = next(inner.split(train_val, groups=train_val["restaurant_id"]))
    train = train_val.iloc[train_idx].copy()
    val = train_val.iloc[val_idx].copy()
    assert not (set(train.restaurant_id) & set(val.restaurant_id))
    assert not (set(train.restaurant_id) & set(test.restaurant_id))
    assert not (set(val.restaurant_id) & set(test.restaurant_id))
    return train, val, test


def build_text_features():
    return ColumnTransformer(
        transformers=[
            ("name_tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=12000), "name"),
            ("type", OneHotEncoder(handle_unknown="ignore"), ["dessert_type"]),
            ("serving", OneHotEncoder(handle_unknown="ignore"), ["serving_type"]),
        ],
        sparse_threshold=0.3,
    )


def prepare_data(path, single_only):
    data = pd.read_csv(path)
    needed = {"restaurant_id", "name", "dessert_type", "price"}
    missing = needed - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    if "serving_type" not in data:
        data["serving_type"] = "unspecified"
    data["price"] = pd.to_numeric(data["price"], errors="coerce")
    data = data[data["price"].between(1.0, 50.0, inclusive="both")].copy()
    data = data.dropna(subset=["restaurant_id", "name", "dessert_type"])
    for col in ["restaurant_id", "name", "dessert_type", "serving_type"]:
        data[col] = data[col].fillna("unspecified").astype(str).str.lower().str.strip()
    if single_only:
        data = data[data["serving_type"] == "single"].copy()
    data = data.drop_duplicates(subset=["restaurant_id", "name", "dessert_type", "serving_type", "price"])
    if len(data) < 100 or data["restaurant_id"].nunique() < 15:
        raise ValueError("Not enough rows or distinct restaurants for a reliable grouped split.")
    return data.reset_index(drop=True)



def load_cookeville(path, single_only):
    """External local evaluation; never included in model fitting."""
    if not path.exists():
        print(f"Cookeville evaluation skipped: file not found: {path}")
        return None
    local = pd.read_csv(path)
    required = {"restaurant", "name", "dessert_type", "serving_type", "price"}
    missing = required - set(local.columns)
    if missing:
        raise ValueError(f"Cookeville file missing columns: {sorted(missing)}")
    local["price"] = pd.to_numeric(local["price"], errors="coerce")
    local = local[local["price"].notna() & (local["price"] > 0)].copy()
    if "price_status" in local:
        local = local[~local["price_status"].isin(["starting_unit_price"])].copy()
    local = local[~local["name"].astype(str).str.contains("per oz", case=False, na=False)].copy()
    if single_only:
        local = local[local["serving_type"].astype(str).str.lower().str.strip() == "single"].copy()
    for col in ["name", "dessert_type", "serving_type"]:
        local[col] = local[col].fillna("unspecified").astype(str).str.lower().str.strip()
    return local.reset_index(drop=True)


def fit_linear(name, estimator, X_train, y_train, X_val, y_val, X_test, y_test):
    start = time.perf_counter()
    estimator.fit(X_train, y_train)
    val_pred = np.maximum(estimator.predict(X_val), 0)
    test_pred = np.maximum(estimator.predict(X_test), 0)
    return {
        "model": name,
        "validation": metrics(y_val, val_pred),
        "test": metrics(y_test, test_pred),
        "predictions": test_pred,
        "seconds": round(time.perf_counter() - start, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Compare dessert price prediction models")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--single-only", action="store_true", help="Train and evaluate only explicitly single-serving items")
    parser.add_argument("--tree-train-limit", type=int, default=30000, help="Max training rows for slower tree models")
    parser.add_argument("--svd-components", type=int, default=60)
    parser.add_argument("--cookeville", type=Path, default=COOKEVILLE_FILE, help="Existing Cookeville price validation CSV")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading:", args.data)
    data = prepare_data(args.data, args.single_only)
    train, val, test = make_splits(data)
    local = load_cookeville(args.cookeville, args.single_only)
    local_cols = ["name", "dessert_type", "serving_type"]
    local_X = local[local_cols] if local is not None and len(local) else None
    local_rows = []
    local_preds = local.copy() if local_X is not None else None

    def record_local(name, predictions):
        if local_preds is None:
            return
        p = np.maximum(np.asarray(predictions, dtype=float), 0.0)
        local_preds[name] = p
        result = metrics(local["price"], p)
        local_rows.append({"model": name, "cookeville_MAE": result["MAE"], "cookeville_RMSE": result["RMSE"], "records": len(local)})
    print(f"Records: {len(data):,}; restaurants: {data.restaurant_id.nunique():,}")
    print(f"Train: {len(train):,} | Validation: {len(val):,} | Test: {len(test):,}")
    print("Note: The original dataset may have been cleaned using global IQR thresholds before splitting.")
    print("      For strict independent evaluation, learn cleaning thresholds from training data only.\n")

    cols = ["name", "dessert_type", "serving_type"]
    X_train = train[cols]
    X_val = val[cols]
    X_test = test[cols]
    y_train = train.price.to_numpy()
    y_val = val.price.to_numpy()
    y_test = test.price.to_numpy()
    rows = []
    pred_frame = test[["restaurant_id", "name", "dessert_type", "serving_type", "price"]].reset_index(drop=True).copy()

    def record(result):
        name = result["model"]
        print(f"{name:<24} Val MAE ${result['validation']['MAE']:.2f} | Test MAE ${result['test']['MAE']:.2f} | Test RMSE ${result['test']['RMSE']:.2f} | {result['seconds']}s", flush=True)
        rows.append({"model": name, "validation_MAE": result["validation"]["MAE"], "validation_RMSE": result["validation"]["RMSE"], "test_MAE": result["test"]["MAE"], "test_RMSE": result["test"]["RMSE"], "training_seconds": result["seconds"]})
        pred_frame[name] = result["predictions"]

    # Baseline: medians are learned ONLY from training data.
    start = time.perf_counter()
    type_medians = train.groupby("dessert_type")["price"].median()
    global_median = float(train.price.median())
    base_val = val.dessert_type.map(type_medians).fillna(global_median).to_numpy()
    base_test = test.dessert_type.map(type_medians).fillna(global_median).to_numpy()
    record({"model": "Category Median", "validation": metrics(y_val, base_val), "test": metrics(y_test, base_test), "predictions": base_test, "seconds": round(time.perf_counter() - start, 2)})
    if local_X is not None:
        record_local("Category Median", local.dessert_type.map(type_medians).fillna(global_median).to_numpy())

    # All linear models use exactly the same training-only TF-IDF vocabulary.
    print("\nBuilding TF-IDF and categorical features...", flush=True)
    feature_maker = build_text_features()
    Xt = feature_maker.fit_transform(X_train)
    Xv = feature_maker.transform(X_val)
    Xe = feature_maker.transform(X_test)
    Xlocal = feature_maker.transform(local_X) if local_X is not None else None
    print("Feature dimensions:", Xt.shape, flush=True)

    for name, model in [
        ("Ridge", Ridge(alpha=10.0, solver="lsqr")),
        ("Lasso", Lasso(alpha=0.002, max_iter=2000, selection="cyclic")),
        ("Elastic Net", ElasticNet(alpha=0.002, l1_ratio=0.5, max_iter=2000)),
    ]:
        record(fit_linear(name, model, Xt, y_train, Xv, y_val, Xe, y_test))
        if Xlocal is not None:
            record_local(name, model.predict(Xlocal))

    # Dense SVD features let tree-based models use text information without
    # attempting to allocate a huge dense 12,000-column TF-IDF matrix.
    print("\nReducing text features for tree models (SVD)...", flush=True)
    components = min(args.svd_components, Xt.shape[1] - 1, Xt.shape[0] - 1)
    if components < 2:
        raise ValueError("Too few TF-IDF features for SVD")
    svd = TruncatedSVD(n_components=components, n_iter=5, random_state=SEED)
    Tt = svd.fit_transform(Xt).astype(np.float32)
    Tv = svd.transform(Xv).astype(np.float32)
    Te = svd.transform(Xe).astype(np.float32)
    Tlocal = svd.transform(Xlocal).astype(np.float32) if Xlocal is not None else None

    # For speed, tree training can use a deterministic sample of restaurants' rows.
    rng = np.random.default_rng(SEED)
    indices = np.arange(len(Tt))
    if len(indices) > args.tree_train_limit:
        indices = np.sort(rng.choice(indices, size=args.tree_train_limit, replace=False))
    print(f"Tree training rows: {len(indices):,} (linear models used {len(train):,})", flush=True)

    tree_models = [
        ("Random Forest", RandomForestRegressor(n_estimators=120, min_samples_leaf=4, max_features=0.8, n_jobs=-1, random_state=SEED)),
        ("Hist Gradient Boosting", HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0, random_state=SEED)),
    ]
    try:
        from catboost import CatBoostRegressor
        tree_models.append(("CatBoost", CatBoostRegressor(iterations=350, depth=6, learning_rate=0.06, loss_function="RMSE", verbose=False, random_seed=SEED, thread_count=4)))
    except ImportError:
        print("CatBoost skipped (optional). Install using: pip install catboost", flush=True)

    for name, estimator in tree_models:
        record(fit_linear(name, estimator, Tt[indices], y_train[indices], Tv, y_val, Te, y_test))
        if Tlocal is not None:
            record_local(name, estimator.predict(Tlocal))

    summary = pd.DataFrame(rows).sort_values("test_MAE").reset_index(drop=True)
    run_dir = OUTPUT_DIR / ("single_only" if args.single_only else "all_servings")
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_file = run_dir / "model_comparison.csv"
    preds_file = run_dir / "test_predictions.csv"
    summary.to_csv(summary_file, index=False)
    pred_frame.to_csv(preds_file, index=False)
    meta = {
        "seed": SEED,
        "data_file": str(args.data),
        "single_only": args.single_only,
        "rows": {"total": len(data), "train": len(train), "validation": len(val), "test": len(test)},
        "restaurant_counts": {"train": int(train.restaurant_id.nunique()), "validation": int(val.restaurant_id.nunique()), "test": int(test.restaurant_id.nunique())},
        "tree_train_rows": len(indices),
        "svd_components": components,
        "notes": [
            "All test rows are from restaurants absent from training and validation.",
            "Tree models use a subsample for training by default; compare with this limitation in mind.",
            "This script uses fixed example hyperparameters, not an exhaustive tuning search.",
            "Use validation scores for model selection; test scores are for reporting, not iterative tuning.",
            "Training source may have undergone IQR trimming before split, which can bias evaluation.",
            "Predicted prices are estimates, not verified menu prices.",
            "Cookeville local results are external evaluation, not training; repeated model selection on them can overfit.",
        ],
    }
    (run_dir / "comparison_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("\n========== TEST RESULTS (LOWER IS BETTER) ==========")
    print(summary.to_string(index=False))
    print("\nFiles saved:")
    print(summary_file)
    print(preds_file)
    print(run_dir / "comparison_metadata.json")
    if local_preds is not None:
        local_summary = pd.DataFrame(local_rows).sort_values("cookeville_MAE")
        local_summary_file = run_dir / "cookeville_model_comparison.csv"
        local_preds_file = run_dir / "cookeville_predictions.csv"
        local_summary.to_csv(local_summary_file, index=False)
        local_preds.to_csv(local_preds_file, index=False)
        print("\n========== COOKEVILLE VALIDATION (LOWER IS BETTER) ==========")
        print(f"Evaluated local records: {len(local_preds)}")
        print(local_summary.to_string(index=False))
        print("Saved:", local_summary_file)
        print("Saved:", local_preds_file)
    print("\nDo not choose or tune models repeatedly using the held-out test scores.")


if __name__ == "__main__":
    main()
