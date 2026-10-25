import json
import os
import tempfile
import pyarrow.parquet as pq
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from pipeline.ingest.clean import (
    CleaningPipeline,
    compute_event_id,
    parse_and_localize_timestamp,
    START_UTC,
    END_UTC,
    CHICAGO_TZ,
    UTC_TZ,
    DEFAULT_EVIDENCE_PATH,
    DEFAULT_AUDIT_REPORT_PATH
)
import hashlib

def test_compute_event_id():
    dataset_id = "wrvz-psew"
    trip_id = "1331f7a37850d9673b465e85cffa6c369d5cf5af"
    event_id = compute_event_id(dataset_id, trip_id)
    assert event_id == "ff02be5e897d08e2a23776d00ce17c73fa8960aa"
    assert len(event_id) == 40

def test_timestamp_localization_and_interval():
    # Inside interval
    ts_in = "2022-06-01T00:00:00.000"
    dt_chi, dt_utc, aligned = parse_and_localize_timestamp(ts_in)
    assert dt_chi is not None
    assert dt_utc == START_UTC
    assert aligned is True
    
    ts_last = "2022-06-30T23:45:00.000"
    dt_chi_last, dt_utc_last, _ = parse_and_localize_timestamp(ts_last)
    assert START_UTC <= dt_utc_last < END_UTC
    
    # Boundary: July 1 00:00:00 CDT is exclusive
    ts_boundary = "2022-07-01T00:00:00.000"
    _, dt_utc_boundary, _ = parse_and_localize_timestamp(ts_boundary)
    assert dt_utc_boundary == END_UTC
    assert not (START_UTC <= dt_utc_boundary < END_UTC)

