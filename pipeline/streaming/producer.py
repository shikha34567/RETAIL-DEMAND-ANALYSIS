"""
RideIntel Kafka Event Producer.

Reads the cleaned historical Chicago taxi Parquet dataset and streams validated ride events
to Apache Kafka. Supports chronological replay, batching, rate-limiting, and bounded test fixtures.
"""

import os
import sys
import time
import argparse
import logging
from typing import Dict, Any, Optional, Iterator, List, Callable
from datetime import datetime, timezone
import pyarrow.parquet as pq

# Ensure project root is in sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from pipeline.streaming.event_schema import (
    StreamingEvent,
    validate_streaming_event,
    parquet_row_to_event,
    TARGET_RESOLUTION
)

logger = logging.getLogger("rideintel.producer")

DEFAULT_CLEANED_PARQUET = os.path.join("data", "interim", "cleaned_trips_2022-06", "cleaned_trips.parquet")
DEFAULT_BOOTSTRAP_SERVERS = "localhost:9092"
DEFAULT_TOPIC = "ride_events_res8"
DEFAULT_BATCH_SIZE = 1000


class ProducerAccounting:
    def __init__(self):
        self.total_input_records: int = 0
        self.validated_records: int = 0
        self.rejected_records: int = 0
        self.published_records: int = 0
        self.delivered_records: int = 0
        self.delivery_errors: int = 0
        self.rejection_reasons: Dict[str, int] = {}

    def record_rejection(self, reason: str):
        self.rejected_records += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_input_records": self.total_input_records,
            "validated_records": self.validated_records,
            "rejected_records": self.rejected_records,
            "published_records": self.published_records,
            "delivered_records": self.delivered_records,
            "delivery_errors": self.delivery_errors,
            "rejection_reasons": self.rejection_reasons
        }


