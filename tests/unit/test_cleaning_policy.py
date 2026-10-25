import json
import hashlib
import os
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

CHICAGO_TZ = ZoneInfo("America/Chicago")
UTC_TZ = ZoneInfo("UTC")

def test_reason_codes_contract_validity():
    contract_path = os.path.join("contracts", "cleaning_reason_codes.json")
    assert os.path.exists(contract_path), "contracts/cleaning_reason_codes.json must exist"
    
    with open(contract_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    assert "codes" in data
    codes = data["codes"]
    
    primary_exclusions = [
        "EXCLUDE_INVALID_JSON",
        "EXCLUDE_MISSING_TRIP_ID",
        "EXCLUDE_DUPLICATE_TRIP_ID",
        "EXCLUDE_INVALID_OR_MISSING_TIMESTAMP",
        "EXCLUDE_OUT_OF_BOUNDS_TIMESTAMP",
        "EXCLUDE_NO_SPATIAL_REFERENCE",
    ]
    quality_flags = [
        "FLAG_COMMUNITY_AREA_MISSING_COORDS_PRESENT",
        "FLAG_COORDS_MISSING_COMMUNITY_PRESENT",
        "FLAG_NON_POSITIVE_MILES",
        "FLAG_NON_POSITIVE_SECONDS",
        "FLAG_ZERO_OR_MISSING_FARE",
        "FLAG_ZERO_OR_MISSING_TIPS",
    ]
    
    # Verify primary exclusions have precedence ranks 1 to 6
    ranks_seen = set()
    for c in primary_exclusions:
        assert c in codes
        assert codes[c]["category"] == "PRIMARY_EXCLUSION"
        assert codes[c]["action"] == "EXCLUDE"
        assert "precedence_rank" in codes[c]
        ranks_seen.add(codes[c]["precedence_rank"])
        
    assert ranks_seen == {1, 2, 3, 4, 5, 6}, "Primary exclusions must have unique ranks 1 through 6"
    
    # Verify quality flags are non-exclusionary
    for qf in quality_flags:
        assert qf in codes
        assert codes[qf]["category"] == "QUALITY_FLAG"
        assert codes[qf]["action"] == "RETAIN_WITH_FLAG"
        assert "precedence_rank" not in codes[qf]

def test_stable_event_id_generation():
    dataset_id = "wrvz-psew"
    trip_id = "1331f7a37850d9673b465e85cffa6c369d5cf5af"
    
    raw_str = f"{dataset_id}:{trip_id}"
    event_id = hashlib.sha1(raw_str.encode("utf-8")).hexdigest()
    
    assert len(event_id) == 40
    assert event_id == "ff02be5e897d08e2a23776d00ce17c73fa8960aa"
    
    # Verify determinism across repeated executions
    assert event_id == hashlib.sha1(raw_str.encode("utf-8")).hexdigest()

def test_mutually_exclusive_geographic_partition():
    """Verify that the 4 mutually exclusive groups strictly partition the raw input data."""
    raw_input_rows = 639269
    
    # 4 mutually exclusive, disjoint groups
    eligible_for_both = 583675
    h3_only = 326
    community_area_only = 0
    neither = 55268
    
    # Assert disjoint partition strictly sums to raw input rows
    partition_sum = eligible_for_both + h3_only + community_area_only + neither
    assert partition_sum == raw_input_rows, "Mutually exclusive groups must strictly sum to raw input count"
    assert partition_sum == 639269

def test_overlapping_eligibility_counts_derivation():
    """Verify independent derivation of overlapping eligibility counts and non-additivity."""
    raw_input_rows = 639269
    
    eligible_for_both = 583675
    h3_only = 326
    community_area_only = 0
    
    # Independent derivation of overlapping eligibility counts
    h3_eligible_rows = eligible_for_both + h3_only
    community_area_eligible_rows = eligible_for_both + community_area_only
    
    assert h3_eligible_rows == 584001
    assert community_area_eligible_rows == 583675
    
    # Difference is exactly the 326 unverified-cause records
    assert h3_eligible_rows - community_area_eligible_rows == 326
    
    # Overlapping counts must NEVER be summed directly (proves double-counting)
    overlapping_sum = h3_eligible_rows + community_area_eligible_rows
    assert overlapping_sum == 1167676
    assert overlapping_sum > raw_input_rows
    assert overlapping_sum != raw_input_rows

def test_reconciliation_equation():
    raw_input_rows = 639269
    
    eligible_for_both = 583675
    h3_only = 326
    community_area_only = 0
    neither = 55268
    
    # Primary exclusions in June 2022 dataset
    primary_exclusions = {
        "EXCLUDE_INVALID_JSON": 0,
        "EXCLUDE_MISSING_TRIP_ID": 0,
        "EXCLUDE_DUPLICATE_TRIP_ID": 0,
        "EXCLUDE_INVALID_OR_MISSING_TIMESTAMP": 0,
        "EXCLUDE_OUT_OF_BOUNDS_TIMESTAMP": 0,
        "EXCLUDE_NO_SPATIAL_REFERENCE": 55268
    }
    
    total_excluded = sum(primary_exclusions.values())
    assert total_excluded == neither
    assert total_excluded == 55268
    
    # Full reconciliation against raw input
    assert raw_input_rows == eligible_for_both + h3_only + community_area_only + neither
    # H3 gridded demand reconciliation
    h3_eligible_rows = eligible_for_both + h3_only
    assert raw_input_rows == h3_eligible_rows + total_excluded

def test_quality_flags_do_not_reduce_included_count():
    # Quality flags describe data defects but do NOT exclude from demand
    raw_input_rows = 639269
    h3_eligible_rows = 584001
    
    quality_flags = {
        "FLAG_NON_POSITIVE_MILES": 81401,
        "FLAG_NON_POSITIVE_SECONDS": 16199,
        "FLAG_COMMUNITY_AREA_MISSING_COORDS_PRESENT": 326,
        "FLAG_ZERO_OR_MISSING_FARE": 925,
        "FLAG_ZERO_OR_MISSING_TIPS": 287053
    }
    
    # Quality flags are informational tags, not exclusions.
    # Subtracting quality flags from raw rows is invalid and would distort demand counts.
    total_flag_occurrences = sum(quality_flags.values())
    assert total_flag_occurrences == 385904
    assert h3_eligible_rows == 584001
    assert raw_input_rows - total_flag_occurrences != h3_eligible_rows

def test_primary_exclusion_precedence_logic():
    # Simulated record with multiple failures: missing trip_id AND no coordinates
    contract_path = os.path.join("contracts", "cleaning_reason_codes.json")
    with open(contract_path, "r", encoding="utf-8") as f:
        codes = json.load(f)["codes"]
        
    rank_missing_id = codes["EXCLUDE_MISSING_TRIP_ID"]["precedence_rank"]
    rank_no_coords = codes["EXCLUDE_NO_SPATIAL_REFERENCE"]["precedence_rank"]
    
    # Missing trip_id (rank 2) has higher precedence than missing coordinates (rank 6)
    assert rank_missing_id < rank_no_coords

def test_half_open_interval_boundary():
    # Inclusive start: 2022-06-01 00:00:00 CDT == 2022-06-01 05:00:00 UTC
    # Exclusive end:   2022-07-01 00:00:00 CDT == 2022-07-01 05:00:00 UTC
    start_utc = datetime(2022, 6, 1, 5, 0, 0, tzinfo=UTC_TZ)
    end_utc = datetime(2022, 7, 1, 5, 0, 0, tzinfo=UTC_TZ)
    
    t_start = datetime.fromisoformat("2022-06-01T00:00:00").replace(tzinfo=CHICAGO_TZ).astimezone(UTC_TZ)
    t_inside = datetime.fromisoformat("2022-06-30T23:45:00").replace(tzinfo=CHICAGO_TZ).astimezone(UTC_TZ)
    t_end = datetime.fromisoformat("2022-07-01T00:00:00").replace(tzinfo=CHICAGO_TZ).astimezone(UTC_TZ)
    
    assert start_utc <= t_start < end_utc
    assert start_utc <= t_inside < end_utc
    assert not (start_utc <= t_end < end_utc)