def test_pipeline_unit_record_evaluation():
    pipeline = CleaningPipeline(raw_path="dummy.jsonl")
    
    # 1. Invalid JSON
    clean_rec, excl_rec = pipeline.evaluate_record(1, "NOT VALID JSON")
    assert clean_rec is None
    assert excl_rec["primary_exclusion_reason"] == "EXCLUDE_INVALID_JSON"
    assert excl_rec["precedence_rank"] == 1
    
    # 2. Missing trip_id
    rec_missing_id = {
        "trip_id": "",
        "trip_start_timestamp": "2022-06-01T10:00:00.000",
        "pickup_centroid_latitude": "41.89",
        "pickup_centroid_longitude": "-87.63"
    }
    clean_rec, excl_rec = pipeline.evaluate_record(2, json.dumps(rec_missing_id))
    assert clean_rec is None
    assert excl_rec["primary_exclusion_reason"] == "EXCLUDE_MISSING_TRIP_ID"
    assert excl_rec["precedence_rank"] == 2
    
    # 3. Clean Record 1 (Both H3 & Community Area)
    rec_clean = {
        "trip_id": "T001",
        "trip_start_timestamp": "2022-06-01T10:00:00.000",
        "pickup_centroid_latitude": "41.89",
        "pickup_centroid_longitude": "-87.63",
        "pickup_community_area": "8",
        "trip_miles": "2.0",
        "trip_seconds": "500",
        "fare": "10.0",
        "tips": "2.0"
    }
    clean_rec, excl_rec = pipeline.evaluate_record(3, json.dumps(rec_clean))
    assert excl_rec is None
    assert clean_rec["trip_id"] == "T001"
    assert clean_rec["h3_eligible"] is True
    assert clean_rec["community_area_eligible"] is True
    assert clean_rec["flag_missing_community_area"] is False
    assert clean_rec["flag_invalid_miles"] is False
    assert clean_rec["flag_invalid_seconds"] is False
    assert clean_rec["flag_unusual_fare"] is False
    assert clean_rec["flag_zero_or_missing_tips"] is False
    
    # 4. Duplicate Record of T001
    clean_rec, excl_rec = pipeline.evaluate_record(4, json.dumps(rec_clean))
    assert clean_rec is None
    assert excl_rec["primary_exclusion_reason"] == "EXCLUDE_DUPLICATE_TRIP_ID"
    assert excl_rec["precedence_rank"] == 3
    
    # 5. Invalid Timestamp
    rec_bad_ts = {
        "trip_id": "T002",
        "trip_start_timestamp": "bad-date",
        "pickup_centroid_latitude": "41.89",
        "pickup_centroid_longitude": "-87.63"
    }
    clean_rec, excl_rec = pipeline.evaluate_record(5, json.dumps(rec_bad_ts))
    assert clean_rec is None
    assert excl_rec["primary_exclusion_reason"] == "EXCLUDE_INVALID_OR_MISSING_TIMESTAMP"
    assert excl_rec["precedence_rank"] == 4
    
    # 6. Out of Bounds Timestamp (July 2022)
    rec_oob = {
        "trip_id": "T003",
        "trip_start_timestamp": "2022-07-02T10:00:00.000",
        "pickup_centroid_latitude": "41.89",
        "pickup_centroid_longitude": "-87.63"
    }
    clean_rec, excl_rec = pipeline.evaluate_record(6, json.dumps(rec_oob))
    assert clean_rec is None
    assert excl_rec["primary_exclusion_reason"] == "EXCLUDE_OUT_OF_BOUNDS_TIMESTAMP"
    assert excl_rec["precedence_rank"] == 5
    
    # 7. No Spatial Reference (coords missing AND community area missing)
    rec_no_spatial = {
        "trip_id": "T004",
        "trip_start_timestamp": "2022-06-01T10:00:00.000",
        "pickup_centroid_latitude": None,
        "pickup_centroid_longitude": None,
        "pickup_community_area": None
    }
    clean_rec, excl_rec = pipeline.evaluate_record(7, json.dumps(rec_no_spatial))
    assert clean_rec is None
    assert excl_rec["primary_exclusion_reason"] == "EXCLUDE_NO_SPATIAL_REFERENCE"
    assert excl_rec["precedence_rank"] == 6
    
    # 8. H3-only (Coords present, community area null) with Quality Flags (0 miles, 0 seconds)
    rec_h3_only = {
        "trip_id": "T005",
        "trip_start_timestamp": "2022-06-01T10:00:00.000",
        "pickup_centroid_latitude": "41.89",
        "pickup_centroid_longitude": "-87.63",
        "pickup_community_area": None,
        "trip_miles": "0",
        "trip_seconds": "0",
        "fare": "0",
        "tips": "0"
    }
    clean_rec, excl_rec = pipeline.evaluate_record(8, json.dumps(rec_h3_only))
    assert excl_rec is None
    assert clean_rec["h3_eligible"] is True
    assert clean_rec["community_area_eligible"] is False
    assert clean_rec["flag_missing_community_area"] is True
    assert clean_rec["flag_invalid_miles"] is True
    assert clean_rec["flag_invalid_seconds"] is True
    assert clean_rec["flag_unusual_fare"] is True
    assert clean_rec["flag_zero_or_missing_tips"] is True

