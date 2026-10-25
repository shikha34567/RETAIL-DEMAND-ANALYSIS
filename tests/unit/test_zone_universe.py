"""
Unit tests for pipeline.spatial.zone_universe module.
"""

import os
import math
import tempfile
import hashlib
from datetime import datetime, timezone
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.spatial.zone_universe import (
    ZoneUniverseBuilder,
    ZONE_UNIVERSE_PARQUET_SCHEMA,
    SELECTED_OPERATIONAL_THRESHOLD,
    SELECTED_RULE_NAME,
    DEFAULT_CLEANED_PARQUET,
    DEFAULT_EXCLUDED_PARQUET,
    DEFAULT_EVIDENCE_JSON,
    DEFAULT_EVIDENCE_MD,
    DEFAULT_PROCESSED_ZONE_PARQUET
)
from pipeline.ingest.clean import (
    DEFAULT_EVIDENCE_PATH as CLEAN_SUMMARY_PATH,
    DEFAULT_AUDIT_REPORT_PATH as CLEAN_AUDIT_PATH
)
from pipeline.spatial.compare_resolutions import (
    DEFAULT_EVIDENCE_JSON as H3_JSON_PATH,
    DEFAULT_EVIDENCE_MD as H3_MD_PATH
)


def test_zone_universe_schema_definition():
    names = ZONE_UNIVERSE_PARQUET_SCHEMA.names
    assert "h3_cell" in names
    assert "resolution" in names
    assert "rule" in names
    assert "trip_count_historical" in names
    assert "first_observed_utc" in names
    assert "last_observed_utc" in names
    assert "is_operational_universe" in names
    assert "qualification_reason" in names
    assert "dataset_period" in names
    assert "dataset_id" in names
    assert "provenance" in names


