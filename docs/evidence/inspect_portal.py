import urllib.request
import urllib.parse
import json
import ssl
import sys

ctx = ssl.create_default_context()

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Dataset-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))

def query_resource(resource_id, params):
    base_url = f"https://data.cityofchicago.org/resource/{resource_id}.json"
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    return get_json(url)

print("--- Testing yearly count queries ---")
for fid, name in [
    ("npd7-ywjz", "Taxi Trips - 2022"),
    ("h4cq-z3dy", "Taxi Trips - 2019"),
    ("2tdj-ffvb", "TNP Trips - 2022"),
    ("iu3g-qa69", "TNP Trips - 2019")
]:
    try:
        res = query_resource(fid, {"$select": "count(trip_id) as total_trips"})
        print(f"{name} ({fid}): {res}")
    except Exception as e:
        print(f"{name} ({fid}) error: {e}")