def test_pipeline_integration_small_dataset():
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_file = os.path.join(tmpdir, "test_raw.jsonl")
        clean_dir = os.path.join(tmpdir, "cleaned")
        exclude_dir = os.path.join(tmpdir, "excluded")
        
        records = [
            # 1. Valid both H3 and CA
            {"trip_id": "R001", "trip_start_timestamp": "2022-06-01T12:00:00.000", "pickup_centroid_latitude": "41.89", "pickup_centroid_longitude": "-87.63", "pickup_community_area": "8", "trip_miles": "1.0", "fare": "5.0"},
            # 2. Valid H3 only (community null)
            {"trip_id": "R002", "trip_start_timestamp": "2022-06-01T12:15:00.000", "pickup_centroid_latitude": "41.90", "pickup_centroid_longitude": "-87.65", "pickup_community_area": None, "trip_miles": "0", "fare": "5.0"},
            # 3. Duplicate R001 -> Excluded rank 3
            {"trip_id": "R001", "trip_start_timestamp": "2022-06-01T12:00:00.000", "pickup_centroid_latitude": "41.89", "pickup_centroid_longitude": "-87.63", "pickup_community_area": "8"},
            # 4. No coordinates and no community area -> Excluded rank 6
            {"trip_id": "R003", "trip_start_timestamp": "2022-06-01T12:30:00.000", "pickup_centroid_latitude": None, "pickup_centroid_longitude": None, "pickup_community_area": None},
            # 5. Out of bounds timestamp -> Excluded rank 5
            {"trip_id": "R004", "trip_start_timestamp": "2022-07-05T12:00:00.000", "pickup_centroid_latitude": "41.89", "pickup_centroid_longitude": "-87.63"}
        ]
        
        with open(raw_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
                
        # Pass evidence_path=None and audit_report_path=None to avoid polluting production reports
        pipeline = CleaningPipeline(raw_path=raw_file, clean_dir=clean_dir, exclude_dir=exclude_dir,
                                    evidence_path=None, audit_report_path=None)
        summary = pipeline.run()
        
        # Reconciliation checks
        assert summary["counts"]["raw_input_rows"] == 5
        assert summary["counts"]["included_demand_rows"] == 2
        assert summary["counts"]["excluded_rows_total"] == 3
        assert summary["reconciliation"]["discrepancy"] == 0
        assert summary["reconciliation"]["balanced"] is True
        
        # Geographic counts
        assert summary["overlapping_eligibility_counts"]["h3_eligible_rows"] == 2
        assert summary["overlapping_eligibility_counts"]["community_area_eligible_rows"] == 1
        assert summary["mutually_exclusive_groups"]["eligible_for_both"] == 1
        assert summary["mutually_exclusive_groups"]["h3_only"] == 1
        assert summary["mutually_exclusive_groups"]["community_area_only"] == 0
        assert summary["mutually_exclusive_groups"]["neither"] == 3
        assert summary["mutually_exclusive_groups"]["partition_sum"] == 5
        assert summary["mutually_exclusive_groups"]["partition_balanced"] is True
        
        # Verify Parquet files
        clean_pq = os.path.join(clean_dir, "cleaned_trips.parquet")
        exclude_pq = os.path.join(exclude_dir, "excluded_trips.parquet")
        
        clean_tbl = pq.read_table(clean_pq)
        exclude_tbl = pq.read_table(exclude_pq)
        
        assert clean_tbl.num_rows == 2
        assert exclude_tbl.num_rows == 3
        assert "event_id" in clean_tbl.schema.names
        assert "event_ts" in clean_tbl.schema.names
        assert "primary_exclusion_reason" in exclude_tbl.schema.names

def test_production_reports_not_polluted_by_testing():
    # Record existing hashes of production reports before test run
    def read_hash(filepath):
        if not os.path.exists(filepath):
            return None
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
            
    hash_evidence_before = read_hash(DEFAULT_EVIDENCE_PATH)
    hash_audit_before = read_hash(DEFAULT_AUDIT_REPORT_PATH)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_file = os.path.join(tmpdir, "test_raw.jsonl")
        clean_dir = os.path.join(tmpdir, "cleaned")
        exclude_dir = os.path.join(tmpdir, "excluded")
        
        with open(raw_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"trip_id": "T1", "trip_start_timestamp": "2022-06-01T12:00:00.000", "pickup_centroid_latitude": "41.89", "pickup_centroid_longitude": "-87.63"}) + "\n")
            
        pipeline = CleaningPipeline(raw_path=raw_file, clean_dir=clean_dir, exclude_dir=exclude_dir,
                                    evidence_path=None, audit_report_path=None)
        pipeline.run()
        
    hash_evidence_after = read_hash(DEFAULT_EVIDENCE_PATH)
    hash_audit_after = read_hash(DEFAULT_AUDIT_REPORT_PATH)
    
    assert hash_evidence_after == hash_evidence_before, "Production clean_run_summary.json must remain unchanged by testing!"
    assert hash_audit_after == hash_audit_before, "Production ingest_exclusion_audit.json must remain unchanged by testing!"

