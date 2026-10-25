import urllib.request
import urllib.parse
import json
import ssl
import sys

ctx = ssl.create_default_context()

def test_connectivity():
    print("Testing connectivity to Socrata Chicago Open Data API...")
    resource_id = "wrvz-psew"
    base_url = f"https://data.cityofchicago.org/resource/{resource_id}.json"
    
    # Small date-filtered request
    params = {
        "$where": "trip_start_timestamp >= '2022-06-01T00:00:00' and trip_start_timestamp < '2022-07-01T00:00:00'",
        "$limit": 5,
        "$order": "trip_start_timestamp ASC, trip_id ASC"
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    print(f"URL: {url}")
    
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Downloader/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        headers = dict(resp.headers)
        status_code = resp.status
        body = resp.read().decode("utf-8")
        data = json.loads(body)
        
    print(f"Response Status: {status_code}")
    print(f"Records returned: {len(data)}")
    if data:
        print(f"Sample trip_id: {data[0].get('trip_id')}")
        print(f"Sample start_ts: {data[0].get('trip_start_timestamp')}")
    
    print("\nRelevant Response Headers:")
    for h in ["X-SODA2-Fields", "X-SODA2-Types", "X-Socrata-Region", "Access-Control-Allow-Origin", "Content-Type"]:
        if h in headers:
            print(f"  {h}: {headers[h]}")
            
    return len(data) == 5

if __name__ == "__main__":
    success = test_connectivity()
    if success:
        print("\nSUCCESS: Small date-filtered API request succeeded.")
    else:
        print("\nFAILURE: Small date-filtered API request returned unexpected result.")
        sys.exit(1)

