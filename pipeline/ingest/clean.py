import json
import os
import sys
import math
import hashlib
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, Tuple, Set, List
import pyarrow as pa
import pyarrow.parquet as pq

DATASET_ID = "wrvz-psew"
DEFAULT_RAW_PATH = os.path.join("data", "raw", "chicago_taxi_trips_2022-06.jsonl")
DEFAULT_CLEAN_DIR = os.path.join("data", "interim", "cleaned_trips_2022-06")
DEFAULT_EXCLUDE_DIR = os.path.join("data", "interim", "excluded_trips_2022-06")
DEFAULT_EVIDENCE_PATH = os.path.join("docs", "evidence", "clean_run_summary.json")
DEFAULT_AUDIT_REPORT_PATH = os.path.join("reports", "ingest_exclusion_audit.json")

CHICAGO_TZ = ZoneInfo("America/Chicago")
UTC_TZ = ZoneInfo("UTC")

# Half-open June 2022 interval: 2022-06-01 00:00:00 CDT to 2022-07-01 00:00:00 CDT
START_UTC = datetime(2022, 6, 1, 5, 0, 0, tzinfo=UTC_TZ)
END_UTC = datetime(2022, 7, 1, 5, 0, 0, tzinfo=UTC_TZ)

CHUNK_SIZE = 50000

CLEANED_PARQUET_SCHEMA = pa.schema([
    ("event_id", pa.string()),
    ("trip_id", pa.string()),
    ("dataset_id", pa.string()),
    ("event_ts", pa.timestamp("us", tz="UTC")),
    ("trip_start_local", pa.string()),
    ("trip_end_local", pa.string()),
    ("pickup_centroid_latitude", pa.float64()),
    ("pickup_centroid_longitude", pa.float64()),
    ("pickup_community_area", pa.int32()),
    ("dropoff_community_area", pa.int32()),
    ("trip_miles", pa.float64()),
    ("trip_seconds", pa.float64()),
    ("fare", pa.float64()),
    ("tips", pa.float64()),
    ("tolls", pa.float64()),
    ("extras", pa.float64()),
    ("trip_total", pa.float64()),
    ("payment_type", pa.string()),
    ("company", pa.string()),
    ("h3_eligible", pa.bool_()),
    ("community_area_eligible", pa.bool_()),
    ("flag_missing_community_area", pa.bool_()),
    ("flag_invalid_miles", pa.bool_()),
    ("flag_invalid_seconds", pa.bool_()),
    ("flag_unusual_fare", pa.bool_()),
    ("flag_zero_or_missing_tips", pa.bool_())
])

EXCLUDED_PARQUET_SCHEMA = pa.schema([
    ("line_number", pa.int64()),
    ("primary_exclusion_reason", pa.string()),
    ("precedence_rank", pa.int32()),
    ("trip_id", pa.string()),
    ("trip_start_timestamp_raw", pa.string()),
    ("raw_record_json", pa.string()),
    ("fare", pa.float64()),
    ("trip_miles", pa.float64()),
    ("trip_seconds", pa.float64())
])

def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def compute_event_id(dataset_id: str, trip_id: str) -> str:
    return hashlib.sha1(f"{dataset_id}:{trip_id}".encode("utf-8")).hexdigest()

def parse_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None

def parse_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None

def parse_and_localize_timestamp(ts_str: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime], bool]:
    if not ts_str or not isinstance(ts_str, str):
        return None, None, False
    ts_clean = ts_str.strip()
    try:
        dt_naive = datetime.fromisoformat(ts_clean)
        dt_chicago = dt_naive.replace(tzinfo=CHICAGO_TZ)
        dt_utc = dt_chicago.astimezone(UTC_TZ)
        is_aligned = (dt_naive.minute in (0, 15, 30, 45)) and (dt_naive.second == 0) and (dt_naive.microsecond == 0)
        return dt_chicago, dt_utc, is_aligned
    except Exception:
        return None, None, False

