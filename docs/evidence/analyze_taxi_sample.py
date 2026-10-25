import urllib.request
import urllib.parse
import json
import ssl

ctx = ssl.create_default_context()

def analyze_taxi_slice():
    params = {
        "$where": "trip_start_timestamp >= '2022-06-01T00:00:00' and trip_start_timestamp < '2022-06-02T00:00:00'",
        "$limit": 1000,
        "$order": "trip_start_timestamp ASC"
    }
    url = f"https://data.cityofchicago.org/resource/wrvz-psew.json?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        records = json.loads(resp.read().decode("utf-8"))
        
    print(f"Fetched {len(records)} records from 2022-06-01 Taxi Trips.")
    
    # 1. Null analysis
    n = len(records)
    null_trip_id = sum(1 for r in records if "trip_id" not in r or not r["trip_id"])
    null_lat = sum(1 for r in records if "pickup_centroid_latitude" not in r or not r["pickup_centroid_latitude"])
    null_lon = sum(1 for r in records if "pickup_centroid_longitude" not in r or not r["pickup_centroid_longitude"])
    null_community = sum(1 for r in records if "pickup_community_area" not in r or not r["pickup_community_area"])
    null_tract = sum(1 for r in records if "pickup_census_tract" not in r or not r["pickup_census_tract"])
    
    print("\n--- NULL / PRESENCE ANALYSIS (N = 1000) ---")
    print(f"Missing trip_id: {null_trip_id} ({null_trip_id/n:.1%})")
    print(f"Missing pickup_lat/lon: {null_lat} ({null_lat/n:.1%})")
    print(f"Missing pickup_community_area: {null_community} ({null_community/n:.1%})")
    print(f"Missing pickup_census_tract: {null_tract} ({null_tract/n:.1%})")
    
    # 2. Timestamp analysis
    minutes = set()
    seconds = set()
    for r in records:
        ts = r.get("trip_start_timestamp", "")
        if "T" in ts:
            time_part = ts.split("T")[1]
            parts = time_part.split(":")
            if len(parts) >= 2:
                minutes.add(parts[1])
            if len(parts) >= 3:
                seconds.add(parts[2])
    print("\n--- TIMESTAMP PRECISION ANALYSIS ---")
    print(f"Unique start minutes observed: {sorted(list(minutes))}")
    print(f"Unique start seconds observed: {sorted(list(seconds))}")
    
    # 3. Spatial centroid discretization
    coords = set()
    for r in records:
        lat = r.get("pickup_centroid_latitude")
        lon = r.get("pickup_centroid_longitude")
        if lat and lon:
            coords.add((lat, lon))
    print("\n--- COORDINATE CLUSTERING ANALYSIS ---")
    print(f"Total non-null coordinate rows: {n - null_lat}")
    print(f"Distinct (lat, lon) coordinates: {len(coords)}")
    print(f"Compression ratio (distinct coords / valid rows): {len(coords)/(n - null_lat):.3f}")
    
    # Check sample coordinates
    print(f"Sample distinct coordinates (first 5): {list(coords)[:5]}")
    
    # 4. Trip ID format & uniqueness
    trip_ids = [r["trip_id"] for r in records if "trip_id" in r]
    unique_trip_ids = set(trip_ids)
    print("\n--- TRIP ID ANALYSIS ---")
    print(f"Trip IDs count: {len(trip_ids)}, Unique trip IDs: {len(unique_trip_ids)}")
    print(f"Sample trip_id: {trip_ids[0] if trip_ids else 'None'} (Length: {len(trip_ids[0]) if trip_ids else 0})")
    
    # Save results to evidence
    evidence = {
        "dataset_id": "wrvz-psew",
        "sample_size": n,
        "date_slice": "2022-06-01",
        "missing_counts": {
            "trip_id": null_trip_id,
            "pickup_coordinates": null_lat,
            "pickup_community_area": null_community,
            "pickup_census_tract": null_tract
        },
        "timestamp_minutes": sorted(list(minutes)),
        "timestamp_seconds": sorted(list(seconds)),
        "distinct_coordinates": len(coords),
        "total_valid_coordinate_rows": n - null_lat,
        "sample_distinct_coordinates": list(coords)[:5],
        "sample_records": records[:3]
    }
    with open("docs/evidence/taxi_sample_analysis.json", "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)
    print("\nSaved evidence to docs/evidence/taxi_sample_analysis.json")

if __name__ == "__main__":
    analyze_taxi_slice()

