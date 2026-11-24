# Recommendation Agent: Review Scoring

This document explains how the recommendation agent scores dessert businesses,
how the score reaches the ranking agent, and how review data is cached.

## What the score means

The recommendation score (0 to 100) describes how well a **business** is rated by
customers, and how well its dessert-specific reviews look. It does not say whether
the business suits a particular user. The ranking agent decides that, using the
user's flavor, budget, and location.

## Pipeline flow

```
research agent  ->  dessert records
                         |
pipeline.py             normalize -> research -> recommend -> check
                         |
                         v
recommendation agent     score_businesses(candidate desserts)
                         |   find each business on Google Places and Yelp
                         |   collect ratings and review text
                         |   Ollama reads review text (judgments only)
                         |   Python computes score and confidence
                         v
ranking agent            rank(request, checked, recommendation_scores)
                         |
                         v
                  PipelineResult (each result has a "recommendation" field)
```

If review scoring fails, is disabled, or has no data, ranking runs exactly as it
did before this feature existed.

## Component scores

Each component is on a 0 to 100 scale, or `None` if there is no evidence for it.

| Component | Weight | How it is computed |
|---|---:|---|
| Customer ratings | 40 | Star ratings from all platforms, combined with Bayesian smoothing (below). The 1 to 5 star result is mapped to 0 to 100 with `(rating - 1) / 4 * 100`. |
| Review sentiment | 30 | Ollama's `sentiment_score` for the business's reviews. |
| Dessert quality | 20 | Ollama's `dessert_quality_score`, which only uses reviews that discuss desserts. |
| Review recency | 10 | Mean of `100 * 0.5 ** (age_days / 365)` over the dated reviews collected. A one-year-old review counts 50. |

### Combining platforms: why not a simple average

Google and Yelp may have very different review counts (for example, 150 and 12),
so a plain average would give the 12-review platform as much weight as the
150-review one. The agent combines them with Bayesian smoothing:

```
combined = (C * m + sum(rating_p * count_p)) / (C + sum(count_p))
```

- `count_p` is each platform's review count, so larger platforms count more.
- `m` is a prior mean (default 3.8 stars) and `C` is a prior weight (default 10 reviews).
- A business with very few reviews is pulled toward `m`. Two five-star reviews
  do not outrank 200 reviews averaging 4.6.

### Final score

```
score = sum(w_i * x_i) / sum(w_i)      over the components i that are not None
```

Missing data is never counted as zero. If Ollama is unavailable, the sentiment
component is missing, the remaining weights are renormalized, and confidence is
lowered. A business with no reviews gets `score = None`.

`evidence_coverage` is the share of the total weight that has evidence
(1.0 means all four components are present).

## Confidence

Confidence is a separate label and is not part of the number.

| Level | Requirement |
|---|---|
| `unknown` | No score. |
| `high` | At least 50 total ratings, at least 5 analyzed reviews, sentiment present, dessert-related reviews, and the model judged the evidence sufficient. |
| `medium` | Sentiment present, evidence judged sufficient, and at least 10 ratings or 3 analyzed reviews. |
| `low` | Anything else that has a score (for example, ratings only). |

## Ranking integration

`rank(request, checked_candidates, recommendation_scores=None)` accepts the score
records from the recommendation agent. The review score is a tiebreak placed
after verification status and flavor match, and before price and distance:

1. Verified before unknown (unchanged)
2. Flavor match (unchanged)
3. **Review score, higher first. Candidates with no review score come after scored ones.**
4. Confirmed price, lower first (unchanged)
5. Distance, nearer first (unchanged)

This means a verified or flavor-matching dessert still beats a higher-rated one.
The review score only decides between candidates that are otherwise equal.

Without review data, every candidate has the same review value, so the original
ordering is kept exactly. The pipeline comparison in the test suite confirms
identical output for several requests.

Each ranked result gets a `recommendation` field. It is `None` for unscored
businesses, and otherwise holds `score`, `confidence`, `evidence_coverage`,
`review_count_used`, and `analysis_status`. The reason text adds
`review score 82/100 (medium confidence)` only when a score exists.

To change the position of the review score, edit `_sort_key` in
`agents/ranking_agent.py`. This is a single line and should be agreed with the team.

## Ollama's role and its limits

Ollama reads review text and returns judgments. It does not compute the final score.

Enforced in code, not only in the prompt:

