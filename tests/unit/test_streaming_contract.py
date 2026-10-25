"""
Unit tests for pipeline.streaming.event_schema module.

Validates streaming contract schema parsing, ISO 8601 UTC timestamp enforcement,
H3 cell verification, bounding box constraints, and rejection reason codes.
"""

import json
from datetime import datetime, timezone
import pytest

from pipeline.streaming.event_schema import (
    StreamingEvent,
    ValidationResult,
    validate_streaming_event,
    parquet_row_to_event,
    SCHEMA_VERSION,
    DATASET_ID,
    DEFAULT_PROVENANCE,
    REASON_CODES
)


def _valid_payload_dict():
    return {
        "schema_version": "1.0.0",
        "event_id": "ff02be5e897d08e2a23776d00ce17c73fa8960aa",
        "trip_id": "1331f7a37850d9673b465e85cffa6c369d5cf5af",
        "event_ts": "2022-06-01T05:00:00Z",
        "h3_cell": "882664c1edfffff",
        "pickup_latitude": 41.79259236,
        "pickup_longitude": -87.769615453,
        "pickup_community_area": 56,
        "dataset_id": "wrvz-psew",
        "provenance": "HISTORICAL_REPLAY"
    }


def test_valid_event_passes_validation():
    payload = _valid_payload_dict()
    res = validate_streaming_event(payload)
    assert res.is_valid is True
    assert res.reason_code is None
    assert res.event is not None
    assert res.event.event_id == "ff02be5e897d08e2a23776d00ce17c73fa8960aa"
    assert res.event.h3_cell == "882664c1edfffff"
    assert res.event.pickup_community_area == 56
    assert res.event.get_kafka_key() == "882664c1edfffff"


def test_valid_json_string_and_bytes_deserialization():
    payload = _valid_payload_dict()
    json_str = json.dumps(payload)
    res_str = validate_streaming_event(json_str)
    assert res_str.is_valid is True

    json_bytes = json_str.encode("utf-8")
    res_bytes = validate_streaming_event(json_bytes)
    assert res_bytes.is_valid is True


def test_reject_malformed_json():
    res = validate_streaming_event("NOT_A_JSON_STRING {")
    assert res.is_valid is False
    assert res.reason_code == REASON_CODES.REJECT_MALFORMED_JSON


def test_reject_unsupported_schema_version():
    p = _valid_payload_dict()
    p["schema_version"] = "2.0.0"
    res = validate_streaming_event(p)
    assert res.is_valid is False
    assert res.reason_code == REASON_CODES.REJECT_UNSUPPORTED_SCHEMA_VERSION


def test_reject_missing_or_invalid_event_id():
    p1 = _valid_payload_dict()
    del p1["event_id"]
    res1 = validate_streaming_event(p1)
    assert res1.is_valid is False
    assert res1.reason_code == REASON_CODES.REJECT_MISSING_EVENT_ID

    p2 = _valid_payload_dict()
    p2["event_id"] = "not_a_valid_sha1_hash"
    res2 = validate_streaming_event(p2)
    assert res2.is_valid is False
    assert res2.reason_code == REASON_CODES.REJECT_INVALID_EVENT_ID


def test_reject_missing_trip_id():
    p = _valid_payload_dict()
    p["trip_id"] = "   "
    res = validate_streaming_event(p)
    assert res.is_valid is False
    assert res.reason_code == REASON_CODES.REJECT_MISSING_TRIP_ID


def test_reject_invalid_or_non_utc_timestamp():
    p1 = _valid_payload_dict()
    p1["event_ts"] = "invalid-date"
    res1 = validate_streaming_event(p1)
    assert res1.is_valid is False
    assert res1.reason_code == REASON_CODES.REJECT_INVALID_TIMESTAMP

    # Missing timezone offset
    p2 = _valid_payload_dict()
    p2["event_ts"] = "2022-06-01T05:00:00"
    res2 = validate_streaming_event(p2)
    assert res2.is_valid is False
    assert res2.reason_code == REASON_CODES.REJECT_INVALID_TIMESTAMP


def test_reject_out_of_bounds_timestamp():
    # Before June 1 05:00Z
    p1 = _valid_payload_dict()
    p1["event_ts"] = "2022-06-01T04:59:59Z"
    res1 = validate_streaming_event(p1)
    assert res1.is_valid is False
    assert res1.reason_code == REASON_CODES.REJECT_OUT_OF_BOUNDS_TIMESTAMP

    # Exactly at or after July 1 05:00Z (half-open upper bound)
    p2 = _valid_payload_dict()
    p2["event_ts"] = "2022-07-01T05:00:00Z"
    res2 = validate_streaming_event(p2)
    assert res2.is_valid is False
    assert res2.reason_code == REASON_CODES.REJECT_OUT_OF_BOUNDS_TIMESTAMP


def test_reject_invalid_h3_cell():
    p1 = _valid_payload_dict()
    p1["h3_cell"] = "not_a_hex_cell"
    res1 = validate_streaming_event(p1)
    assert res1.is_valid is False
    assert res1.reason_code == REASON_CODES.REJECT_INVALID_H3_CELL

    # Resolution 7 cell instead of 8
    p2 = _valid_payload_dict()
    p2["h3_cell"] = "872664c1effffff"
    res2 = validate_streaming_event(p2)
    assert res2.is_valid is False
    assert res2.reason_code == REASON_CODES.REJECT_INVALID_H3_CELL


def test_reject_coordinates_out_of_bounds():
    p = _valid_payload_dict()
    p["pickup_latitude"] = 35.0  # Outside Chicago
    res = validate_streaming_event(p)
    assert res.is_valid is False
    assert res.reason_code == REASON_CODES.REJECT_COORDINATES_OUT_OF_BOUNDS


def test_parquet_row_to_event_conversion():
    row = {
        "event_id": "ff02be5e897d08e2a23776d00ce17c73fa8960aa",
        "trip_id": "1331f7a37850d9673b465e85cffa6c369d5cf5af",
        "dataset_id": "wrvz-psew",
        "event_ts": datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc),
        "pickup_centroid_latitude": 41.79259236,
        "pickup_centroid_longitude": -87.769615453,
        "pickup_community_area": 56
    }
    event = parquet_row_to_event(row, resolution=8)
    assert isinstance(event, StreamingEvent)
    assert event.event_id == "ff02be5e897d08e2a23776d00ce17c73fa8960aa"
    assert event.event_ts == "2022-06-01T05:00:00Z"
    assert event.h3_cell.startswith("88")
    assert event.pickup_community_area == 56

    # Test serialization round-trip
    event_json = event.to_json()
    val_res = validate_streaming_event(event_json)
    assert val_res.is_valid is True

