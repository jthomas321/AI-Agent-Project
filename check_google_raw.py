import json
import urllib.error
import urllib.request

from tools.review_apis import GooglePlacesSource

s = GooglePlacesSource()

listing, reason = s.find_business(
    "Cream City Ice Cream & Coffee House",
    "119 W Broad St, Cookeville, TN"
)

print("reason:", reason)

if listing:
    url = f"https://places.googleapis.com/v1/places/{listing['id']}"

    headers = {
        "X-Goog-Api-Key": s.api_key,
        "X-Goog-FieldMask": "id,displayName,rating,userRatingCount,reviews",
    }

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req) as response:
            print("HTTP status:", response.status)

            data = json.loads(response.read().decode("utf-8"))

            print(json.dumps(data, indent=2))

    except urllib.error.HTTPError as e:
        print("HTTP error:", e.code)
        print(e.read().decode("utf-8"))