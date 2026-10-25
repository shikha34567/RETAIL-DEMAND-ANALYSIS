"""
RideIntel Streaming Event Contract & Schema Validation (v1.0.0).

Defines the shared event representation, JSON serialization, and deterministic
validation reason codes across Kafka producer, Spark consumer, and test suites.
"""

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, Union

from pipeline.spatial.h3_index import is_valid_cell, get_cell_resolution, coords_to_h3

SCHEMA_VERSION = "1.0.0"
DATASET_ID = "wrvz-psew"
DEFAULT_PROVENANCE = "HISTORICAL_REPLAY"
TARGET_RESOLUTION = 8

# Bounding box for valid Chicago coordinates
LAT_MIN, LAT_MAX = 41.60, 42.10
LON_MIN, LON_MAX = -87.95, -87.50

# Valid experimental interval boundaries (UTC)
INTERVAL_START_UTC = datetime(2022, 6, 1, 5, 0, 0, tzinfo=timezone.utc)
INTERVAL_END_UTC = datetime(2022, 7, 1, 5, 0, 0, tzinfo=timezone.utc)

# Validation Reason Codes
class REASON_CODES:
    REJECT_MALFORMED_JSON = "REJECT_MALFORMED_JSON"
    REJECT_MISSING_EVENT_ID = "REJECT_MISSING_EVENT_ID"
    REJECT_INVALID_EVENT_ID = "REJECT_INVALID_EVENT_ID"
    REJECT_MISSING_TRIP_ID = "REJECT_MISSING_TRIP_ID"
    REJECT_INVALID_TIMESTAMP = "REJECT_INVALID_TIMESTAMP"
    REJECT_OUT_OF_BOUNDS_TIMESTAMP = "REJECT_OUT_OF_BOUNDS_TIMESTAMP"
    REJECT_INVALID_H3_CELL = "REJECT_INVALID_H3_CELL"
    REJECT_COORDINATES_OUT_OF_BOUNDS = "REJECT_COORDINATES_OUT_OF_BOUNDS"
    REJECT_UNSUPPORTED_SCHEMA_VERSION = "REJECT_UNSUPPORTED_SCHEMA_VERSION"


_EVENT_ID_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class StreamingEvent:
    schema_version: str
    event_id: str
    trip_id: str
    event_ts: str  # ISO 8601 UTC string (e.g. "2022-06-01T05:00:00Z")
    h3_cell: str
    pickup_latitude: float
    pickup_longitude: float
    pickup_community_area: Optional[int]
    dataset_id: str
    provenance: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def get_kafka_key(self) -> str:
        """Returns the Kafka message key. Uses h3_cell for spatial affinity, fallback to event_id."""
        return self.h3_cell if self.h3_cell else self.event_id


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    reason_code: Optional[str] = None
    event: Optional[StreamingEvent] = None
    message: Optional[str] = None


