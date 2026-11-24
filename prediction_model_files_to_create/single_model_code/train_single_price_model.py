"""Train Sweetery's production single-serving Ridge price estimator.

Run: python train_single_price_model.py
Uses only data/sweetery_training_data.csv, not Cookeville validation prices.
"""
from pathlib import Path
import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / 'data' / 'sweetery_training_data.csv'
MODEL_FILE = BASE_DIR / 'models' / 'sweetery_single_price_model.joblib'
FEATURES = ['name', 'dessert_type', 'serving_type']


def train():
    df = pd.read_csv(DATA_FILE)
    required = {'restaurant_id', 'name', 'dessert_type', 'serving_type', 'price'}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f'Missing training columns: {sorted(missing)}')
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df = df[df['price'].between(1.0, 50.0, inclusive='both')].copy()
    df = df.dropna(subset=['restaurant_id', 'name', 'dessert_type'])
    for col in ['restaurant_id'] + FEATURES:
        df[col] = df[col].fillna('unspecified').astype(str).str.lower().str.strip()
    df = df[df['serving_type'] == 'single'].copy()
    df = df.drop_duplicates(subset=['restaurant_id', *FEATURES, 'price'])
    if len(df) < 100:
        raise ValueError('Not enough single-serving training examples.')

    preprocess = ColumnTransformer([
        ('name_tfidf', TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=12000), 'name'),
        ('type', OneHotEncoder(handle_unknown='ignore'), ['dessert_type']),
        ('serving', OneHotEncoder(handle_unknown='ignore'), ['serving_type']),
    ], sparse_threshold=0.3)
    pipeline = Pipeline([
        ('preprocess', preprocess),
        ('ridge', Ridge(alpha=10.0, solver='lsqr')),
    ])
    pipeline.fit(df[FEATURES], df['price'])
    payload = {
        'pipeline': pipeline,
        'features': FEATURES,
        'serving_type': 'single',
        'training_records': len(df),
        'type_medians': df.groupby('dessert_type')['price'].median().to_dict(),
        'global_median': float(df['price'].median()),
        'price_status': 'estimated',
    }
    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, MODEL_FILE)
    print(f'Trained on {len(df):,} single-serving records')
    print(f'Saved model: {MODEL_FILE}')
    print('Note: this trains on all eligible single-serving data; previous holdout scores are not a new evaluation of this saved model.')


if __name__ == '__main__':
    train()
