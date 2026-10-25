import json
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from pipeline.ingest.profile_raw import (
    parse_float,
    parse_int,
    parse_and_localize_timestamp,
    DatasetProfiler,
    CHICAGO_TZ,
    UTC_TZ,
)

def test_parse_float():
    assert parse_float("12.34") == 12.34
    assert parse_float(5) == 5.0
    assert parse_float("0") == 0.0
    assert parse_float("-4.5") == -4.5
    assert parse_float("") is None
    assert parse_float(None) is None
    assert parse_float("invalid") is None
    assert parse_float("nan") is None
    assert parse_float("inf") is None

def test_parse_int():
    assert parse_int("56") == 56
    assert parse_int("56.0") == 56
    assert parse_int(0) == 0
    assert parse_int("") is None
    assert parse_int(None) is None
    assert parse_int("abc") is None

def test_parse_and_localize_timestamp_chicago_to_utc():
    ts_str = "2022-06-01T00:15:00.000"
    dt_chi, dt_utc, aligned = parse_and_localize_timestamp(ts_str)
    
    assert dt_chi is not None
    assert dt_utc is not None
    assert aligned is True
    
    # In June, Chicago is on CDT (UTC-5)
    assert dt_chi.tzinfo == CHICAGO_TZ
    assert dt_chi.hour == 0
    assert dt_chi.minute == 15
    
    assert dt_utc.tzinfo == UTC_TZ
    assert dt_utc.hour == 5
    assert dt_utc.minute == 15
    assert dt_utc.isoformat() == "2022-06-01T05:15:00+00:00"

def test_parse_and_localize_timestamp_non_aligned():
    ts_str = "2022-06-01T14:07:22.000"
    dt_chi, dt_utc, aligned = parse_and_localize_timestamp(ts_str)
    assert dt_chi is not None
    assert aligned is False

def test_parse_and_localize_timestamp_invalid():
    dt_chi, dt_utc, aligned = parse_and_localize_timestamp("invalid-date")
    assert dt_chi is None
    assert dt_utc is None
    assert aligned is False
    
    dt_chi, dt_utc, aligned = parse_and_localize_timestamp(None)
    assert dt_chi is None
    assert dt_utc is None
    assert aligned is False

def test_dataset_profiler_line_processing():
    profiler = DatasetProfiler()
    
    # Record 1: Clean, valid record
    rec1 = {
        "trip_id": "tid001",
        "trip_start_timestamp": "2022-06-01T10:00:00.000",
        "pickup_community_area": "8",
        "pickup_centroid_latitude": "41.89",
        "pickup_centroid_longitude": "-87.63",
        "trip_miles": "2.5",
        "fare": "10.0",
        "tips": "2.0",
        "trip_seconds": "600"
    }
    
    # Record 2: Duplicate trip_id, zero miles, zero seconds, missing community area
    rec2 = {
        "trip_id": "tid001",  # duplicate
        "trip_start_timestamp": "2022-06-01T10:15:00.000",
        "pickup_community_area": None,
        "pickup_centroid_latitude": "41.89",
        "pickup_centroid_longitude": "-87.63",
        "trip_miles": "0",
        "fare": "5.0",
        "tips": "0",
        "trip_seconds": "0"
    }
    
    # Record 3: Community area only (no coordinates), negative fare
    rec3 = {
        "trip_id": "tid002",
        "trip_start_timestamp": "2022-06-01T10:30:00.000",
        "pickup_community_area": "32",
        "pickup_centroid_latitude": None,
        "pickup_centroid_longitude": None,
        "trip_miles": "1.0",
        "fare": "-2.5",
        "tips": "0",
        "trip_seconds": "300"
    }
    
    # Record 4: Invalid JSON
    profiler.process_line(json.dumps(rec1))
    profiler.process_line(json.dumps(rec2))
    profiler.process_line(json.dumps(rec3))
    profiler.process_line("INVALID NOT A JSON")
    
    summary = profiler.get_summary()
    
    assert summary["total_records"] == 4
    assert summary["invalid_json_count"] == 1
    
    # trip_id audit
    t_audit = summary["trip_id_audit"]
    assert t_audit["unique_count"] == 2
    assert t_audit["duplicate_count"] == 1
    assert t_audit["missing_count"] == 0
    assert t_audit["supports_deterministic_event_id"] is False
    
    # Geography audit
    g_audit = summary["geography_audit"]
    assert g_audit["usable_coordinates_count"] == 2
    assert g_audit["community_area_only_count"] == 1
    assert g_audit["both_coords_and_community"] == 1
    assert g_audit["coords_present_community_missing"] == 1
    assert g_audit["distinct_pickup_coordinates_count"] == 1
    
    # Metrics audit
    m_audit = summary["metrics_audit"]
    assert m_audit["trip_miles"]["positive_count"] == 2
    assert m_audit["trip_miles"]["zero_or_negative_count"] == 1
    assert m_audit["trip_seconds"]["positive_count"] == 2
    assert m_audit["trip_seconds"]["zero_or_negative_count"] == 1
    assert m_audit["fare"]["negative_count"] == 1
    assert m_audit["fare"]["positive_count"] == 2

