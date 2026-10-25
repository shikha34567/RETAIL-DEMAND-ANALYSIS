import urllib.request
import urllib.parse
import json
import ssl
import time

ctx = ssl.create_default_context()

def benchmark():
    params = {
        "$where": "trip_start_timestamp >= '2022-06-01T00:00:00' and trip_start_timestamp < '2022-06-02T00:00:00'",
        "$limit": 10000,
        "$order": "trip_start_timestamp ASC, trip_id ASC"
    }
    url = f"https://data.cityofchicago.org/resource/wrvz-psew.json?{urllib.parse.urlencode(params)}"
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Downloader/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    t1 = time.time()
    print(f"Retrieved {len(data)} rows in {t1 - t0:.2f}s")
    
    # Try limit 25000
    params["$limit"] = 25000
    url = f"https://data.cityofchicago.org/resource/wrvz-psew.json?{urllib.parse.urlencode(params)}"
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Downloader/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        data25 = json.loads(resp.read().decode("utf-8"))
    t1 = time.time()
    print(f"Retrieved {len(data25)} rows with limit 25000 in {t1 - t0:.2f}s")

if __name__ == "__main__":
    benchmark()