class RideEventProducer:
    """
    Publishes cleaned taxi ride events to an Apache Kafka topic.
    Supports dependency injection of the underlying Kafka producer for unit testing.
    """

    def __init__(
        self,
        bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
        topic: str = DEFAULT_TOPIC,
        parquet_path: str = DEFAULT_CLEANED_PARQUET,
        batch_size: int = DEFAULT_BATCH_SIZE,
        kafka_client: Optional[Any] = None,
        conf_overrides: Optional[Dict[str, Any]] = None
    ):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.parquet_path = parquet_path
        self.batch_size = batch_size
        self.accounting = ProducerAccounting()
        self._custom_client = kafka_client
        self._producer = None
        self._conf_overrides = conf_overrides or {}

    def _get_producer(self):
        if self._custom_client is not None:
            return self._custom_client

        if self._producer is not None:
            return self._producer

        try:
            import confluent_kafka
            conf = {
                "bootstrap.servers": self.bootstrap_servers,
                "client.id": "rideintel-parquet-producer",
                "compression.type": "snappy",
                "linger.ms": 20,
                "acks": "all",
                "retries": 5,
                "retry.backoff.ms": 250,
            }
            conf.update(self._conf_overrides)
            self._producer = confluent_kafka.Producer(conf)
            return self._producer
        except Exception as e:
            logger.error(f"Failed to initialize confluent-kafka Producer: {e}")
            raise

    def delivery_callback(self, err, msg):
        """Callback invoked once by confluent-kafka per message on delivery success/failure."""
        if err is not None:
            self.accounting.delivery_errors += 1
            logger.warning(f"Message delivery failed: {err}")
        else:
            self.accounting.delivered_records += 1

    def read_records(
        self,
        limit: Optional[int] = None,
        start_offset: int = 0
    ) -> Iterator[Dict[str, Any]]:
        """
        Stream records in chunks from Parquet to minimize memory footprint.
        Yields Python dictionary records.
        """
        if not os.path.exists(self.parquet_path):
            raise FileNotFoundError(f"Cleaned Parquet dataset not found at: {self.parquet_path}")

        parquet_file = pq.ParquetFile(self.parquet_path)
        yielded = 0
        skipped = 0

        columns = [
            "event_id",
            "trip_id",
            "dataset_id",
            "event_ts",
            "pickup_centroid_latitude",
            "pickup_centroid_longitude",
            "pickup_community_area"
        ]

        for batch in parquet_file.iter_batches(batch_size=self.batch_size, columns=columns):
            pydict = batch.to_pydict()
            batch_len = len(batch)
            for i in range(batch_len):
                if skipped < start_offset:
                    skipped += 1
                    continue

                if limit is not None and yielded >= limit:
                    return

                row = {col: pydict[col][i] for col in columns}
                yield row
                yielded += 1

    def publish_events(
        self,
        limit: Optional[int] = None,
        start_offset: int = 0,
        rate_limit_per_second: Optional[float] = None
    ) -> ProducerAccounting:
        """
        Reads records, validates them, and publishes to Kafka.
        """
        producer = self._get_producer()
        t0 = time.time()
        batch_count = 0

        logger.info(f"Starting replay from {self.parquet_path} -> topic: {self.topic}")

        sleep_interval = (1.0 / rate_limit_per_second) if (rate_limit_per_second and rate_limit_per_second > 0) else 0

        for raw_row in self.read_records(limit=limit, start_offset=start_offset):
            self.accounting.total_input_records += 1

            # Validate and construct event
            try:
                event = parquet_row_to_event(raw_row, resolution=TARGET_RESOLUTION)
                validation = validate_streaming_event(event.to_dict())
            except Exception as e:
                self.accounting.record_rejection(f"CONSTRUCTION_ERROR: {e}")
                continue

            if not validation.is_valid:
                self.accounting.record_rejection(validation.reason_code or "VALIDATION_FAILED")
                continue

            self.accounting.validated_records += 1
            payload_bytes = event.to_json().encode("utf-8")
            key_bytes = event.get_kafka_key().encode("utf-8")

            # Publish to Kafka
            try:
                producer.produce(
                    topic=self.topic,
                    key=key_bytes,
                    value=payload_bytes,
                    on_delivery=self.delivery_callback
                )
                self.accounting.published_records += 1
            except BufferError:
                # Local queue full, poll and retry
                producer.poll(1.0)
                producer.produce(
                    topic=self.topic,
                    key=key_bytes,
                    value=payload_bytes,
                    on_delivery=self.delivery_callback
                )
                self.accounting.published_records += 1
            except Exception as e:
                self.accounting.delivery_errors += 1
                logger.error(f"Produce exception for event {event.event_id}: {e}")

            batch_count += 1
            if batch_count % self.batch_size == 0:
                producer.poll(0)
                elapsed = time.time() - t0
                rate = self.accounting.published_records / elapsed if elapsed > 0 else 0
                logger.info(f"Published {self.accounting.published_records:,} events ({rate:.1f} msg/sec)...")

            if sleep_interval > 0:
                time.sleep(sleep_interval)

        # Flush all remaining messages
        logger.info("Flushing producer buffer...")
        producer.flush(timeout=30.0)

        elapsed_total = time.time() - t0
        logger.info(
            f"Replay complete: {self.accounting.published_records:,} published, "
            f"{self.accounting.delivered_records:,} delivered, "
            f"{self.accounting.rejected_records:,} rejected in {elapsed_total:.2f}s."
        )
        return self.accounting


def main():
    parser = argparse.ArgumentParser(description="RideIntel Kafka Event Replay Producer")
    parser.add_argument("--parquet-path", default=DEFAULT_CLEANED_PARQUET, help="Path to cleaned trips Parquet file")
    parser.add_argument("--bootstrap-servers", default=DEFAULT_BOOTSTRAP_SERVERS, help="Kafka bootstrap broker(s)")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Kafka topic to publish to")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of records to publish (default: all)")
    parser.add_argument("--offset", type=int, default=0, help="Initial record offset to start from")
    parser.add_argument("--rate", type=float, default=None, help="Maximum events per second (default: unconstrained)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Internal chunk batch size")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s [%(levelname)s] %(message)s")

    producer = RideEventProducer(
        bootstrap_servers=args.bootstrap_servers,
        topic=args.topic,
        parquet_path=args.parquet_path,
        batch_size=args.batch_size
    )

    try:
        accounting = producer.publish_events(
            limit=args.limit,
            start_offset=args.offset,
            rate_limit_per_second=args.rate
        )
        print("\n=======================================================")
        print("PRODUCER REPLAY SUMMARY")
        print("=======================================================")
        print(f"Total Input Records:      {accounting.total_input_records:,}")
        print(f"Validated Records:        {accounting.validated_records:,}")
        print(f"Published Records:        {accounting.published_records:,}")
        print(f"Delivered Records:        {accounting.delivered_records:,}")
        print(f"Delivery Errors:          {accounting.delivery_errors:,}")
        print(f"Rejected Records:         {accounting.rejected_records:,}")
        if accounting.delivery_errors > 0:
            sys.exit(1)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Producer execution failed: {e}", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()

