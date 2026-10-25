import urllib.request
import urllib.parse
import json
import ssl

ctx = ssl.create_default_context()

params = {
    "$where": "trip_start_timestamp >= '2022-06-01T00:00:00' and trip_start_timestamp < '2022-06-02T00:00:00'",
    "$select": "count(trip_id) as day_count"
}
url = f"https://data.cityofchicago.org/resource/wrvz-psew.json?{urllib.parse.urlencode(params)}"
req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
try:
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        print("1-day taxi count (2022-06-01):", json.loads(resp.read().decode("utf-8")))
except Exception as e:
    print("Query error:", e)

