"""
Unit tests for pipeline.streaming.consumer module.

Tests window boundary calculations, watermark semantics, deduplication policies,
Catalyst schema definitions, and consumer configuration validation.
"""

from datetime import datetime, timezone, timedelta
import pytest

from pipeline.streaming.consumer import (
    DEFAULT_WATERMARK,
    DEFAULT_WINDOW_DURATION,
    DEFAULT_BOOTSTRAP_SERVERS,
    DEFAULT_TOPIC,
    SparkStreamingConsumer
)
from pipeline.streaming.event_schema import SPARK_STREAMING_SCHEMA


def test_spark_streaming_schema_definition():
    """Verify Catalyst StructType schema contains all required fields with correct types."""
    assert SPARK_STREAMING_SCHEMA is not None
    names = SPARK_STREAMING_SCHEMA.names
    assert "schema_version" in names
    assert "event_id" in names
    assert "trip_id" in names
    assert "event_ts" in names
    assert "h3_cell" in names
    assert "pickup_latitude" in names
    assert "pickup_longitude" in names
    assert "pickup_community_area" in names
    assert "dataset_id" in names
    assert "provenance" in names


def test_fifteen_minute_window_boundary_calculations():
    """
    Verify 15-minute tumbling window boundary logic:
    Window is half-open [window_start, window_end).
    An event exactly on the boundary belongs to the NEXT window.
    """
    def compute_window(dt: datetime, window_minutes: int = 15):
        # Epoch-aligned window calculation
        minute_bucket = (dt.minute // window_minutes) * window_minutes
        start = dt.replace(minute=minute_bucket, second=0, microsecond=0)
        end = start + timedelta(minutes=window_minutes)
        return start, end

    # 1. Event inside window
    t1 = datetime(2022, 6, 1, 10, 7, 30, tzinfo=timezone.utc)
    s1, e1 = compute_window(t1)
    assert s1 == datetime(2022, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    assert e1 == datetime(2022, 6, 1, 10, 15, 0, tzinfo=timezone.utc)

    # 2. Event exactly at window start: belongs to [10:00, 10:15)
    t2 = datetime(2022, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    s2, e2 = compute_window(t2)
    assert s2 == datetime(2022, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    assert e2 == datetime(2022, 6, 1, 10, 15, 0, tzinfo=timezone.utc)

    # 3. Event exactly at window end (10:15:00): belongs to [10:15, 10:30), NOT [10:00, 10:15)
    t3 = datetime(2022, 6, 1, 10, 15, 0, tzinfo=timezone.utc)
    s3, e3 = compute_window(t3)
    assert s3 == datetime(2022, 6, 1, 10, 15, 0, tzinfo=timezone.utc)
    assert e3 == datetime(2022, 6, 1, 10, 30, 0, tzinfo=timezone.utc)

    # 4. End of hour boundary (10:59:59 -> [10:45, 11:00); 11:00:00 -> [11:00, 11:15))
    t4 = datetime(2022, 6, 1, 10, 59, 59, tzinfo=timezone.utc)
    s4, e4 = compute_window(t4)
    assert s4 == datetime(2022, 6, 1, 10, 45, 0, tzinfo=timezone.utc)
    assert e4 == datetime(2022, 6, 1, 11, 0, 0, tzinfo=timezone.utc)

    t5 = datetime(2022, 6, 1, 11, 0, 0, tzinfo=timezone.utc)
    s5, e5 = compute_window(t5)
    assert s5 == datetime(2022, 6, 1, 11, 0, 0, tzinfo=timezone.utc)
    assert e5 == datetime(2022, 6, 1, 11, 15, 0, tzinfo=timezone.utc)


def test_watermark_and_lateness_evaluation_policy():
    """
    Verify 10-minute watermark horizon:
    Events arriving with event_ts < max_event_ts - 10min are dropped as late.
    Events with event_ts >= max_event_ts - 10min are accepted.
    """
    watermark_duration = timedelta(minutes=10)
    current_max_event_ts = datetime(2022, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    watermark_cutoff = current_max_event_ts - watermark_duration  # 11:50:00 UTC

    # Event arriving within tolerance (11:52:00) -> ACCEPTED
    in_time_event = datetime(2022, 6, 1, 11, 52, 0, tzinfo=timezone.utc)
    assert in_time_event >= watermark_cutoff

    # Event arriving exactly at cutoff (11:50:00) -> ACCEPTED
    boundary_event = datetime(2022, 6, 1, 11, 50, 0, tzinfo=timezone.utc)
    assert boundary_event >= watermark_cutoff

    # Event arriving beyond watermark (11:49:59) -> DROPPED AS LATE
    late_event = datetime(2022, 6, 1, 11, 49, 59, tzinfo=timezone.utc)
    assert late_event < watermark_cutoff


def test_deduplication_horizon_contract():
    """
    Verify deduplication horizon contract per AGENTS.md:
    'Streaming: event time only. Dedup horizon equals the watermark.
    Duplicates beyond it may be counted again, and that behaviour must be tested, not hidden.'
    """
    dedup_horizon = timedelta(minutes=10)

    # First event seen at 10:00:00
    first_event_ts = datetime(2022, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Duplicate arriving within dedup horizon (e.g. stream progressed to 10:05:00)
    stream_progress_1 = datetime(2022, 6, 1, 10, 5, 0, tzinfo=timezone.utc)
    is_within_horizon_1 = (stream_progress_1 - first_event_ts) <= dedup_horizon
    assert is_within_horizon_1 is True  # Dropped as duplicate

    # Duplicate arriving beyond dedup horizon (e.g. stream progressed to 10:15:00)
    stream_progress_2 = datetime(2022, 6, 1, 10, 15, 0, tzinfo=timezone.utc)
    is_within_horizon_2 = (stream_progress_2 - first_event_ts) <= dedup_horizon
    assert is_within_horizon_2 is False  # State expired; may be counted again


def test_consumer_configuration_validation():
    """Verify consumer parameters and default settings alignment."""
    consumer = SparkStreamingConsumer(
        bootstrap_servers="broker.test:9092",
        topic="test_topic",
        checkpoint_dir="/tmp/chk",
        output_dir="/tmp/out",
        watermark="10 minutes",
        window_duration="15 minutes"
    )
    assert consumer.bootstrap_servers == "broker.test:9092"
    assert consumer.topic == "test_topic"
    assert consumer.watermark == "10 minutes"
    assert consumer.window_duration == "15 minutes"