def test_deterministic_zone_inclusion_and_threshold_boundary():
    """Verify threshold boundary: 9 trips is excluded, 10 trips is included."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cleaned_pq = os.path.join(tmpdir, "cleaned.parquet")
        out_pq = os.path.join(tmpdir, "zone_universe.parquet")
        evidence_json = os.path.join(tmpdir, "evidence.json")
        evidence_md = os.path.join(tmpdir, "evidence.md")
        settings_yaml = os.path.join(tmpdir, "settings.yaml")

        with open(settings_yaml, "w", encoding="utf-8") as f:
            f.write("h3:\n  resolution: 8\n")

        # Create synthetic fixture:
        # Zone A (Loop: 41.88, -87.62): 10 trips -> QUALIFIED
        # Zone B (Lincoln Park: 41.92, -87.64): 9 trips -> EXCLUDED_BELOW_MIN_TRIPS (threshold boundary test)
        # Zone C (O'Hare: 41.982775, -87.877305): 15 trips -> QUALIFIED
        schema = pa.schema([
            ("event_id", pa.string()),
            ("trip_id", pa.string()),
            ("event_ts", pa.timestamp("us", tz="UTC")),
            ("pickup_centroid_latitude", pa.float64()),
            ("pickup_centroid_longitude", pa.float64()),
            ("pickup_community_area", pa.int32()),
            ("h3_eligible", pa.bool_()),
            ("flag_missing_community_area", pa.bool_())
        ])

        rows = []
        base_ts = datetime(2022, 6, 1, 12, 0, tzinfo=timezone.utc)
        
        # Zone A: 10 trips
        for i in range(10):
            rows.append({
                "event_id": f"evt_a_{i}",
                "trip_id": f"t_a_{i}",
                "event_ts": base_ts,
                "pickup_centroid_latitude": 41.881832,
                "pickup_centroid_longitude": -87.623177,
                "pickup_community_area": 8,
                "h3_eligible": True,
                "flag_missing_community_area": False
            })
            
        # Zone B: exactly 9 trips (below threshold of 10)
        for i in range(9):
            rows.append({
                "event_id": f"evt_b_{i}",
                "trip_id": f"t_b_{i}",
                "event_ts": base_ts,
                "pickup_centroid_latitude": 41.9214,
                "pickup_centroid_longitude": -87.6445,
                "pickup_community_area": 7,
                "h3_eligible": True,
                "flag_missing_community_area": False
            })
            
        # Zone C: 15 trips
        for i in range(15):
            rows.append({
                "event_id": f"evt_c_{i}",
                "trip_id": f"t_c_{i}",
                "event_ts": base_ts,
                "pickup_centroid_latitude": 41.982775009,
                "pickup_centroid_longitude": -87.8773054,
                "pickup_community_area": None,
                "h3_eligible": True,
                "flag_missing_community_area": True
            })

        tbl = pa.Table.from_pylist(rows, schema=schema)
        pq.write_table(tbl, cleaned_pq)

        builder = ZoneUniverseBuilder(
            cleaned_parquet_path=cleaned_pq,
            excluded_parquet_path="dummy.parquet",
            output_parquet_path=out_pq,
            evidence_json_path=evidence_json,
            evidence_md_path=evidence_md,
            settings_path=settings_yaml,
            resolution=8,
            operational_threshold=10
        )
        evidence = builder.build_and_evaluate()

        # Check total trips
        total_input = 10 + 9 + 15  # 34 trips
        assert evidence["metadata"]["total_eligible_trips"] == 34
        assert evidence["metadata"]["total_distinct_occupied_cells"] == 3

        op_rule = evidence["selected_operational_rule"]
        assert op_rule["retained_operational_zones"] == 2
        assert op_rule["excluded_dormant_zones"] == 1
        assert op_rule["retained_trips_count"] == 25  # 10 + 15
        assert op_rule["excluded_trips_count"] == 9   # 9 trips

        # Read exported Parquet and inspect
        out_tbl = pq.read_table(out_pq)
        assert len(out_tbl) == 3
        records = {r["h3_cell"]: r for r in out_tbl.to_pylist()}
        
        # Check boundary qualification
        for cell, r in records.items():
            if r["trip_count_historical"] == 9:
                assert r["is_operational_universe"] is False
                assert r["qualification_reason"] == "EXCLUDED_BELOW_MIN_TRIPS"
            elif r["trip_count_historical"] in (10, 15):
                assert r["is_operational_universe"] is True
                assert r["qualification_reason"] == "QUALIFIED_ACTIVE_ZONE"


def test_production_evidence_invariance_during_testing():
    """Verify that synthetic testing never mutates existing production evidence files."""
    def get_hash(path):
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    hashes_before = {
        "clean_summary": get_hash(CLEAN_SUMMARY_PATH),
        "clean_audit": get_hash(CLEAN_AUDIT_PATH),
        "h3_json": get_hash(H3_JSON_PATH),
        "h3_md": get_hash(H3_MD_PATH),
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        cleaned_pq = os.path.join(tmpdir, "cleaned.parquet")
        schema = pa.schema([
            ("event_id", pa.string()),
            ("trip_id", pa.string()),
            ("event_ts", pa.timestamp("us", tz="UTC")),
            ("pickup_centroid_latitude", pa.float64()),
            ("pickup_centroid_longitude", pa.float64()),
            ("pickup_community_area", pa.int32()),
            ("h3_eligible", pa.bool_()),
            ("flag_missing_community_area", pa.bool_())
        ])
        tbl = pa.Table.from_pylist([{
            "event_id": "e1",
            "trip_id": "t1",
            "event_ts": datetime(2022, 6, 1, 12, 0, tzinfo=timezone.utc),
            "pickup_centroid_latitude": 41.88,
            "pickup_centroid_longitude": -87.62,
            "pickup_community_area": 8,
            "h3_eligible": True,
            "flag_missing_community_area": False
        }], schema=schema)
        pq.write_table(tbl, cleaned_pq)

        builder = ZoneUniverseBuilder(
            cleaned_parquet_path=cleaned_pq,
            output_parquet_path=None,
            evidence_json_path=None,
            evidence_md_path=None,
            settings_path=None
        )
        builder.build_and_evaluate()

    for key, path in [
        ("clean_summary", CLEAN_SUMMARY_PATH),
        ("clean_audit", CLEAN_AUDIT_PATH),
        ("h3_json", H3_JSON_PATH),
        ("h3_md", H3_MD_PATH),
    ]:
        assert get_hash(path) == hashes_before[key], f"Evidence file {path} was modified during test run!"


def test_full_dataset_reconciliation_and_properties():
    """Verify reconciliation and properties on the real production cleaned dataset."""
    if not os.path.exists(DEFAULT_CLEANED_PARQUET):
        pytest.skip("Cleaned production dataset not found.")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_pq = os.path.join(tmpdir, "test_out.parquet")
        builder = ZoneUniverseBuilder(
            cleaned_parquet_path=DEFAULT_CLEANED_PARQUET,
            excluded_parquet_path=DEFAULT_EXCLUDED_PARQUET,
            output_parquet_path=out_pq,
            evidence_json_path=None,
            evidence_md_path=None,
            settings_path=None,
            resolution=8,
            operational_threshold=10
        )
        evidence = builder.build_and_evaluate()

        assert evidence["metadata"]["total_eligible_trips"] == 584001
        assert evidence["metadata"]["total_distinct_occupied_cells"] == 239

        op = evidence["selected_operational_rule"]
        assert op["retained_operational_zones"] == 139
        assert op["excluded_dormant_zones"] == 100
        assert op["retained_trips_count"] == 583659
        assert op["excluded_trips_count"] == 342
        assert op["retained_trips_count"] + op["excluded_trips_count"] == 584001
        assert math.isclose(op["retained_trips_coverage_pct"], 99.9414, abs_tol=1e-3)


def test_provisional_rule_and_metadata():
    """Verify that operational status is explicitly marked provisional and temporal leakage is documented."""
    if not os.path.exists(DEFAULT_CLEANED_PARQUET):
        pytest.skip("Cleaned production dataset not found.")

    with tempfile.TemporaryDirectory() as tmpdir:
        builder = ZoneUniverseBuilder(
            cleaned_parquet_path=DEFAULT_CLEANED_PARQUET,
            output_parquet_path=None,
            evidence_json_path=None,
            evidence_md_path=None,
            settings_path=None,
            resolution=8,
            operational_threshold=10
        )
        evidence = builder.build_and_evaluate()

        rule_info = evidence["selected_operational_rule"]
        assert rule_info["status"] == "PROVISIONAL_OPERATIONAL_CHOICE"
        assert "provisional operational choice" in rule_info["description"]
        assert "optimal" not in rule_info["description"].lower()

        leak = evidence.get("temporal_leakage_assessment")
        assert leak is not None

        # Verify retrospective scope warning
        assert leak["is_operational_universe_scope"] == "RETROSPECTIVE_FULL_MONTH"
        assert "must NOT be treated as leakage-safe" in leak["is_operational_universe_warning"]

        # Verify corrected CDT-aligned split
        demo = leak["leakage_sensitivity_demonstration"]
        assert demo["split_utc"] == "2022-06-22T05:00:00Z"
        assert demo["train_duration_days"] == 21.0
        assert demo["test_duration_days"] == 9.0
        assert demo["train_operational_zones_count"] == 135
        assert demo["full_month_operational_zones_count"] == 139
        assert demo["leaked_zones_count"] == 4

        # Verify dataset interval
        interval = leak["dataset_interval_utc"]
        assert interval["start_inclusive"] == "2022-06-01T05:00:00Z"
        assert interval["end_exclusive"] == "2022-07-01T05:00:00Z"
        assert interval["total_duration_hours"] == 720.0

        # Verify Phase 3 leakage-safe rule and downstream handling policy
        assert "t < T_split" in leak["phase3_leakage_safe_rule"]
        policy = leak["phase3_downstream_handling_policy"]
        assert "Included in zero-filling" in policy["zones_in_training_eligibility"]
        assert "Excluded from zero-filling" in policy["zones_absent_from_training_eligibility"]
        assert "All 239" in policy["catalog_preservation"]


def test_catalog_completeness_all_239_cells_preserved():
    """Verify all 239 observed cells are preserved in the catalog with explicit operational flags."""
    if not os.path.exists(DEFAULT_CLEANED_PARQUET):
        pytest.skip("Cleaned production dataset not found.")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_pq = os.path.join(tmpdir, "zone_universe.parquet")
        builder = ZoneUniverseBuilder(
            cleaned_parquet_path=DEFAULT_CLEANED_PARQUET,
            output_parquet_path=out_pq,
            evidence_json_path=None,
            evidence_md_path=None,
            settings_path=None,
            resolution=8,
            operational_threshold=10
        )
        builder.build_and_evaluate()

        tbl = pq.read_table(out_pq)
        assert len(tbl) == 239

        records = tbl.to_pylist()
        op_zones = [r for r in records if r["is_operational_universe"]]
        dormant_zones = [r for r in records if not r["is_operational_universe"]]

        assert len(op_zones) == 139
        assert len(dormant_zones) == 100

        for r in op_zones:
            assert r["trip_count_historical"] >= 10
            assert r["qualification_reason"] == "QUALIFIED_ACTIVE_ZONE"

        for r in dormant_zones:
            assert r["trip_count_historical"] < 10
            assert r["qualification_reason"] == "EXCLUDED_BELOW_MIN_TRIPS"

        assert sum(r["trip_count_historical"] for r in records) == 584001


def test_temporal_leakage_sensitivity_cdt_aligned():
    """Verify temporal lookahead sensitivity using CDT-aligned split (midnight CDT = 05:00Z).

    The dataset interval is [2022-06-01T05:00:00Z, 2022-07-01T05:00:00Z).
    The CDT-aligned split at 2022-06-22T05:00:00Z produces exactly 21 train + 9 test local days.
    Four zones qualify under >=10 threshold only because test-period trips push them over.
    """
    if not os.path.exists(DEFAULT_CLEANED_PARQUET):
        pytest.skip("Cleaned production dataset not found.")

    from pipeline.spatial.h3_index import coords_to_h3
    from collections import Counter

    tbl = pq.read_table(DEFAULT_CLEANED_PARQUET, columns=["event_ts", "pickup_centroid_latitude", "pickup_centroid_longitude"])
    tss = tbl["event_ts"].to_pylist()
    lats = tbl["pickup_centroid_latitude"].to_pylist()
    lons = tbl["pickup_centroid_longitude"].to_pylist()

    # CDT-aligned split: midnight CDT June 22 = 2022-06-22T05:00:00Z
    split_utc = datetime(2022, 6, 22, 5, 0, 0, tzinfo=timezone.utc)

    train_counts = Counter()
    full_counts = Counter()

    for ts, lat, lon in zip(tss, lats, lons):
        cell = coords_to_h3(lat, lon, 8)
        if cell is None:
            continue
        full_counts[cell] += 1
        if ts < split_utc:
            train_counts[cell] += 1

    train_operational = {c for c, cnt in train_counts.items() if cnt >= 10}
    full_operational = {c for c, cnt in full_counts.items() if cnt >= 10}

    assert len(full_operational) == 139
    assert len(train_operational) == 135

    leaked = full_operational - train_operational
    assert len(leaked) == 4
    expected_leaked = {"882664528bfffff", "882664cf4bfffff", "882664d89dfffff", "882664d8d5fffff"}
    assert leaked == expected_leaked

    # Verify that leaked zones had <10 training trips and >=10 full-month trips
    for cell in leaked:
        assert train_counts[cell] < 10, f"Leaked zone {cell} should have <10 training trips"
        assert full_counts[cell] >= 10, f"Leaked zone {cell} should have >=10 full-month trips"

    # Verify specific training trip counts (OBSERVED from data)
    expected_train_trips = {
        "882664528bfffff": 7,
        "882664cf4bfffff": 8,
        "882664d89dfffff": 7,
        "882664d8d5fffff": 5,
    }
    for cell, expected_count in expected_train_trips.items():
        assert train_counts[cell] == expected_count, (
            f"Zone {cell}: expected {expected_count} training trips, got {train_counts[cell]}"
        )


def test_half_open_interval_and_split_durations():
    """Verify that the dataset half-open interval and CDT-aligned split produce exact durations."""
    from datetime import timedelta

    # Dataset interval boundaries from pipeline/ingest/clean.py
    ds_start = datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc)   # 2022-06-01 00:00:00 CDT
    ds_end = datetime(2022, 7, 1, 5, 0, 0, tzinfo=timezone.utc)     # 2022-07-01 00:00:00 CDT

    # Total dataset duration: exactly 30 days
    total_duration = ds_end - ds_start
    assert total_duration == timedelta(days=30)
    assert total_duration.total_seconds() == 720 * 3600  # 720 hours

    # CDT-aligned split at midnight CDT June 22
    split_utc = datetime(2022, 6, 22, 5, 0, 0, tzinfo=timezone.utc)

    train_duration = split_utc - ds_start
    test_duration = ds_end - split_utc

    # Exactly 21 train days + 9 test days
    assert train_duration == timedelta(days=21)
    assert test_duration == timedelta(days=9)
    assert train_duration + test_duration == total_duration

    # Verify that midnight UTC (the OLD split) does NOT produce integer days
    old_split = datetime(2022, 6, 22, 0, 0, 0, tzinfo=timezone.utc)
    old_train = old_split - ds_start
    old_test = ds_end - old_split
    assert old_train != timedelta(days=21), "Midnight UTC split should NOT yield 21 days"
    assert old_test != timedelta(days=9), "Midnight UTC split should NOT yield 9 days"
    assert old_train == timedelta(days=20, hours=19)
    assert old_test == timedelta(days=9, hours=5)


def test_is_operational_universe_is_retrospective_full_month():
    """Verify that is_operational_universe reflects full-month retrospective status,
    not training-window eligibility. The 4 leaked zones are marked operational
    even though they would not qualify under training-only evaluation."""
    if not os.path.exists(DEFAULT_CLEANED_PARQUET):
        pytest.skip("Cleaned production dataset not found.")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_pq = os.path.join(tmpdir, "zone_universe.parquet")
        builder = ZoneUniverseBuilder(
            cleaned_parquet_path=DEFAULT_CLEANED_PARQUET,
            output_parquet_path=out_pq,
            evidence_json_path=None,
            evidence_md_path=None,
            settings_path=None,
            resolution=8,
            operational_threshold=10
        )
        builder.build_and_evaluate()

        tbl = pq.read_table(out_pq)
        records = {r["h3_cell"]: r for r in tbl.to_pylist()}

        # The 4 leaked zones are marked is_operational_universe=True based on full-month data
        leaked_zones = ["882664528bfffff", "882664cf4bfffff", "882664d89dfffff", "882664d8d5fffff"]
        for cell in leaked_zones:
            assert cell in records, f"Leaked zone {cell} should be in catalog"
            assert records[cell]["is_operational_universe"] is True, (
                f"Leaked zone {cell} should be retrospectively operational (full-month)"
            )
            # But their full-month counts are 10-15 trips, barely above threshold
            assert records[cell]["trip_count_historical"] >= 10
            assert records[cell]["trip_count_historical"] <= 15

        # All records have provenance HISTORICAL
        for r in records.values():
            assert r["provenance"] == "HISTORICAL"


