# Sweetery Single-Serving Price Prediction Model

## Overview

The Sweetery Single-Serving Price Prediction Model uses **TF-IDF and Ridge Regression** to estimate the prices of individual desserts when verified menu prices are unavailable.

The model is trained on restaurant menu data and focuses exclusively on single-serving desserts rather than bulk orders, packaged products, or multi-serving desserts.

The model produces estimated prices that can support Sweetery's dessert recommendation system.

## 1. Dataset Preparation

### Original Dataset

The original restaurant menu dataset was obtained from Kaggle:

**Dataset Source:** [Uber Eats USA Restaurants and Menus Dataset Updated, v3](https://www.kaggle.com/discussions/general/333340?utm_source=chatgpt.com)

The source describes a collection of menu data from over 15,000 U.S. restaurants, containing more than 1.3 million menu entries.

The original `restaurant-menus.csv` dataset contains restaurant menu information, including:

- Restaurant identifiers
- Menu item names
- Categories
- Descriptions
- Prices

Because the dataset contains both dessert and non-dessert items, additional cleaning and preprocessing were necessary before training the Sweetery price prediction model.

### Data Cleaning — `cleaning.py`

The cleaning script extracts dessert-related menu items from the original dataset.

The following operations are performed:

1. **Dessert Identification:** Uses regular expressions to identify dessert categories such as cookies, cakes, ice cream, brownies, milkshakes, and pastries.
2. **Non-Dessert Filtering:** Removes unrelated menu items.
3. **Price Conversion:** Converts prices into numeric values and removes missing, invalid, or nonpositive prices.
4. **Dessert Classification:** Assigns dessert types based on item names and menu categories.
5. **Serving Classification:** Classifies desserts as `single`, `bulk`, `packaged`, or `unspecified`.
6. **Duplicate Removal:** Removes duplicate records based on restaurant identifier, dessert name, and price.
7. **Outlier Removal:** Applies the Interquartile Range (IQR) method within dessert and serving categories.

The cleaned dataset is saved as:

`data/sweetery_dessert_prices_v2.csv`

### Exploratory Data Analysis — `explore_prices.py`

The exploratory script examines unusually expensive menu items and desserts classified as `other` to identify potential pricing and classification problems.

### Training Dataset Preparation — `prepare_training_data.py`

The preparation script removes candy, unclassified desserts, and records flagged for review.

The resulting dataset is saved as:

`data/sweetery_training_data.csv`

| Column | Description |
|---|---|
| `restaurant_id` | Restaurant identifier |
| `name` | Dessert name |
| `dessert_type` | Classified dessert category |
| `serving_type` | Classified serving category |
| `price` | Actual menu price |

## 2. Single-Serving Model Training

### Training Script

`train_single_price_model.py`

The single-serving model uses the prepared training dataset and applies additional filtering:

- Prices must be between $1 and $50.
- Restaurant identifiers, dessert names, and dessert categories must be present.
- Serving type must be classified as `single`.
- Duplicate records are removed.
- At least 100 eligible training records are required.

### Model Features

| Feature | Processing Method |
|---|---|
| Dessert Name | TF-IDF Vectorization |
| Dessert Type | One-Hot Encoding |
| Serving Type | One-Hot Encoding |

The prediction target is the actual dessert price.

### TF-IDF Vectorization

TF-IDF converts dessert names into numerical features.

Configuration:

- N-gram range: (1, 2)
- Minimum document frequency: 3
- Maximum features: 12,000

### Ridge Regression

The model uses Ridge Regression with L2 regularization.

```python
Ridge(alpha=10.0, solver="lsqr")
```

The preprocessing and regression components are combined into a Scikit-learn pipeline.

The final model is trained on all eligible single-serving records in the prepared dataset.

## 3. Saved Model

The trained model is saved as:

`models/sweetery_single_price_model.joblib`

The saved file contains the trained pipeline, input features, training record count, dessert category medians, and overall median price.

## 4. Model Evaluation

Earlier evaluation of Sweetery's calibrated Ridge Regression price estimation approach produced the following results for single-serving desserts:

| Metric | Result |
|---|---|
| Estimated Price Range Coverage | **87.5%** |
| Actual Prices Within Estimated Ranges | 35 of 40 |
| Mean Absolute Error | $1.68 |
| Root Mean Squared Error | $2.26 |
| Evaluation Records | 40 |

The 87.5% coverage result indicates that 35 of 40 actual menu prices fell within their estimated price intervals.

**Note:** These results describe the earlier calibrated Ridge Regression evaluation, not an independent validation of the final `sweetery_single_price_model.joblib` artifact. The single-serving training script does not itself calibrate or save prediction intervals.

## 5. Running the Training Pipeline

Clean the original dataset:

```bash
python cleaning.py
```

Explore dessert prices:

```bash
python explore_prices.py
```

The exploration script may require updating its input path to `data/sweetery_dessert_prices_v2.csv`.

Prepare the training dataset:

```bash
python prepare_training_data.py
```

Train the single-serving model:

```bash
python train_single_price_model.py
```

The trained model is saved to `models/sweetery_single_price_model.joblib`.

## 6. Limitations

- The model estimates prices rather than retrieving verified menu prices.
- It is designed specifically for single-serving desserts.
- Serving classification depends on keywords in menu item names and descriptions.
- Some individual desserts may be excluded when classified as `unspecified`.
- Prices can vary by restaurant, location, and menu changes.
- The final single-serving model does not independently calibrate prediction intervals.
- Additional validation is needed to establish range coverage for the saved model.

## Conclusion

The Sweetery Single-Serving Price Prediction Model uses restaurant menu data originally sourced from Kaggle to train a TF-IDF and Ridge Regression pipeline.

The training process includes data cleaning, dessert classification, serving classification, outlier removal, feature engineering, and model training.

By focusing on single-serving desserts, the model avoids mixing individual dessert prices with bulk orders and multi-serving products.

The trained model provides estimated prices as a fallback when verified menu prices are unavailable.