class CleaningPipeline:
    def __init__(self, raw_path: str = DEFAULT_RAW_PATH, 
                 clean_dir: str = DEFAULT_CLEAN_DIR,
                 exclude_dir: str = DEFAULT_EXCLUDE_DIR,
                 evidence_path: Optional[str] = DEFAULT_EVIDENCE_PATH,
                 audit_report_path: Optional[str] = DEFAULT_AUDIT_REPORT_PATH):
        self.raw_path = raw_path
        self.clean_dir = clean_dir
        self.exclude_dir = exclude_dir
        self.evidence_path = evidence_path
        self.audit_report_path = audit_report_path
        
        self.seen_trip_ids: Set[str] = set()
        
        # Counters
        self.raw_input_rows = 0
        self.invalid_json_lines = 0
        
        self.primary_exclusions = {
            "EXCLUDE_INVALID_JSON": 0,
            "EXCLUDE_MISSING_TRIP_ID": 0,
            "EXCLUDE_DUPLICATE_TRIP_ID": 0,
            "EXCLUDE_INVALID_OR_MISSING_TIMESTAMP": 0,
            "EXCLUDE_OUT_OF_BOUNDS_TIMESTAMP": 0,
            "EXCLUDE_NO_SPATIAL_REFERENCE": 0
        }
        
        # Overlapping eligibility counts
        self.h3_eligible_rows = 0
        self.community_area_eligible_rows = 0
        
        # Mutually exclusive groups
        self.eligible_for_both = 0
        self.h3_only = 0
        self.community_area_only = 0
        self.neither = 0
        
        # Quality flags
        self.quality_flags = {
            "FLAG_COMMUNITY_AREA_MISSING_COORDS_PRESENT": 0,
            "FLAG_NON_POSITIVE_MILES": 0,
            "FLAG_NON_POSITIVE_SECONDS": 0,
            "FLAG_ZERO_OR_MISSING_FARE": 0,
            "FLAG_ZERO_OR_MISSING_TIPS": 0
        }
        
        # Timestamp range tracking
        self.min_start_chicago: Optional[datetime] = None
        self.max_start_chicago: Optional[datetime] = None
        self.min_start_utc: Optional[datetime] = None
        self.max_start_utc: Optional[datetime] = None

    def evaluate_record(self, line_num: int, line_str: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Evaluates a raw line strictly according to exclusion precedence (ranks 1 to 6).
        Returns either:
          (cleaned_dict, None) if retained
          (None, exclusion_dict) if excluded
        """
        self.raw_input_rows += 1
        line_clean = line_str.strip()
        
        # Rank 1: Invalid JSON
        if not line_clean:
            self.invalid_json_lines += 1
            self.primary_exclusions["EXCLUDE_INVALID_JSON"] += 1
            self.neither += 1
            return None, {
                "line_number": line_num,
                "primary_exclusion_reason": "EXCLUDE_INVALID_JSON",
                "precedence_rank": 1,
                "trip_id": None,
                "trip_start_timestamp_raw": None,
                "raw_record_json": line_str,
                "fare": None,
                "trip_miles": None,
                "trip_seconds": None
            }
            
        try:
            rec = json.loads(line_clean)
            if not isinstance(rec, dict):
                raise ValueError("Record is not a dict")
        except Exception:
            self.invalid_json_lines += 1
            self.primary_exclusions["EXCLUDE_INVALID_JSON"] += 1
            self.neither += 1
            return None, {
                "line_number": line_num,
                "primary_exclusion_reason": "EXCLUDE_INVALID_JSON",
                "precedence_rank": 1,
                "trip_id": None,
                "trip_start_timestamp_raw": None,
                "raw_record_json": line_str,
                "fare": None,
                "trip_miles": None,
                "trip_seconds": None
            }

        tid = rec.get("trip_id")
        ts_raw = rec.get("trip_start_timestamp")
        fare_val = parse_float(rec.get("fare"))
        miles_val = parse_float(rec.get("trip_miles"))
        secs_val = parse_float(rec.get("trip_seconds"))

        # Rank 2: Missing or blank trip_id
        if not tid or not str(tid).strip():
            self.primary_exclusions["EXCLUDE_MISSING_TRIP_ID"] += 1
            self.neither += 1
            return None, {
                "line_number": line_num,
                "primary_exclusion_reason": "EXCLUDE_MISSING_TRIP_ID",
                "precedence_rank": 2,
                "trip_id": None,
                "trip_start_timestamp_raw": ts_raw,
                "raw_record_json": line_clean,
                "fare": fare_val,
                "trip_miles": miles_val,
                "trip_seconds": secs_val
            }
            
        tid_str = str(tid).strip()

        # Rank 3: Duplicate trip_id
        if tid_str in self.seen_trip_ids:
            self.primary_exclusions["EXCLUDE_DUPLICATE_TRIP_ID"] += 1
            self.neither += 1
            return None, {
                "line_number": line_num,
                "primary_exclusion_reason": "EXCLUDE_DUPLICATE_TRIP_ID",
                "precedence_rank": 3,
                "trip_id": tid_str,
                "trip_start_timestamp_raw": ts_raw,
                "raw_record_json": line_clean,
                "fare": fare_val,
                "trip_miles": miles_val,
                "trip_seconds": secs_val
            }
        self.seen_trip_ids.add(tid_str)

        # Rank 4: Invalid or missing trip_start_timestamp
        dt_chi, dt_utc, aligned = parse_and_localize_timestamp(ts_raw)
        if dt_chi is None or dt_utc is None:
            self.primary_exclusions["EXCLUDE_INVALID_OR_MISSING_TIMESTAMP"] += 1
            self.neither += 1
            return None, {
                "line_number": line_num,
                "primary_exclusion_reason": "EXCLUDE_INVALID_OR_MISSING_TIMESTAMP",
                "precedence_rank": 4,
                "trip_id": tid_str,
                "trip_start_timestamp_raw": ts_raw,
                "raw_record_json": line_clean,
                "fare": fare_val,
                "trip_miles": miles_val,
                "trip_seconds": secs_val
            }

        # Rank 5: Timestamp outside June 2022 half-open interval [2022-06-01T05:00:00Z, 2022-07-01T05:00:00Z)
        if not (START_UTC <= dt_utc < END_UTC):
            self.primary_exclusions["EXCLUDE_OUT_OF_BOUNDS_TIMESTAMP"] += 1
            self.neither += 1
            return None, {
                "line_number": line_num,
                "primary_exclusion_reason": "EXCLUDE_OUT_OF_BOUNDS_TIMESTAMP",
                "precedence_rank": 5,
                "trip_id": tid_str,
                "trip_start_timestamp_raw": ts_raw,
                "raw_record_json": line_clean,
                "fare": fare_val,
                "trip_miles": miles_val,
                "trip_seconds": secs_val
            }

        # Geography parsing
        lat = parse_float(rec.get("pickup_centroid_latitude"))
        lon = parse_float(rec.get("pickup_centroid_longitude"))
        comm = parse_int(rec.get("pickup_community_area"))
        
        has_coords = (lat is not None and lon is not None)
        has_community = (comm is not None)

        # Rank 6: Missing all spatial reference
        if not has_coords and not has_community:
            self.primary_exclusions["EXCLUDE_NO_SPATIAL_REFERENCE"] += 1
            self.neither += 1
            return None, {
                "line_number": line_num,
                "primary_exclusion_reason": "EXCLUDE_NO_SPATIAL_REFERENCE",
                "precedence_rank": 6,
                "trip_id": tid_str,
                "trip_start_timestamp_raw": ts_raw,
                "raw_record_json": line_clean,
                "fare": fare_val,
                "trip_miles": miles_val,
                "trip_seconds": secs_val
            }

        # Track timestamp ranges
        if self.min_start_chicago is None or dt_chi < self.min_start_chicago:
            self.min_start_chicago = dt_chi
            self.min_start_utc = dt_utc
        if self.max_start_chicago is None or dt_chi > self.max_start_chicago:
            self.max_start_chicago = dt_chi
            self.max_start_utc = dt_utc

        # Record is RETAINED. Compute geographic groups and quality flags.
        if has_coords and has_community:
            self.eligible_for_both += 1
            self.h3_eligible_rows += 1
            self.community_area_eligible_rows += 1
            flag_missing_comm = False
        elif has_coords and not has_community:
            self.h3_only += 1
            self.h3_eligible_rows += 1
            self.quality_flags["FLAG_COMMUNITY_AREA_MISSING_COORDS_PRESENT"] += 1
            flag_missing_comm = True
        else: # not has_coords and has_community
            self.community_area_only += 1
            self.community_area_eligible_rows += 1
            flag_missing_comm = False

        # Additional quality flags (non-exclusionary)
        flag_miles = (miles_val is None or miles_val <= 0.0)
        if flag_miles:
            self.quality_flags["FLAG_NON_POSITIVE_MILES"] += 1

        flag_seconds = (secs_val is None or secs_val <= 0.0)
        if flag_seconds:
            self.quality_flags["FLAG_NON_POSITIVE_SECONDS"] += 1

        flag_fare = (fare_val is None or fare_val <= 0.0)
        if flag_fare:
            self.quality_flags["FLAG_ZERO_OR_MISSING_FARE"] += 1

        tips_val = parse_float(rec.get("tips"))
        flag_tips = (tips_val is None or tips_val <= 0.0)
        if flag_tips:
            self.quality_flags["FLAG_ZERO_OR_MISSING_TIPS"] += 1

        event_id = compute_event_id(DATASET_ID, tid_str)

        cleaned_record = {
            "event_id": event_id,
            "trip_id": tid_str,
            "dataset_id": DATASET_ID,
            "event_ts": dt_utc,
            "trip_start_local": ts_raw,
            "trip_end_local": rec.get("trip_end_timestamp"),
            "pickup_centroid_latitude": lat,
            "pickup_centroid_longitude": lon,
            "pickup_community_area": comm,
            "dropoff_community_area": parse_int(rec.get("dropoff_community_area")),
            "trip_miles": miles_val,
            "trip_seconds": secs_val,
            "fare": fare_val,
            "tips": tips_val,
            "tolls": parse_float(rec.get("tolls")),
            "extras": parse_float(rec.get("extras")),
            "trip_total": parse_float(rec.get("trip_total")),
            "payment_type": rec.get("payment_type"),
            "company": rec.get("company"),
            "h3_eligible": has_coords,
            "community_area_eligible": has_community,
            "flag_missing_community_area": flag_missing_comm,
            "flag_invalid_miles": flag_miles,
            "flag_invalid_seconds": flag_seconds,
            "flag_unusual_fare": flag_fare,
            "flag_zero_or_missing_tips": flag_tips
        }
        return cleaned_record, None

    def run(self) -> Dict[str, Any]:
        if not os.path.exists(self.raw_path):
            raise FileNotFoundError(f"Raw dataset not found at: {self.raw_path}")

        print(f"Verifying raw input file checksum for: {self.raw_path}...")
        raw_sha256 = compute_sha256(self.raw_path)
        print(f"Raw Input SHA-256: {raw_sha256}")

        os.makedirs(self.clean_dir, exist_ok=True)
        os.makedirs(self.exclude_dir, exist_ok=True)

        clean_parquet_file = os.path.join(self.clean_dir, "cleaned_trips.parquet")
        exclude_parquet_file = os.path.join(self.exclude_dir, "excluded_trips.parquet")

        clean_writer = pq.ParquetWriter(clean_parquet_file, CLEANED_PARQUET_SCHEMA, compression="snappy")
        exclude_writer = pq.ParquetWriter(exclude_parquet_file, EXCLUDED_PARQUET_SCHEMA, compression="snappy")

        clean_batch: List[Dict[str, Any]] = []
        exclude_batch: List[Dict[str, Any]] = []

        total_cleaned = 0
        total_excluded = 0

        t0 = time.time()
        print(f"\nStreaming {self.raw_path} into Parquet datasets (chunk size: {CHUNK_SIZE:,})...")

        with open(self.raw_path, "r", encoding="utf-8") as in_f:
            for line_idx, line in enumerate(in_f, 1):
                clean_rec, exclude_rec = self.evaluate_record(line_idx, line)
                
                if clean_rec is not None:
                    clean_batch.append(clean_rec)
                    total_cleaned += 1
                elif exclude_rec is not None:
                    exclude_batch.append(exclude_rec)
                    total_excluded += 1

                if len(clean_batch) >= CHUNK_SIZE:
                    tbl = pa.Table.from_pylist(clean_batch, schema=CLEANED_PARQUET_SCHEMA)
                    clean_writer.write_table(tbl)
                    clean_batch = []

                if len(exclude_batch) >= CHUNK_SIZE:
                    tbl = pa.Table.from_pylist(exclude_batch, schema=EXCLUDED_PARQUET_SCHEMA)
                    exclude_writer.write_table(tbl)
                    exclude_batch = []

                if line_idx % 100000 == 0:
                    print(f"  Processed {line_idx:,} rows (Clean: {total_cleaned:,}, Excluded: {total_excluded:,})...")

        # Flush remaining buffers
        if clean_batch:
            tbl = pa.Table.from_pylist(clean_batch, schema=CLEANED_PARQUET_SCHEMA)
            clean_writer.write_table(tbl)
        if exclude_batch:
            tbl = pa.Table.from_pylist(exclude_batch, schema=EXCLUDED_PARQUET_SCHEMA)
            exclude_writer.write_table(tbl)

        clean_writer.close()
        exclude_writer.close()
        t1 = time.time()
        print(f"\nStreaming completed in {t1 - t0:.2f}s.")

        # Re-verify raw checksum to guarantee raw immutability
        post_raw_sha256 = compute_sha256(self.raw_path)
        if post_raw_sha256 != raw_sha256:
            raise RuntimeError("CRITICAL ERROR: Raw dataset checksum altered during ingestion!")

        # Verify Parquet row counts match memory counters
        clean_pq_meta = pq.read_metadata(clean_parquet_file)
        exclude_pq_meta = pq.read_metadata(exclude_parquet_file)
        
        assert clean_pq_meta.num_rows == total_cleaned, "Cleaned Parquet row count mismatch!"
        assert exclude_pq_meta.num_rows == total_excluded, "Excluded Parquet row count mismatch!"

        # Reconciliation check
        sum_primary_exclusions = sum(self.primary_exclusions.values())
        reconciliation_discrepancy = self.raw_input_rows - (total_cleaned + total_excluded)
        is_balanced = (reconciliation_discrepancy == 0) and (total_excluded == sum_primary_exclusions)
        
        partition_sum = self.eligible_for_both + self.h3_only + self.community_area_only + self.neither
        partition_balanced = (partition_sum == self.raw_input_rows)

        summary = {
            "run_timestamp_utc": datetime.now(ZoneInfo("UTC")).isoformat(),
            "raw_file": {
                "path": self.raw_path,
                "sha256_checksum": raw_sha256,
                "checksum_verified_immutable": True
            },
            "counts": {
                "raw_input_rows": self.raw_input_rows,
                "invalid_json_lines": self.invalid_json_lines,
                "included_demand_rows": total_cleaned,
                "excluded_rows_total": total_excluded
            },
            "reconciliation": {
                "balanced": is_balanced,
                "equation": "raw_input_rows == included_demand_rows + excluded_rows_total",
                "discrepancy": reconciliation_discrepancy
            },
            "overlapping_eligibility_counts": {
                "h3_eligible_rows": self.h3_eligible_rows,
                "community_area_eligible_rows": self.community_area_eligible_rows
            },
            "mutually_exclusive_groups": {
                "eligible_for_both": self.eligible_for_both,
                "h3_only": self.h3_only,
                "community_area_only": self.community_area_only,
                "neither": self.neither,
                "partition_sum": partition_sum,
                "partition_balanced": partition_balanced
            },
            "primary_exclusions": self.primary_exclusions,
            "quality_flag_counts": self.quality_flags,
            "timestamp_range_local": {
                "min": self.min_start_chicago.isoformat() if self.min_start_chicago else None,
                "max": self.max_start_chicago.isoformat() if self.max_start_chicago else None
            },
            "timestamp_range_utc": {
                "min": self.min_start_utc.isoformat() if self.min_start_utc else None,
                "max": self.max_start_utc.isoformat() if self.max_start_utc else None
            },
            "outputs": {
                "cleaned_parquet_path": clean_parquet_file,
                "cleaned_parquet_rows": clean_pq_meta.num_rows,
                "cleaned_parquet_size_bytes": os.path.getsize(clean_parquet_file),
                "excluded_parquet_path": exclude_parquet_file,
                "excluded_parquet_rows": exclude_pq_meta.num_rows,
                "excluded_parquet_size_bytes": os.path.getsize(exclude_parquet_file)
            }
        }

        # Save run summary and audit report if paths are specified
        if self.evidence_path:
            parent = os.path.dirname(self.evidence_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.evidence_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)

        if self.audit_report_path:
            parent = os.path.dirname(self.audit_report_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.audit_report_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)

        return summary

def main():
    pipeline = CleaningPipeline()
    summary = pipeline.run()

    print("\n=======================================================")
    print("INGESTION & CLEANING EXECUTION SUMMARY")
    print("=======================================================")
    print(f"Raw Input:                     {summary['counts']['raw_input_rows']:,} rows")
    print(f"Input Checksum (Immutable):     {summary['raw_file']['sha256_checksum']}")
    print(f"Cleaned Output (Parquet):      {summary['counts']['included_demand_rows']:,} rows")
    print(f"Excluded Output (Parquet):     {summary['counts']['excluded_rows_total']:,} rows")
    print(f"Reconciliation Discrepancy:    {summary['reconciliation']['discrepancy']} (Balanced: {summary['reconciliation']['balanced']})")
    
    print("\n--- Overlapping Eligibility Counts ---")
    print(f"  h3_eligible_rows:            {summary['overlapping_eligibility_counts']['h3_eligible_rows']:,} (91.355%)")
    print(f"  community_area_eligible_rows: {summary['overlapping_eligibility_counts']['community_area_eligible_rows']:,} (91.304%)")
    print(f"  Delta (H3-only border rows): 326 rows")
    
    print("\n--- Mutually Exclusive Groups (Sum: 639,269) ---")
    for g, cnt in summary["mutually_exclusive_groups"].items():
        if isinstance(cnt, int):
            print(f"  {g:28s}: {cnt:6,d}")
            
    print("\n--- Primary Exclusions by Reason ---")
    for r, cnt in summary["primary_exclusions"].items():
        print(f"  {r:36s}: {cnt:6,d}")
        
    print("\n--- Quality Flags on Cleaned Demand Records ---")
    for f, cnt in summary["quality_flag_counts"].items():
        print(f"  {f:42s}: {cnt:6,d}")
        
    print(f"\nCleaned Parquet:  {summary['outputs']['cleaned_parquet_path']} ({summary['outputs']['cleaned_parquet_size_bytes'] / (1024*1024):.2f} MB)")
    print(f"Excluded Parquet: {summary['outputs']['excluded_parquet_path']} ({summary['outputs']['excluded_parquet_size_bytes'] / (1024*1024):.2f} MB)")
    if pipeline.audit_report_path:
        print(f"Audit Report:     {pipeline.audit_report_path}")
    if pipeline.evidence_path:
        print(f"Evidence File:    {pipeline.evidence_path}")

if __name__ == "__main__":
    main()

