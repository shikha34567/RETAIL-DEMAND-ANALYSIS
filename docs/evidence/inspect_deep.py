import urllib.request
import urllib.parse
import json
import ssl

ctx = ssl.create_default_context()

def query_socrata(resource_id, params):
    base_url = f"https://data.cityofchicago.org/resource/{resource_id}.json"
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def inspect_dataset_deep(name, resource_id):
    print(f"\n=======================================================")
    print(f"DEEP INSPECTION: {name} (ID: {resource_id})")
    print(f"=======================================================")
    
    # 1. Total Count
    count_res = query_socrata(resource_id, {"$select": "count(*)"})
    total_count = count_res[0].get("count")
    print(f"Total row count: {total_count}")

    # 2. Date Range
    range_res = query_socrata(resource_id, {
        "$select": "min(trip_start_timestamp) as min_start, max(trip_start_timestamp) as max_start, min(trip_end_timestamp) as min_end, max(trip_end_timestamp) as max_end"
    })
    print(f"Timestamp range: {json.dumps(range_res, indent=2)}")

    # 3. Check sample rows
    samples = query_socrata(resource_id, {"$limit": 5})
    print(f"\nSample record 0:")
    print(json.dumps(samples[0], indent=2))

    # 4. Check trip_id format & uniqueness in sample
    trip_ids = [s.get("trip_id") for s in samples]
    print(f"\nSample trip_ids: {trip_ids}")
    print(f"Sample trip_id lengths: {[len(t) if t else None for t in trip_ids]}")

    # 5. Null rates for spatial and ID fields (on a 50,000 row probe or using aggregation)
    # Using aggregation:
    agg_res = query_socrata(resource_id, {
        "$select": "count(trip_id) as cnt_trip_id, count(pickup_centroid_latitude) as cnt_lat, count(pickup_community_area) as cnt_community, count(pickup_census_tract) as cnt_tract, count(*)"
    })
    print(f"\nField presence counts (all rows): {json.dumps(agg_res, indent=2)}")

    # 6. Coordinate precision & distribution of pickup coordinates
    # Let's inspect 10 sample distinct pickup coordinates
    coord_res = query_socrata(resource_id, {
        "$select": "pickup_centroid_latitude, pickup_centroid_longitude, pickup_community_area, pickup_census_tract, count(*)",
        "$where": "pickup_centroid_latitude is not null",
        "$group": "pickup_centroid_latitude, pickup_centroid_longitude, pickup_community_area, pickup_census_tract",
        "$order": "count(*) desc",
        "$limit": 10
    })
    print(f"\nTop 10 most frequent pickup coordinate clusters:")
    print(json.dumps(coord_res, indent=2))

    # Count distinct pickup coordinate pairs
    distinct_coords = query_socrata(resource_id, {
        "$select": "count(distinct pickup_centroid_latitude) as distinct_lat, count(distinct pickup_centroid_longitude) as distinct_lon",
        "$where": "pickup_centroid_latitude is not null"
    })
    print(f"\nDistinct latitude/longitude counts: {json.dumps(distinct_coords, indent=2)}")

if __name__ == "__main__":
    inspect_dataset_deep("Chicago Taxi Trips (2013-2023)", "wrvz-psew")
    inspect_dataset_deep("Chicago TNP Trips (2018-2022)", "m6dm-c72p")

