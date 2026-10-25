import urllib.request
import json
import ssl

ctx = ssl.create_default_context()

def fetch_and_save_samples(resource_id, name):
    url = f"https://data.cityofchicago.org/api/views/{resource_id}/rows.json?max_rows=10"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Inspector/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        raw_json = json.loads(resp.read().decode("utf-8"))
    
    columns = [col["fieldName"] for col in raw_json["meta"]["view"]["columns"]]
    data = raw_json["data"]
    
    records = []
    for row in data:
        record = dict(zip(columns, row))
        records.append(record)
        
    out_file = f"docs/evidence/sample_{resource_id}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "dataset_id": resource_id,
            "dataset_name": name,
            "columns": raw_json["meta"]["view"]["columns"],
            "sample_records": records
        }, f, indent=2)
    print(f"Saved {len(records)} sample records for {name} to {out_file}")
    return records

print("Fetching Taxi samples...")
taxi_records = fetch_and_save_samples("wrvz-psew", "Taxi Trips (2013-2023)")
print("Fetching TNP samples...")
tnp_records = fetch_and_save_samples("m6dm-c72p", "Transportation Network Providers - Trips (2018-2022)")

