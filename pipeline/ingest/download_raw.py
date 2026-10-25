import urllib.request
import urllib.parse
import json
import ssl
import time
import os
import hashlib
from datetime import datetime, timedelta

DATASET_ID = "wrvz-psew"
BASE_URL = f"https://data.cityofchicago.org/resource/{DATASET_ID}.json"
RAW_DIR = os.path.join("data", "raw")
DAILY_DIR = os.path.join(RAW_DIR, "daily")
MANIFEST_PATH = os.path.join(RAW_DIR, "download_manifest.json")
FINAL_OUTPUT_PATH = os.path.join(RAW_DIR, "chicago_taxi_trips_2022-06.jsonl")

PAGE_SIZE = 10000
MAX_RETRIES = 5
EXPECTED_TOTAL_COUNT = 639269

ctx = ssl.create_default_context()

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def make_request_with_retry(params):
    qs = urllib.parse.urlencode(params)
    url = f"{BASE_URL}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "RideIntel-Downloader/1.0"})
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data
                else:
                    print(f"  [Attempt {attempt}] Unexpected HTTP status {resp.status}")
        except Exception as e:
            print(f"  [Attempt {attempt}] Request error: {e}")
            if attempt < MAX_RETRIES:
                sleep_sec = 2 ** attempt
                print(f"  Backing off for {sleep_sec}s...")
                time.sleep(sleep_sec)
            else:
                raise e
    raise RuntimeError(f"Failed to fetch data after {MAX_RETRIES} attempts: {url}")

def get_day_expected_count(day_start_iso, day_end_iso):
    params = {
        "$where": f"trip_start_timestamp >= '{day_start_iso}' and trip_start_timestamp < '{day_end_iso}'",
        "$select": "count(trip_id) as total_trips"
    }
    data = make_request_with_retry(params)
    if data and len(data) > 0:
        return int(data[0].get("total_trips", 0))
    return 0

def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_manifest(manifest):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

def download_day(day_str, day_start_iso, day_end_iso, manifest):
    out_file = os.path.join(DAILY_DIR, f"taxi_trips_{day_str}.jsonl")
    tmp_file = out_file + ".tmp"
    
    # Check if already completed
    if day_str in manifest and manifest[day_str].get("status") == "COMPLETED":
        if os.path.exists(out_file):
            actual_lines = sum(1 for _ in open(out_file, "r", encoding="utf-8"))
            if actual_lines == manifest[day_str].get("count"):
                print(f"[{day_str}] Already downloaded and verified ({actual_lines} rows). Skipping.")
                return manifest[day_str]["count"]
    
    print(f"\n[{day_str}] Querying expected count for {day_start_iso} to {day_end_iso}...")
    expected_count = get_day_expected_count(day_start_iso, day_end_iso)
    print(f"[{day_str}] Expected trips: {expected_count}")
    
    offset = 0
    records_written = 0
    seen_trip_ids = set()
    duplicate_count = 0
    
    with open(tmp_file, "w", encoding="utf-8") as out_f:
        while True:
            params = {
                "$where": f"trip_start_timestamp >= '{day_start_iso}' and trip_start_timestamp < '{day_end_iso}'",
                "$limit": PAGE_SIZE,
                "$offset": offset,
                "$order": "trip_start_timestamp ASC, trip_id ASC"
            }
            print(f"[{day_str}] Fetching offset {offset} (limit {PAGE_SIZE})...")
            t0 = time.time()
            page = make_request_with_retry(params)
            t1 = time.time()
            page_len = len(page)
            print(f"[{day_str}] Received {page_len} rows in {t1 - t0:.2f}s")
            
            if page_len == 0:
                break
                
            for rec in page:
                tid = rec.get("trip_id")
                if tid:
                    if tid in seen_trip_ids:
                        duplicate_count += 1
                    else:
                        seen_trip_ids.add(tid)
                out_f.write(json.dumps(rec) + "\n")
                records_written += 1
                
            offset += page_len
            if page_len < PAGE_SIZE:
                break
                
            # Brief pause to respect API rate limits
            time.sleep(0.5)

    if records_written != expected_count:
        raise ValueError(
            f"[{day_str}] Count mismatch! Expected {expected_count}, wrote {records_written}."
        )

    # Atomic rename
    if os.path.exists(out_file):
        os.remove(out_file)
    os.rename(tmp_file, out_file)
    
    sha256 = compute_sha256(out_file)
    manifest[day_str] = {
        "status": "COMPLETED",
        "day_start": day_start_iso,
        "day_end": day_end_iso,
        "count": records_written,
        "unique_trip_ids": len(seen_trip_ids),
        "duplicates_in_day": duplicate_count,
        "sha256": sha256,
        "completed_at": datetime.utcnow().isoformat() + "Z"
    }
    save_manifest(manifest)
    print(f"[{day_str}] Successfully verified and saved {records_written} rows (SHA-256: {sha256[:12]}...).")
    return records_written