- Only reviews sent to the model can be cited. Any other review ID is dropped.
- A reply that cites no valid review has its scores discarded.
- Scores outside 0 to 100 are discarded, not clipped.
- Malformed JSON and unreachable servers are reported as `malformed` or
  `unavailable`. The business is then scored from ratings alone, with low confidence.
- The model is called with `format: "json"` and `temperature: 0`.
- The model is not called when there are no reviews.
- Once Ollama is unavailable, it is not called again for the rest of the run.

## Business matching

A wrong match would give one shop another shop's reviews, so matching is strict.
A listing is accepted only if:

- its name is essentially the same (normalized, similarity of at least 0.92), and
- its street number matches the dessert record's address and it is in Cookeville.

If the dessert record has no address, only an exact name match in Cookeville is
accepted. Closed listings are ignored. If two different listings both match, the
result is `ambiguous` and neither is used. Chain locations are separated by street
number and scored separately.

## Review collection and de-duplication

- A review is a duplicate if it repeats a platform review ID, or if it has the same
  text of 40 characters or more (for example, one review shown on both platforms).
  Short phrases such as "Great!" are not merged.
- Only the first 15 reviews with text are sent to Ollama, each truncated.

## Caching and storage policy

Google and Yelp have different terms, so each has its own rule.

| Data | Where it is kept | How long | Setting |
|---|---|---|---|
| Yelp search results and reviews | Disk (`data/review_cache/`, gitignored) | 24 hours | `SWEETERY_REVIEW_CACHE_HOURS` |
| Google search results, place details, and reviews | Memory only, never disk | 60 minutes, for this process only | `SWEETERY_GOOGLE_MEMORY_CACHE_MINUTES` |
| Ollama analysis of Yelp text only | Disk | 24 hours | (uses the Yelp setting) |
| Ollama analysis that includes any Google text | Memory only | 60 minutes | (uses the Google setting) |
| Output file `data/recommendation_output/business_scores.json` | Disk (gitignored) | Until overwritten | (see below) |

Setting either TTL to `0` turns that store off.

**Output file.** The file written by the CLI omits Google review text, and Google
links. Scores, Yelp excerpts with their links, and Google ratings and counts are
kept. The in-memory records used by the pipeline are not changed.

Failed requests are not cached. API keys are sent only in request headers, never in
URLs, logs, or output.

## API sources

| Platform | Used for | Notes |
|---|---|---|
| Google Places API (New) | Place search, rating, review count, up to 5 reviews, website | Approved for this project. Uses the Places API (New) endpoints. The older Place Details web-service endpoint is legacy. Review data is billed under a higher-cost SKU. |
| Yelp Fusion | Business search, rating, review count, up to 3 review excerpts | Cached for 24 hours, consistent with Yelp's current developer guidance. Attribution is required when displaying content. |
| Tripadvisor | Not implemented | Future optional integration. API access is partner-dependent. Its older API is reported to be transitioning toward the Terra platform, so current availability should be verified before any work starts. |

### Failure handling

| Situation | Behavior |
|---|---|
| No API key | Source skipped. Status `not_configured`. No request made. |
| HTTP 429 (rate limit) | Status `rate_limited`. That source is not called again in the same run. |
| Other HTTP error or timeout | Status `unavailable`. The other source is still used. |
| Ollama down | Status `unavailable`. Scoring uses ratings alone. Ollama is not retried in the run. |
| Scoring raises an unexpected error | Logged. Ranking proceeds without review scores. |

## Configuration

Copy `.env.example` to `.env` and fill in the keys you have. `.env` is gitignored.
Every setting can also be set as an environment variable. Real environment variables
take precedence over `.env`.

| Setting | Default | Meaning |
|---|---|---|
| `GOOGLE_PLACES_API_KEY` | (blank) | Google key. Blank means Google is skipped. |
| `YELP_API_KEY` | (blank) | Yelp key. Blank means Yelp is skipped. |
| `SWEETERY_REVIEW_SOURCES` | `google,yelp` | Platforms to query. |
| `SWEETERY_REVIEW_SCORING` | `1` | Set to `0` to skip review scoring in the pipeline entirely. |
| `SWEETERY_REVIEW_CACHE_HOURS` | `24` | Yelp disk cache lifetime. `0` disables it. |
| `SWEETERY_GOOGLE_MEMORY_CACHE_MINUTES` | `60` | Google in-memory cache lifetime. `0` disables it. |
| `SWEETERY_WEIGHT_RATINGS` | `40` | Weight for customer ratings. |
| `SWEETERY_WEIGHT_SENTIMENT` | `30` | Weight for review sentiment. |
| `SWEETERY_WEIGHT_DESSERT_QUALITY` | `20` | Weight for dessert quality. |
| `SWEETERY_WEIGHT_RECENCY` | `10` | Weight for review recency. |
| `SWEETERY_RATING_PRIOR_MEAN` | `3.8` | Prior mean for Bayesian smoothing. |
| `SWEETERY_RATING_PRIOR_COUNT` | `10` | Prior weight for Bayesian smoothing. |
| `SWEETERY_RECENCY_HALF_LIFE_DAYS` | `365` | Days until a review's recency value halves. |
| `SWEETERY_REVIEW_MAX_TEXTS` | `15` | Most reviews sent to Ollama per business. |
| `OLLAMA_MODEL`, `OLLAMA_HOST` | (existing) | Reused from the ranking agent. The model is not changed. |

