import json
import os
import sys
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, Tuple, Set

CHICAGO_TZ = ZoneInfo("America/Chicago")
UTC_TZ = ZoneInfo("UTC")

# Bounding box for greater Chicago area
CHICAGO_LAT_MIN = 41.60
CHICAGO_LAT_MAX = 42.10
CHICAGO_LON_MIN = -87.95
CHICAGO_LON_MAX = -87.50

REQUIRED_FIELDS = [
    "trip_id",
    "trip_start_timestamp",
    "pickup_community_area",
    "pickup_centroid_latitude",
    "pickup_centroid_longitude",
    "trip_miles",
    "fare",
    "tips",
    "trip_seconds"
]

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
    """
    Parses Chicago local timestamp string, localizes to America/Chicago,
    and returns (dt_chicago, dt_utc, is_15min_aligned).
    """
    if not ts_str or not isinstance(ts_str, str):
        return None, None, False
    
    # Expected formats: YYYY-MM-DDTHH:MM:SS or YYYY-MM-DDTHH:MM:SS.fff
    ts_clean = ts_str.strip()
    try:
        # Handles ISO format like 2022-06-01T00:00:00 or with microseconds .000
        dt_naive = datetime.fromisoformat(ts_clean)
        # Localize to Chicago time
        dt_chicago = dt_naive.replace(tzinfo=CHICAGO_TZ)
        dt_utc = dt_chicago.astimezone(UTC_TZ)
        is_aligned = (dt_naive.minute in (0, 15, 30, 45)) and (dt_naive.second == 0) and (dt_naive.microsecond == 0)
        return dt_chicago, dt_utc, is_aligned
    except Exception:
        return None, None, False

