import urllib.request
import urllib.parse
import json
import ssl

ctx = ssl.create_default_context()

def query_socrata(resource_id, query_params):
    base_url = f"https://data.cityofchicago.org/resource/{resource_id}.json"
    url = f"{base_url}?{urllib.parse.urlencode(query_params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_view_meta(resource_id):
    url = f"https://data.cityofchicago.org/api/views/{resource_id}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def search_datasets(query):
    url = f"https://data.cityofchicago.org/api/catalog/v1?{urllib.parse.urlencode({'q': query, 'limit': 10})}"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

print("=== 1. SEARCHING FOR CHICAGO TAXI & TNP DATASETS ===")
search_results = search_datasets("Taxi Trips")
for item in search_results.get("results", []):
    res = item.get("resource", {})
    print(f"Dataset: {res.get('name')} | ID: {res.get('id')} | Type: {res.get('type')} | Updated: {res.get('updatedAt')}")

tnp_search = search_datasets("Transportation Network Providers Trips")
for item in tnp_search.get("results", []):
    res = item.get("resource", {})
    print(f"Dataset: {res.get('name')} | ID: {res.get('id')} | Type: {res.get('type')} | Updated: {res.get('updatedAt')}")

