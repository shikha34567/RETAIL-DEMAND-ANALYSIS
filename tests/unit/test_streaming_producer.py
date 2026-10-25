"""
Unit tests for pipeline.streaming.producer module.

Tests producer accounting, batch iteration, mock Kafka message delivery,
error callbacks, and rejection handling without requiring a live broker.
"""

import os
import json
import tempfile
from datetime import datetime, timezone
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.streaming.producer import RideEventProducer, ProducerAccounting
from pipeline.streaming.event_schema import TARGET_RESOLUTION


class MockKafkaProducer:
    """Mock Kafka producer that simulates message queuing and delivery callbacks."""
    def __init__(self, fail_rate: float = 0.0):
        self.messages = []
        self.fail_rate = fail_rate
        self.flush_called = False

    def produce(self, topic, key, value, on_delivery=None):
        self.messages.append({"topic": topic, "key": key, "value": value})
        if on_delivery:
            if self.fail_rate > 0 and len(self.messages) % int(1 / self.fail_rate) == 0:
                on_delivery("SimulatedDeliveryFailure", None)
            else:
                on_delivery(None, "DeliveredMessage")

    def poll(self, timeout=0):
        pass

    def flush(self, timeout=None):
        self.flush_called = True


@pytest.fixture
def sample_parquet_fixture(tmp_path):
    pq_path = tmp_path / "test_cleaned.parquet"
    schema = pa.schema([
        ("event_id", pa.string()),
        ("trip_id", pa.string()),
        ("dataset_id", pa.string()),
        ("event_ts", pa.timestamp("us", tz="UTC")),
        ("pickup_centroid_latitude", pa.float64()),
        ("pickup_centroid_longitude", pa.float64()),
        ("pickup_community_area", pa.int32()),
    ])

    rows = []
    # 5 valid trips
    for i in range(5):
        rows.append({
            "event_id": f"111111111111111111111111111111111111111{i}",
            "trip_id": f"trip_{i}",
            "dataset_id": "wrvz-psew",
            "event_ts": datetime(2022, 6, 1, 5, i, 0, tzinfo=timezone.utc),
            "pickup_centroid_latitude": 41.881832,
            "pickup_centroid_longitude": -87.623177,
            "pickup_community_area": 8
        })

    # 1 invalid trip (out of bounds coordinates)
    rows.append({
        "event_id": "2222222222222222222222222222222222222222",
        "trip_id": "trip_invalid",
        "dataset_id": "wrvz-psew",
        "event_ts": datetime(2022, 6, 1, 5, 10, 0, tzinfo=timezone.utc),
        "pickup_centroid_latitude": 10.0,
        "pickup_centroid_longitude": 10.0,
        "pickup_community_area": None
    })

    tbl = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(tbl, str(pq_path))
    return str(pq_path)


def test_producer_mock_publishing_and_accounting(sample_parquet_fixture):
    mock_client = MockKafkaProducer()
    producer = RideEventProducer(
        bootstrap_servers="localhost:9092",
        topic="test_topic",
        parquet_path=sample_parquet_fixture,
        batch_size=2,
        kafka_client=mock_client
    )

    accounting = producer.publish_events(limit=None)

    assert accounting.total_input_records == 6
    assert accounting.validated_records == 5
    assert accounting.rejected_records == 1
    assert accounting.published_records == 5
    assert accounting.delivered_records == 5
    assert accounting.delivery_errors == 0
    assert mock_client.flush_called is True
    assert len(mock_client.messages) == 5

    # Check key and payload
    first_msg = mock_client.messages[0]
    assert first_msg["topic"] == "test_topic"
    assert first_msg["key"] == b"882664c1a9fffff"  # Loop H3 cell
    payload = json.loads(first_msg["value"].decode("utf-8"))
    assert payload["event_id"] == "1111111111111111111111111111111111111110"
    assert payload["schema_version"] == "1.0.0"


def test_producer_with_offset_and_limit(sample_parquet_fixture):
    mock_client = MockKafkaProducer()
    producer = RideEventProducer(
        bootstrap_servers="localhost:9092",
        topic="test_topic",
        parquet_path=sample_parquet_fixture,
        batch_size=2,
        kafka_client=mock_client
    )

    accounting = producer.publish_events(limit=2, start_offset=1)
    assert accounting.total_input_records == 2
    assert accounting.published_records == 2
    assert len(mock_client.messages) == 2


def test_producer_delivery_failure_accounting(sample_parquet_fixture):
    # Mock client with 50% failure rate
    mock_client = MockKafkaProducer(fail_rate=0.5)
    producer = RideEventProducer(
        bootstrap_servers="localhost:9092",
        topic="test_topic",
        parquet_path=sample_parquet_fixture,
        kafka_client=mock_client
    )

    accounting = producer.publish_events(limit=4)
    assert accounting.delivery_errors > 0
    assert accounting.delivered_records + accounting.delivery_errors == accounting.published_records