def test_all_exclusion_ranks_accounting_and_precedence():
    """Verify that every primary exclusion rank (1 to 6) is counted in neither exactly once."""
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_file = os.path.join(tmpdir, "test_exclusions.jsonl")
        clean_dir = os.path.join(tmpdir, "cleaned")
        exclude_dir = os.path.join(tmpdir, "excluded")
        
        lines = [
            # 1. Rank 1: Invalid JSON (blank line)
            "",
            # 2. Rank 1: Invalid JSON (malformed string)
            "NOT_A_JSON_STRING",
            # 3. Rank 2: Missing trip_id
            json.dumps({"trip_id": "", "trip_start_timestamp": "2022-06-01T12:00:00.000", "pickup_centroid_latitude": "41.89", "pickup_centroid_longitude": "-87.63"}),
            # 4. Clean baseline record (will be duplicated next)
            json.dumps({"trip_id": "DUP_ID", "trip_start_timestamp": "2022-06-01T12:00:00.000", "pickup_centroid_latitude": "41.89", "pickup_centroid_longitude": "-87.63", "pickup_community_area": "8"}),
            # 5. Rank 3: Duplicate trip_id
            json.dumps({"trip_id": "DUP_ID", "trip_start_timestamp": "2022-06-01T12:00:00.000", "pickup_centroid_latitude": "41.89", "pickup_centroid_longitude": "-87.63", "pickup_community_area": "8"}),
            # 6. Rank 4: Invalid/unparseable timestamp
            json.dumps({"trip_id": "BAD_TS", "trip_start_timestamp": "not-a-timestamp", "pickup_centroid_latitude": "41.89", "pickup_centroid_longitude": "-87.63"}),
            # 7. Rank 5: Out of bounds timestamp (July 2022)
            json.dumps({"trip_id": "OOB_TS", "trip_start_timestamp": "2022-07-02T12:00:00.000", "pickup_centroid_latitude": "41.89", "pickup_centroid_longitude": "-87.63"}),
            # 8. Rank 6: Missing all spatial reference
            json.dumps({"trip_id": "NO_GEO", "trip_start_timestamp": "2022-06-01T12:00:00.000", "pickup_centroid_latitude": None, "pickup_centroid_longitude": None, "pickup_community_area": None}),
            # 9. Multiple defects: Missing trip_id (Rank 2) + Bad timestamp (Rank 4) + No spatial (Rank 6)
            # Must be assigned Rank 2 (highest precedence)
            json.dumps({"trip_id": None, "trip_start_timestamp": "invalid", "pickup_centroid_latitude": None, "pickup_centroid_longitude": None})
        ]
        
        with open(raw_file, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
                
        pipeline = CleaningPipeline(raw_path=raw_file, clean_dir=clean_dir, exclude_dir=exclude_dir,
                                    evidence_path=None, audit_report_path=None)
        summary = pipeline.run()
        
        assert summary["counts"]["raw_input_rows"] == 9
        assert summary["counts"]["included_demand_rows"] == 1  # Only line 4 is clean
        assert summary["counts"]["excluded_rows_total"] == 8
        assert summary["reconciliation"]["discrepancy"] == 0
        assert summary["reconciliation"]["balanced"] is True
        
        # Verify primary exclusion breakdown
        assert summary["primary_exclusions"]["EXCLUDE_INVALID_JSON"] == 2
        assert summary["primary_exclusions"]["EXCLUDE_MISSING_TRIP_ID"] == 2  # Lines 3 and 9
        assert summary["primary_exclusions"]["EXCLUDE_DUPLICATE_TRIP_ID"] == 1
        assert summary["primary_exclusions"]["EXCLUDE_INVALID_OR_MISSING_TIMESTAMP"] == 1
        assert summary["primary_exclusions"]["EXCLUDE_OUT_OF_BOUNDS_TIMESTAMP"] == 1
        assert summary["primary_exclusions"]["EXCLUDE_NO_SPATIAL_REFERENCE"] == 1
        
        # Verify mutually exclusive partition
        groups = summary["mutually_exclusive_groups"]
        assert groups["eligible_for_both"] == 1
        assert groups["h3_only"] == 0
        assert groups["community_area_only"] == 0
        assert groups["neither"] == 8
        assert groups["partition_sum"] == 9
        assert groups["partition_balanced"] is True