class DatasetProfiler:
    def __init__(self):
        self.total_records = 0
        self.invalid_json_count = 0
        
        # Field presence / missingness
        self.field_missing = {f: 0 for f in REQUIRED_FIELDS}
        self.all_seen_fields: Set[str] = set()
        
        # trip_id tracking
        self.seen_trip_ids: Set[str] = set()
        self.duplicate_trip_ids = 0
        self.missing_trip_ids = 0
        
        # Timestamp metrics
        self.min_start_chicago: Optional[datetime] = None
        self.max_start_chicago: Optional[datetime] = None
        self.min_start_utc: Optional[datetime] = None
        self.max_start_utc: Optional[datetime] = None
        self.unparseable_start_ts = 0
        self.non_aligned_start_ts = 0
        
        # Geography metrics
        self.usable_coords = 0
        self.community_area_only = 0
        self.both_coords_and_community = 0
        self.coords_present_community_missing = 0
        self.missing_all_geography = 0
        
        self.wgs84_out_of_range = 0
        self.outside_chicago_bbox = 0
        self.unparseable_coords = 0
        self.distinct_pickup_coords: Set[Tuple[float, float]] = set()
        self.distinct_community_areas: Set[int] = set()
        
        # Trip metrics (miles, seconds, fare, tips)
        self.miles_missing = 0
        self.miles_zero_or_negative = 0
        self.miles_positive = 0
        self.miles_extreme = 0  # > 100 miles
        self.min_miles = float("inf")
        self.max_miles = float("-inf")
        self.sum_miles = 0.0
        
        self.seconds_missing = 0
        self.seconds_zero_or_negative = 0
        self.seconds_positive = 0
        self.seconds_extreme = 0  # > 86400 seconds
        self.min_seconds = float("inf")
        self.max_seconds = float("-inf")
        self.sum_seconds = 0.0
        
        self.fare_missing = 0
        self.fare_negative = 0
        self.fare_zero = 0
        self.fare_positive = 0
        self.min_fare = float("inf")
        self.max_fare = float("-inf")
        self.sum_fare = 0.0
        
        self.tips_missing = 0
        self.tips_negative = 0
        self.tips_zero = 0
        self.tips_positive = 0
        self.min_tips = float("inf")
        self.max_tips = float("-inf")
        self.sum_tips = 0.0

    def process_line(self, line: str) -> None:
        self.total_records += 1
        line_str = line.strip()
        if not line_str:
            self.invalid_json_count += 1
            return
            
        try:
            rec = json.loads(line_str)
        except Exception:
            self.invalid_json_count += 1
            return
            
        if not isinstance(rec, dict):
            self.invalid_json_count += 1
            return
            
        self.all_seen_fields.update(rec.keys())
        
        # 1. Check required fields presence & blankness
        for f in REQUIRED_FIELDS:
            val = rec.get(f)
            if val is None or val == "":
                self.field_missing[f] += 1
                
        # 2. trip_id analysis
        tid = rec.get("trip_id")
        if not tid or not str(tid).strip():
            self.missing_trip_ids += 1
        else:
            tid_str = str(tid).strip()
            if tid_str in self.seen_trip_ids:
                self.duplicate_trip_ids += 1
            else:
                self.seen_trip_ids.add(tid_str)
                
        # 3. Timestamp analysis
        start_ts = rec.get("trip_start_timestamp")
        dt_chi, dt_utc, aligned = parse_and_localize_timestamp(start_ts)
        if dt_chi is None:
            self.unparseable_start_ts += 1
        else:
            if not aligned:
                self.non_aligned_start_ts += 1
            if self.min_start_chicago is None or dt_chi < self.min_start_chicago:
                self.min_start_chicago = dt_chi
                self.min_start_utc = dt_utc
            if self.max_start_chicago is None or dt_chi > self.max_start_chicago:
                self.max_start_chicago = dt_chi
                self.max_start_utc = dt_utc
                
        # 4. Geography analysis
        lat_raw = rec.get("pickup_centroid_latitude")
        lon_raw = rec.get("pickup_centroid_longitude")
        comm_raw = rec.get("pickup_community_area")
        
        lat = parse_float(lat_raw)
        lon = parse_float(lon_raw)
        comm = parse_int(comm_raw)
        
        has_coords = (lat is not None and lon is not None)
        has_community = (comm is not None)
        
        if comm is not None:
            self.distinct_community_areas.add(comm)
            
        if lat_raw is not None and lon_raw is not None and not has_coords:
            self.unparseable_coords += 1
            
        if has_coords:
            self.usable_coords += 1
            # Check WGS84
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                self.wgs84_out_of_range += 1
            # Check Chicago bbox
            if not (CHICAGO_LAT_MIN <= lat <= CHICAGO_LAT_MAX and CHICAGO_LON_MIN <= lon <= CHICAGO_LON_MAX):
                self.outside_chicago_bbox += 1
            self.distinct_pickup_coords.add((lat, lon))
            
            if has_community:
                self.both_coords_and_community += 1
            else:
                self.coords_present_community_missing += 1
        else:
            if has_community:
                self.community_area_only += 1
            else:
                self.missing_all_geography += 1
                
        # 5. Trip metrics (miles, seconds, fare, tips)
        miles = parse_float(rec.get("trip_miles"))
        if miles is None:
            self.miles_missing += 1
        else:
            if miles <= 0:
                self.miles_zero_or_negative += 1
            else:
                self.miles_positive += 1
            if miles > 100.0:
                self.miles_extreme += 1
            self.min_miles = min(self.min_miles, miles)
            self.max_miles = max(self.max_miles, miles)
            self.sum_miles += miles
            
        secs = parse_float(rec.get("trip_seconds"))
        if secs is None:
            self.seconds_missing += 1
        else:
            if secs <= 0:
                self.seconds_zero_or_negative += 1
            else:
                self.seconds_positive += 1
            if secs > 86400.0:
                self.seconds_extreme += 1
            self.min_seconds = min(self.min_seconds, secs)
            self.max_seconds = max(self.max_seconds, secs)
            self.sum_seconds += secs
            
        fare = parse_float(rec.get("fare"))
        if fare is None:
            self.fare_missing += 1
        else:
            if fare < 0:
                self.fare_negative += 1
            elif fare == 0:
                self.fare_zero += 1
            else:
                self.fare_positive += 1
            self.min_fare = min(self.min_fare, fare)
            self.max_fare = max(self.max_fare, fare)
            self.sum_fare += fare
            
        tips = parse_float(rec.get("tips"))
        if tips is None:
            self.tips_missing += 1
        else:
            if tips < 0:
                self.tips_negative += 1
            elif tips == 0:
                self.tips_zero += 1
            else:
                self.tips_positive += 1
            self.min_tips = min(self.min_tips, tips)
            self.max_tips = max(self.max_tips, tips)
            self.sum_tips += tips

    def get_summary(self) -> Dict[str, Any]:
        n = self.total_records
        valid_n = n - self.invalid_json_count
        
        valid_miles_count = self.miles_positive + self.miles_zero_or_negative
        mean_miles = (self.sum_miles / valid_miles_count) if valid_miles_count > 0 else None
        
        valid_seconds_count = self.seconds_positive + self.seconds_zero_or_negative
        mean_seconds = (self.sum_seconds / valid_seconds_count) if valid_seconds_count > 0 else None
        
        valid_fare_count = self.fare_positive + self.fare_zero + self.fare_negative
        mean_fare = (self.sum_fare / valid_fare_count) if valid_fare_count > 0 else None
        
        valid_tips_count = self.tips_positive + self.tips_zero + self.tips_negative
        mean_tips = (self.sum_tips / valid_tips_count) if valid_tips_count > 0 else None

        return {
            "total_records": n,
            "invalid_json_count": self.invalid_json_count,
            "all_fields_observed": sorted(list(self.all_seen_fields)),
            "required_fields_confirmation": {
                f: {
                    "present": f in self.all_seen_fields,
                    "missing_count": self.field_missing[f],
                    "missing_pct": round(self.field_missing[f] / n * 100, 3) if n > 0 else 0.0
                }
                for f in REQUIRED_FIELDS
            },
            "trip_id_audit": {
                "total_records": n,
                "missing_count": self.missing_trip_ids,
                "unique_count": len(self.seen_trip_ids),
                "duplicate_count": self.duplicate_trip_ids,
                "supports_deterministic_event_id": (self.missing_trip_ids == 0 and self.duplicate_trip_ids == 0)
            },
            "timestamp_audit": {
                "unparseable_count": self.unparseable_start_ts,
                "non_15min_aligned_count": self.non_aligned_start_ts,
                "min_trip_start_chicago": self.min_start_chicago.isoformat() if self.min_start_chicago else None,
                "max_trip_start_chicago": self.max_start_chicago.isoformat() if self.max_start_chicago else None,
                "min_trip_start_utc": self.min_start_utc.isoformat() if self.min_start_utc else None,
                "max_trip_start_utc": self.max_start_utc.isoformat() if self.max_start_utc else None,
                "timezone_interpretation_rule": "Raw values represent America/Chicago local time. Must localize to America/Chicago before converting to UTC. Direct UTC interpretation introduces a 5-hour error (CDT = UTC-5)."
            },
            "geography_audit": {
                "usable_coordinates_count": self.usable_coords,
                "usable_coordinates_pct": round(self.usable_coords / n * 100, 3) if n > 0 else 0.0,
                "community_area_only_count": self.community_area_only,
                "community_area_only_pct": round(self.community_area_only / n * 100, 3) if n > 0 else 0.0,
                "both_coords_and_community": self.both_coords_and_community,
                "coords_present_community_missing": self.coords_present_community_missing,
                "missing_all_geography_count": self.missing_all_geography,
                "missing_all_geography_pct": round(self.missing_all_geography / n * 100, 3) if n > 0 else 0.0,
                "distinct_pickup_coordinates_count": len(self.distinct_pickup_coords),
                "distinct_community_areas_count": len(self.distinct_community_areas),
                "wgs84_out_of_range": self.wgs84_out_of_range,
                "outside_chicago_bbox": self.outside_chicago_bbox,
                "unparseable_coords": self.unparseable_coords,
                "spatial_representation_finding": "Coordinates represent centroid discretizations (predominantly Community Area centroids when tract is masked), NOT exact vehicle GPS tracks."
            },
            "metrics_audit": {
                "trip_miles": {
                    "missing_count": self.miles_missing,
                    "zero_or_negative_count": self.miles_zero_or_negative,
                    "positive_count": self.miles_positive,
                    "extreme_gt_100_count": self.miles_extreme,
                    "min": self.min_miles if self.min_miles != float("inf") else None,
                    "max": self.max_miles if self.max_miles != float("-inf") else None,
                    "mean": round(mean_miles, 2) if mean_miles is not None else None
                },
                "trip_seconds": {
                    "missing_count": self.seconds_missing,
                    "zero_or_negative_count": self.seconds_zero_or_negative,
                    "positive_count": self.seconds_positive,
                    "extreme_gt_24h_count": self.seconds_extreme,
                    "min": self.min_seconds if self.min_seconds != float("inf") else None,
                    "max": self.max_seconds if self.max_seconds != float("-inf") else None,
                    "mean": round(mean_seconds, 1) if mean_seconds is not None else None
                },
                "fare": {
                    "missing_count": self.fare_missing,
                    "negative_count": self.fare_negative,
                    "zero_count": self.fare_zero,
                    "positive_count": self.fare_positive,
                    "min": self.min_fare if self.min_fare != float("inf") else None,
                    "max": self.max_fare if self.max_fare != float("-inf") else None,
                    "mean": round(mean_fare, 2) if mean_fare is not None else None
                },
                "tips": {
                    "missing_count": self.tips_missing,
                    "negative_count": self.tips_negative,
                    "zero_count": self.tips_zero,
                    "positive_count": self.tips_positive,
                    "min": self.min_tips if self.min_tips != float("inf") else None,
                    "max": self.max_tips if self.max_tips != float("-inf") else None,
                    "mean": round(mean_tips, 2) if mean_tips is not None else None
                }
            }
        }