def run_download():
    os.makedirs(DAILY_DIR, exist_ok=True)
    manifest = load_manifest()
    
    start_date = datetime(2022, 6, 1)
    end_date = datetime(2022, 7, 1)
    
    cur_date = start_date
    total_downloaded = 0
    
    print(f"=== STARTING RESUMABLE DOWNLOAD FOR INTERVAL [{start_date.date()} to {end_date.date()}) ===")
    while cur_date < end_date:
        next_date = cur_date + timedelta(days=1)
        day_str = cur_date.strftime("%Y-%m-%d")
        day_start_iso = cur_date.strftime("%Y-%m-%dT00:00:00")
        day_end_iso = next_date.strftime("%Y-%m-%dT00:00:00")
        
        day_count = download_day(day_str, day_start_iso, day_end_iso, manifest)
        total_downloaded += day_count
        cur_date = next_date
        
    print(f"\nAll daily slices completed. Total rows verified across days: {total_downloaded}")
    if total_downloaded != EXPECTED_TOTAL_COUNT:
        raise ValueError(f"CRITICAL DISCREPANCY: Total downloaded ({total_downloaded}) != Expected ({EXPECTED_TOTAL_COUNT})")

    # Combine into single canonical raw file
    print(f"\nCombining daily files into {FINAL_OUTPUT_PATH}...")
    combined_rows = 0
    all_seen_trip_ids = set()
    global_duplicates = 0
    
    with open(FINAL_OUTPUT_PATH, "w", encoding="utf-8") as out_f:
        cur_date = start_date
        while cur_date < end_date:
            day_str = cur_date.strftime("%Y-%m-%d")
            day_file = os.path.join(DAILY_DIR, f"taxi_trips_{day_str}.jsonl")
            with open(day_file, "r", encoding="utf-8") as in_f:
                for line in in_f:
                    if line.strip():
                        rec = json.loads(line)
                        tid = rec.get("trip_id")
                        if tid:
                            if tid in all_seen_trip_ids:
                                global_duplicates += 1
                            else:
                                all_seen_trip_ids.add(tid)
                        out_f.write(line)
                        combined_rows += 1
            cur_date += timedelta(days=1)
            
    final_sha256 = compute_sha256(FINAL_OUTPUT_PATH)
    final_size_bytes = os.path.getsize(FINAL_OUTPUT_PATH)
    final_size_mb = final_size_bytes / (1024 * 1024)
    
    print("\n=======================================================")
    print("VERIFICATION SUMMARY")
    print("=======================================================")
    print(f"Target interval: [2022-06-01T00:00:00, 2022-07-01T00:00:00)")
    print(f"Final file: {FINAL_OUTPUT_PATH}")
    print(f"File size: {final_size_bytes:,} bytes ({final_size_mb:.2f} MB)")
    print(f"Total rows written: {combined_rows:,}")
    print(f"Expected count: {EXPECTED_TOTAL_COUNT:,}")
    print(f"Unique trip IDs: {len(all_seen_trip_ids):,}")
    print(f"Duplicate trip IDs encountered: {global_duplicates}")
    print(f"SHA-256 Checksum: {final_sha256}")
    
    # Save verification report in docs/evidence/
    evidence_report = {
        "dataset_id": DATASET_ID,
        "date_interval": "[2022-06-01T00:00:00, 2022-07-01T00:00:00)",
        "expected_count": EXPECTED_TOTAL_COUNT,
        "actual_count": combined_rows,
        "count_verified": combined_rows == EXPECTED_TOTAL_COUNT,
        "unique_trip_ids": len(all_seen_trip_ids),
        "global_duplicates": global_duplicates,
        "file_path": FINAL_OUTPUT_PATH,
        "file_size_bytes": final_size_bytes,
        "file_size_mb": round(final_size_mb, 2),
        "sha256_checksum": final_sha256,
        "timestamp_utc": datetime.utcnow().isoformat() + "Z"
    }
    evidence_path = os.path.join("docs", "evidence", "raw_download_verification.json")
    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump(evidence_report, f, indent=2)
    print(f"Saved verification evidence to {evidence_path}")

if __name__ == "__main__":
    run_download()