Weights are relative. They do not have to add up to 100.

## Running it

Prerequisites:

1. Python 3 (tested on 3.12) and `pip install -r requirements.txt`.
2. Optional, for review scores: Ollama running locally with the model pulled
   (`ollama pull llama3.2`, or the model in `SWEETERY_OLLAMA_MODEL`).
3. Optional: API keys in `.env` (see Configuration).

From the project root:

```bash
# Use the Streamlit app. Review scoring runs automatically if keys or Ollama are set.
streamlit run app.py

# Score a file of dessert records on its own and write the scores to a file
python -m agents.recommendation_agent data/cookeville_chocolate_ice_cream.json --output /tmp/scores.json
```

With no keys set, the app works as before and review scores are simply absent.

## Running the tests

```bash
python -m pytest -q
```

The tests never call a real API or Ollama. `tests/conftest.py` provides the
`review_env` fixture, which isolates the cache, clears the keys, and makes any real
HTTP call fail the test.

Note: `tests/test_pipeline.py` has 4 failures that existed before this work. They
come from the pipeline's default mock file, which does not match what those tests
expect. They are not caused by the recommendation agent.

## Example output

This example uses stubbed platform responses and a stubbed model reply, with the real
scoring code.

```json
{
  "business_key": "cream city ice cream and coffee house|119",
  "business_name": "Cream City Ice Cream & Coffee House",
  "address": "119 W Broad St, Cookeville, TN",
  "dessert_ids": ["rl_001", "rl_002"],
  "google_rating": 4.5,
  "google_review_count": 150,
  "yelp_rating": 4.0,
  "yelp_review_count": 75,
  "review_count_used": 3,
  "combined_rating": 4.31,
  "total_ratings": 225,
  "rating_score": 82.8,
  "sentiment_score": 84,
  "dessert_quality_score": 88,
  "review_recency_score": 63.7,
  "recommendation_score": 82,
  "evidence_coverage": 1.0,
  "confidence": "medium",
  "analysis_status": "ok",
  "evidence": [
    {"review_id": "R1", "platform": "google", "rating": 5, "date": "2026-09-15T00:00:00Z",
     "excerpt": null, "url": null},
    {"review_id": "R2", "platform": "google", "rating": 4, "date": "2026-02-01T00:00:00Z",
     "excerpt": null, "url": null},
    {"review_id": "R3", "platform": "yelp", "rating": 4, "date": "2025-07-10 18:00:00",
     "excerpt": "Creamy chocolate, a little icy near the bottom of the tub.",
     "url": "https://yelp.example/r1"}
  ],
  "sources": [
    {"platform": "google", "status": "matched", "url": null},
    {"platform": "yelp", "status": "matched", "url": "https://yelp.example/cream-city"}
  ],
  "last_checked": "2026-11-02T00:00:00+00:00"
}
```

Google evidence items keep their place in the list, but their excerpt and link are `null` in the file, as described under Caching. The score
of 82 is `(40 × 82.8 + 30 × 84 + 20 × 88 + 10 × 63.7) / 100 = 82.3`, rounded.
The rating component is `(10 × 3.8 + 4.5 × 150 + 4.0 × 75) / 235 = 4.31` stars, mapped to 82.8.
Confidence is `medium`: 225 ratings, but only 3 analyzed reviews, below the `high` threshold.

## Open items

- **Live research.** The research agent is still in mock mode, so review scoring
  currently runs on the mock dessert records.
- **Tripadvisor.** Not implemented. Verify current API availability before starting.
- **Google caching terms.** The in-memory and no-disk policy reflects the team's
  decision. Confirm it against the signed agreement, including whether ratings and
  counts may be written to the output file.