def profile_dataset(file_path: str) -> Dict[str, Any]:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Raw dataset not found at: {file_path}")
        
    profiler = DatasetProfiler()
    print(f"Streaming and profiling {file_path}...")
    
    with open(file_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            profiler.process_line(line)
            if idx % 100000 == 0:
                print(f"  Processed {idx:,} records...")
                
    summary = profiler.get_summary()
    return summary

def main():
    raw_path = os.path.join("data", "raw", "chicago_taxi_trips_2022-06.jsonl")
    evidence_dir = os.path.join("docs", "evidence")
    os.makedirs(evidence_dir, exist_ok=True)
    evidence_json = os.path.join(evidence_dir, "raw_profile.json")
    
    summary = profile_dataset(raw_path)
    
    # Save to JSON
    with open(evidence_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        
    print("\n=======================================================")
    print("RAW DATASET PROFILING SUMMARY (READ-ONLY AUDIT)")
    print("=======================================================")
    print(f"Source file: {raw_path}")
    print(f"Total records: {summary['total_records']:,}")
    print(f"Invalid JSON lines: {summary['invalid_json_count']}")
    
    print("\n--- 1. REQUIRED FIELDS AUDIT ---")
    for f, stats in summary["required_fields_confirmation"].items():
        print(f"  {f:28s}: Missing = {stats['missing_count']:6,d} ({stats['missing_pct']:5.2f}%)")
        
    print("\n--- 2. TRIP ID & DETERMINISM ---")
    t_audit = summary["trip_id_audit"]
    print(f"  Unique trip_ids: {t_audit['unique_count']:,}")
    print(f"  Duplicates: {t_audit['duplicate_count']}")
    print(f"  Missing: {t_audit['missing_count']}")
    print(f"  Supports sha1(dataset_id:trip_id): {t_audit['supports_deterministic_event_id']}")
    
    print("\n--- 3. TIMESTAMP RANGE & TIMEZONE ---")
    ts_audit = summary["timestamp_audit"]
    print(f"  Chicago Local Range: {ts_audit['min_trip_start_chicago']} to {ts_audit['max_trip_start_chicago']}")
    print(f"  UTC Range:           {ts_audit['min_trip_start_utc']} to {ts_audit['max_trip_start_utc']}")
    print(f"  Non-15min-aligned:   {ts_audit['non_15min_aligned_count']}")
    print(f"  Unparseable:         {ts_audit['unparseable_count']}")
    print(f"  Rule:                {ts_audit['timezone_interpretation_rule']}")
    
    print("\n--- 4. GEOGRAPHY & CENTROID AUDIT ---")
    g_audit = summary["geography_audit"]
    print(f"  Usable coordinates (lat & lon): {g_audit['usable_coordinates_count']:,} ({g_audit['usable_coordinates_pct']}%)")
    print(f"  Community-area-only:            {g_audit['community_area_only_count']:,} ({g_audit['community_area_only_pct']}%)")
    print(f"  Missing all geography:          {g_audit['missing_all_geography_count']:,} ({g_audit['missing_all_geography_pct']}%)")
    print(f"  Distinct pickup coords pairs:   {g_audit['distinct_pickup_coordinates_count']}")
    print(f"  Distinct community areas:       {g_audit['distinct_community_areas_count']}")
    print(f"  WGS84 out-of-range:             {g_audit['wgs84_out_of_range']}")
    print(f"  Outside Chicago bounding box:   {g_audit['outside_chicago_bbox']}")
    print(f"  Spatial Note:                   {g_audit['spatial_representation_finding']}")
    
    print("\n--- 5. METRICS DATA QUALITY ---")
    m_audit = summary["metrics_audit"]
    print(f"  Trip Miles   <= 0: {m_audit['trip_miles']['zero_or_negative_count']:,} | > 0: {m_audit['trip_miles']['positive_count']:,} | Max: {m_audit['trip_miles']['max']} | Mean: {m_audit['trip_miles']['mean']}")
    print(f"  Trip Seconds <= 0: {m_audit['trip_seconds']['zero_or_negative_count']:,} | > 0: {m_audit['trip_seconds']['positive_count']:,} | Max: {m_audit['trip_seconds']['max']} | Mean: {m_audit['trip_seconds']['mean']}")
    print(f"  Fare < 0: {m_audit['fare']['negative_count']} | == 0: {m_audit['fare']['zero_count']:,} | > 0: {m_audit['fare']['positive_count']:,} | Min: {m_audit['fare']['min']} | Max: {m_audit['fare']['max']}")
    print(f"  Tips < 0: {m_audit['tips']['negative_count']} | == 0: {m_audit['tips']['zero_count']:,} | > 0: {m_audit['tips']['positive_count']:,} | Max: {m_audit['tips']['max']}")
    
    print(f"\nSaved profiling evidence JSON to {evidence_json}")

if __name__ == "__main__":
    main()

