import urllib.parse
import urllib.request
import urllib.error
from tools.review_apis import YelpFusionSource

s = YelpFusionSource()
listing, reason = s.find_business("Cream City Ice Cream & Coffee House", "119 W Broad St, Cookeville, TN")
print("reason:", reason)

if listing is None:
    print("no listing chosen")
else:
    print("listing id:", listing["id"], "| name:", listing["name"])
    path = urllib.parse.quote(listing["id"], safe="")
    url = f"{s.BASE_URL}/{path}/reviews?locale=en_US"
    print("reviews URL:", url)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + s.api_key})
    try:
        print("OK", urllib.request.urlopen(req).status)
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode()[:300])

if listing is not None:
    detail_url = f"{s.BASE_URL}/{path}"
    print("details URL:", detail_url)
    req = urllib.request.Request(detail_url, headers={"Authorization": "Bearer " + s.api_key})
    try:
        print("details OK", urllib.request.urlopen(req).status)
    except urllib.error.HTTPError as e:
        print("details", e.code, e.read().decode()[:300])
import urllib.parse
import urllib.request
import urllib.error
from tools.review_apis import YelpFusionSource

s = YelpFusionSource()
listing, reason = s.find_business("Cream City Ice Cream & Coffee House", "119 W Broad St, Cookeville, TN")
print("reason:", reason)

if listing is None:
    print("no listing chosen")
else:
    print("listing id:", listing["id"], "| name:", listing["name"])
    path = urllib.parse.quote(listing["id"], safe="")

    def try_url(label, url):
        print(label, "URL:", url)
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + s.api_key})
        try:
            print(label, "OK", urllib.request.urlopen(req).status)
        except urllib.error.HTTPError as e:
            print(label, e.code, e.read().decode()[:300])

    try_url("details", f"{s.BASE_URL}/{path}")
    try_url("reviews", f"{s.BASE_URL}/{path}/reviews?locale=en_US")
    try_url("highlights", f"{s.BASE_URL}/{path}/review_highlights")