def validate_streaming_event(data: Union[str, bytes, Dict[str, Any]]) -> ValidationResult:
    """
    Validates a raw payload (dict, string, or bytes) against the streaming event contract.
    Returns a deterministic ValidationResult with reason code on failure.
    """
    if isinstance(data, (str, bytes)):
        try:
            payload = json.loads(data)
        except Exception as e:
            return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_MALFORMED_JSON, message=str(e))
    elif isinstance(data, dict):
        payload = data
    else:
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_MALFORMED_JSON, message="Payload must be dict or JSON string/bytes")

    if not isinstance(payload, dict):
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_MALFORMED_JSON, message="Parsed payload is not a JSON object")

    # Schema version
    version = payload.get("schema_version")
    if not isinstance(version, str) or not version.startswith("1."):
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_UNSUPPORTED_SCHEMA_VERSION, message=f"Unsupported schema_version: {version}")

    # event_id
    event_id = payload.get("event_id")
    if not event_id or not isinstance(event_id, str):
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_MISSING_EVENT_ID, message="Missing event_id")
    if not _EVENT_ID_PATTERN.match(event_id.lower()):
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_INVALID_EVENT_ID, message=f"Invalid event_id hash: {event_id}")

    # trip_id
    trip_id = payload.get("trip_id")
    if not trip_id or not isinstance(trip_id, str) or not trip_id.strip():
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_MISSING_TRIP_ID, message="Missing trip_id")

    # event_ts
    raw_ts = payload.get("event_ts")
    if not raw_ts or not isinstance(raw_ts, str):
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_INVALID_TIMESTAMP, message="Missing or non-string event_ts")

    try:
        # Normalize trailing Z to +00:00 for fromisoformat
        iso_str = raw_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_INVALID_TIMESTAMP, message="event_ts must specify timezone (UTC)")
        dt_utc = dt.astimezone(timezone.utc)
    except Exception as e:
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_INVALID_TIMESTAMP, message=f"Unparseable event_ts: {e}")

    # Check half-open experimental interval: [2022-06-01T05:00:00Z, 2022-07-01T05:00:00Z)
    if not (INTERVAL_START_UTC <= dt_utc < INTERVAL_END_UTC):
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_OUT_OF_BOUNDS_TIMESTAMP, message=f"Timestamp {raw_ts} outside interval [{INTERVAL_START_UTC.isoformat()}, {INTERVAL_END_UTC.isoformat()})")

    # Coordinates
    lat = payload.get("pickup_latitude")
    lon = payload.get("pickup_longitude")
    if lat is None or lon is None:
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_COORDINATES_OUT_OF_BOUNDS, message="Coordinates cannot be null")
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_COORDINATES_OUT_OF_BOUNDS, message="Coordinates not float")

    if not (LAT_MIN <= lat_f <= LAT_MAX and LON_MIN <= lon_f <= LON_MAX):
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_COORDINATES_OUT_OF_BOUNDS, message=f"Coordinates ({lat_f}, {lon_f}) outside Chicago bounds")

    # h3_cell
    h3_cell = payload.get("h3_cell")
    if not h3_cell or not isinstance(h3_cell, str):
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_INVALID_H3_CELL, message="Missing h3_cell")
    if not is_valid_cell(h3_cell) or get_cell_resolution(h3_cell) != TARGET_RESOLUTION:
        return ValidationResult(is_valid=False, reason_code=REASON_CODES.REJECT_INVALID_H3_CELL, message=f"Invalid H3 Resolution {TARGET_RESOLUTION} cell: {h3_cell}")

    # pickup_community_area (optional)
    ca = payload.get("pickup_community_area")
    ca_int = None
    if ca is not None:
        try:
            ca_int = int(ca)
        except (ValueError, TypeError):
            pass

    event = StreamingEvent(
        schema_version=version,
        event_id=event_id.lower(),
        trip_id=trip_id,
        event_ts=dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        h3_cell=h3_cell.lower(),
        pickup_latitude=round(lat_f, 9),
        pickup_longitude=round(lon_f, 9),
        pickup_community_area=ca_int,
        dataset_id=str(payload.get("dataset_id", DATASET_ID)),
        provenance=str(payload.get("provenance", DEFAULT_PROVENANCE))
    )

    return ValidationResult(is_valid=True, event=event)


def parquet_row_to_event(row: Dict[str, Any], resolution: int = TARGET_RESOLUTION) -> StreamingEvent:
    """
    Constructs a validated StreamingEvent from a row of cleaned_trips.parquet.
    Computes H3 cell dynamically if missing or validates existing cell.
    """
    lat = float(row["pickup_centroid_latitude"])
    lon = float(row["pickup_centroid_longitude"])
    h3_cell = coords_to_h3(lat, lon, resolution)
    if not h3_cell:
        raise ValueError(f"Could not compute H3 resolution {resolution} for ({lat}, {lon})")

    event_ts = row["event_ts"]
    if isinstance(event_ts, datetime):
        ts_utc = event_ts.astimezone(timezone.utc)
        ts_str = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(event_ts, (int, float)):
        # Microseconds from epoch in pyarrow timestamp
        ts_utc = datetime.fromtimestamp(event_ts / 1e6, tz=timezone.utc)
        ts_str = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        ts_str = str(event_ts)

    ca = row.get("pickup_community_area")
    ca_val = int(ca) if ca is not None and not (isinstance(ca, float) and (ca != ca)) else None

    return StreamingEvent(
        schema_version=SCHEMA_VERSION,
        event_id=str(row["event_id"]).lower(),
        trip_id=str(row["trip_id"]),
        event_ts=ts_str,
        h3_cell=h3_cell.lower(),
        pickup_latitude=round(lat, 9),
        pickup_longitude=round(lon, 9),
        pickup_community_area=ca_val,
        dataset_id=str(row.get("dataset_id", DATASET_ID)),
        provenance=DEFAULT_PROVENANCE
    )


# Spark Catalyst StructType schema for parsing JSON messages in Spark Structured Streaming
try:
    from pyspark.sql.types import (
        StructType, StructField, StringType, DoubleType, IntegerType
    )
    SPARK_STREAMING_SCHEMA = StructType([
        StructField("schema_version", StringType(), False),
        StructField("event_id", StringType(), False),
        StructField("trip_id", StringType(), False),
        StructField("event_ts", StringType(), False),
        StructField("h3_cell", StringType(), False),
        StructField("pickup_latitude", DoubleType(), False),
        StructField("pickup_longitude", DoubleType(), False),
        StructField("pickup_community_area", IntegerType(), True),
        StructField("dataset_id", StringType(), False),
        StructField("provenance", StringType(), False)
    ])
except ImportError:
    SPARK_STREAMING_SCHEMA = None

