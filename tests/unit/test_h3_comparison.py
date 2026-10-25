"""
Unit tests for pipeline.spatial.compare_resolutions module.
"""

import os
import json
import tempfile
import hashlib
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.spatial.compare_resolutions import (
    H3ResolutionComparator,
    DEFAULT_CLEANED_PARQUET,
    DEFAULT_EXCLUDED_PARQUET,
    H3_RESOLUTION_METRICS
)
from pipeline.ingest.clean import (
    DEFAULT_EVIDENCE_PATH,
    DEFAULT_AUDIT_REPORT_PATH
)


def test_h3_resolution_metrics_metadata():
    for res in (7, 8, 9):
        assert res in H3_RESOLUTION_METRICS
        assert "avg_area_km2" in H3_RESOLUTION_METRICS[res]
        assert "avg_edge_length_m" in H3_RESOLUTION_METRICS[res]
        # Res 7 area > Res 8 area > Res 9 area
        if res > 7:
            assert H3_RESOLUTION_METRICS[res]["avg_area_km2"] < H3_RESOLUTION_METRICS[res - 1]["avg_area_km2"]


def test_comparator_on_synthetic_dataset():
    """Verify H3 comparison metrics, distributions, and reconciliation on a synthetic fixture."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cleaned_pq = os.path.join(tmpdir, "cleaned.parquet")
        excluded_pq = os.path.join(tmpdir, "excluded.parquet")
        evidence_json = os.path.join(tmpdir, "evidence.json")
        evidence_md = os.path.join(tmpdir, "evidence.md")
        settings_yaml = os.path.join(tmpdir, "settings.yaml")

        with open(settings_yaml, "w", encoding="utf-8") as f:
            f.write("h3:\n  resolution: null\n")

        # Create a small synthetic dataset: 10 trips across 2 coordinates
        # Coordinate 1: Loop (41.88, -87.62) -> 8 trips
        # Coordinate 2: O'Hare (41.982775, -87.877305) -> 2 trips (flag_missing_community_area=True)
        schema = pa.schema([
            ("event_id", pa.string()),
            ("trip_id", pa.string()),
            ("pickup_centroid_latitude", pa.float64()),
            ("pickup_centroid_longitude", pa.float64()),
            ("pickup_community_area", pa.int32()),
            ("h3_eligible", pa.bool_()),
            ("community_area_eligible", pa.bool_()),
            ("flag_missing_community_area", pa.bool_()),
        ])

        rows = []
        for i in range(8):
            rows.append({
                "event_id": f"evt_{i}",
                "trip_id": f"trip_{i}",
                "pickup_centroid_latitude": 41.88,
                "pickup_centroid_longitude": -87.62,
                "pickup_community_area": 8,
                "h3_eligible": True,
                "community_area_eligible": True,
                "flag_missing_community_area": False
            })
        for i in range(8, 10):
            rows.append({
                "event_id": f"evt_{i}",
                "trip_id": f"trip_{i}",
                "pickup_centroid_latitude": 41.982775009,
                "pickup_centroid_longitude": -87.8773054,
                "pickup_community_area": None,
                "h3_eligible": True,
                "community_area_eligible": False,
                "flag_missing_community_area": True
            })

        tbl = pa.Table.from_pylist(rows, schema=schema)
        pq.write_table(tbl, cleaned_pq)

        # Create excluded dummy parquet
        excl_schema = pa.schema([
            ("line_number", pa.int64()),
            ("primary_exclusion_reason", pa.string())
        ])
        excl_tbl = pa.Table.from_pylist([{"line_number": 1, "primary_exclusion_reason": "EXCLUDE_NO_SPATIAL_REFERENCE"}], schema=excl_schema)
        pq.write_table(excl_tbl, excluded_pq)

        comparator = H3ResolutionComparator(
            cleaned_parquet_path=cleaned_pq,
            excluded_parquet_path=excluded_pq,
            evidence_json_path=evidence_json,
            evidence_md_path=evidence_md,
            settings_path=settings_yaml,
            resolutions=(7, 8, 9)
        )
        res_data = comparator.evaluate()

        # Assert counts reconcile
        for r in ("7", "8", "9"):
            assert res_data["candidate_evaluations"][r]["eligible_trips_input"] == 10
            assert res_data["candidate_evaluations"][r]["indexed_trips"] == 10
            assert res_data["candidate_evaluations"][r]["skipped_trips"] == 0
            assert res_data["candidate_evaluations"][r]["distinct_occupied_cells"] == 2

        # Verify evidence files generated in temp dir
        assert os.path.exists(evidence_json)
        assert os.path.exists(evidence_md)

        # Update settings in temp dir
        comparator.update_settings_file(selected_res=8)
        with open(settings_yaml, "r", encoding="utf-8") as f:
            content = f.read()
        assert "resolution: 8" in content


def test_production_evidence_invariance_during_testing():
    """Verify that running comparator with None evidence paths never alters production cleaning evidence."""
    def get_hash(path):
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    clean_summary_hash_before = get_hash(DEFAULT_EVIDENCE_PATH)
    audit_hash_before = get_hash(DEFAULT_AUDIT_REPORT_PATH)

    with tempfile.TemporaryDirectory() as tmpdir:
        cleaned_pq = os.path.join(tmpdir, "cleaned.parquet")
        schema = pa.schema([
            ("event_id", pa.string()),
            ("trip_id", pa.string()),
            ("pickup_centroid_latitude", pa.float64()),
            ("pickup_centroid_longitude", pa.float64()),
            ("pickup_community_area", pa.int32()),
            ("h3_eligible", pa.bool_()),
            ("community_area_eligible", pa.bool_()),
            ("flag_missing_community_area", pa.bool_()),
        ])
        tbl = pa.Table.from_pylist([{
            "event_id": "e1",
            "trip_id": "t1",
            "pickup_centroid_latitude": 41.88,
            "pickup_centroid_longitude": -87.62,
            "pickup_community_area": 8,
            "h3_eligible": True,
            "community_area_eligible": True,
            "flag_missing_community_area": False
        }], schema=schema)
        pq.write_table(tbl, cleaned_pq)

        comparator = H3ResolutionComparator(
            cleaned_parquet_path=cleaned_pq,
            excluded_parquet_path="nonexistent.parquet",
            evidence_json_path=None,
            evidence_md_path=None,
            settings_path=None,
            resolutions=(8,)
        )
        comparator.evaluate()

    clean_summary_hash_after = get_hash(DEFAULT_EVIDENCE_PATH)
    audit_hash_after = get_hash(DEFAULT_AUDIT_REPORT_PATH)

    assert clean_summary_hash_after == clean_summary_hash_before
    assert audit_hash_after == audit_hash_before


def test_comparison_metrics_determinism():
    """Verify that re-evaluating on the same dataset produces identical metrics (excluding runtime fields)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cleaned_pq = os.path.join(tmpdir, "cleaned.parquet")
        schema = pa.schema([
            ("event_id", pa.string()),
            ("trip_id", pa.string()),
            ("pickup_centroid_latitude", pa.float64()),
            ("pickup_centroid_longitude", pa.float64()),
            ("pickup_community_area", pa.int32()),
            ("h3_eligible", pa.bool_()),
            ("community_area_eligible", pa.bool_()),
            ("flag_missing_community_area", pa.bool_()),
        ])
        tbl = pa.Table.from_pylist([
            {"event_id": "e1", "trip_id": "t1", "pickup_centroid_latitude": 41.88, "pickup_centroid_longitude": -87.62, "pickup_community_area": 8, "h3_eligible": True, "community_area_eligible": True, "flag_missing_community_area": False},
            {"event_id": "e2", "trip_id": "t2", "pickup_centroid_latitude": 41.98, "pickup_centroid_longitude": -87.87, "pickup_community_area": None, "h3_eligible": True, "community_area_eligible": False, "flag_missing_community_area": True}
        ], schema=schema)
        pq.write_table(tbl, cleaned_pq)

        comparator = H3ResolutionComparator(
            cleaned_parquet_path=cleaned_pq,
            excluded_parquet_path="dummy.parquet",
            evidence_json_path=None,
            evidence_md_path=None,
            settings_path=None,
            resolutions=(7, 8)
        )
        res1 = comparator.evaluate()
        res2 = comparator.evaluate()

        for r in ("7", "8"):
            m1 = res1["candidate_evaluations"][r]
            m2 = res2["candidate_evaluations"][r]
            assert m1["eligible_trips_input"] == m2["eligible_trips_input"]
            assert m1["indexed_trips"] == m2["indexed_trips"]
            assert m1["distinct_occupied_cells"] == m2["distinct_occupied_cells"]
            assert m1["trips_per_occupied_cell"] == m2["trips_per_occupied_cell"]
            assert m1["sparsity_descriptive_metrics"] == m2["sparsity_descriptive_metrics"]

