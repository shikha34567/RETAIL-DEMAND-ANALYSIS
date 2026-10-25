import urllib.request
import urllib.parse
import json
import ssl
import re

ctx = ssl.create_default_context()

def get_samples_and_fields(resource_id):
    url = f"https://data.cityofchicago.org/resource/{resource_id}.json?$limit=10"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data

def get_page_summary(resource_id):
    url = f"https://data.cityofchicago.org/api/views/{resource_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        meta = json.loads(resp.read().decode("utf-8"))
    return {
        "id": meta.get("id"),
        "name": meta.get("name"),
        "createdAt": meta.get("createdAt"),
        "rowsUpdatedAt": meta.get("rowsUpdatedAt"),
        "columns": [(c.get("name"), c.get("fieldName"), c.get("dataTypeName")) for c in meta.get("columns", [])],
        "description": meta.get("description"),
    }

def probe_date_slice(resource_id, start_iso, end_iso):
    # Test a 1-day slice to see performance and record structure
    params = {
        "$where": f"trip_start_timestamp >= '{start_iso}' AND trip_start_timestamp < '{end_iso}'",
        "$limit": 5,
        "$order": "trip_start_timestamp ASC"
    }
    url = f"https://data.cityofchicago.org/resource/{resource_id}.json?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

print("=== TAXI TRIPS SAMPLE ===")
taxi_samples = get_samples_and_fields("wrvz-psew")
print("Taxi sample count:", len(taxi_samples))
if taxi_samples:
    print("Sample record 0 keys:", list(taxi_samples[0].keys()))
    print("Sample record 0:")
    print(json.dumps(taxi_samples[0], indent=2))

print("\n=== TNP TRIPS SAMPLE ===")
tnp_samples = get_samples_and_fields("m6dm-c72p")
print("TNP sample count:", len(tnp_samples))
if tnp_samples:
    print("Sample record 0 keys:", list(tnp_samples[0].keys()))
    print("Sample record 0:")
    print(json.dumps(tnp_samples[0], indent=2))

print("\n=== PROBING 1-DAY SLICE (2022-06-01) FOR TAXI ===")
taxi_day = probe_date_slice("wrvz-psew", "2022-06-01T00:00:00", "2022-06-02T00:00:00")
print("Found taxi rows:", len(taxi_day))
if taxi_day:
    print(json.dumps(taxi_day[0], indent=2))

print("\n=== PROBING 1-DAY SLICE (2022-06-01) FOR TNP ===")
tnp_day = probe_date_slice("m6dm-c72p", "2022-06-01T00:00:00", "2022-06-02T00:00:00")
print("Found tnp rows:", len(tnp_day))
if tnp_day:
    print(json.dumps(tnp_day[0], indent=2))

