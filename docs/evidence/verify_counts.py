import urllib.request
import urllib.parse
import json
import ssl

ctx = ssl.create_default_context()

def run_count(title, resource_id, start_ts, end_ts):
    params = {
        "$where": f"trip_start_timestamp >= '{start_ts}' and trip_start_timestamp < '{end_ts}'",
        "$select": "count(trip_id) as total_trips"
    }
    url = f"https://data.cityofchicago.org/resource/{resource_id}.json?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        print(f"{title} ({start_ts} to {end_ts}): {res[0]['total_trips']} trips")
        return int(res[0]['total_trips'])

print("=== TAXI COUNTS ===")
run_count("Taxi 1-day", "wrvz-psew", "2022-06-01T00:00:00", "2022-06-02T00:00:00")
run_count("Taxi 1-week", "wrvz-psew", "2022-06-01T00:00:00", "2022-06-08T00:00:00")
run_count("Taxi 1-month (June 2022)", "wrvz-psew", "2022-06-01T00:00:00", "2022-07-01T00:00:00")

print("\n=== TNP COUNTS ===")
run_count("TNP 1-day", "m6dm-c72p", "2022-06-01T00:00:00", "2022-06-02T00:00:00")
run_count("TNP 1-week", "m6dm-c72p", "2022-06-01T00:00:00", "2022-06-08T00:00:00")
run_count("TNP 1-month (June 2022)", "m6dm-c72p", "2022-06-01T00:00:00", "2022-07-01T00:00:00")

