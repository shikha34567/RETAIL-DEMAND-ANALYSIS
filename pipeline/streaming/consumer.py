"""
RideIntel Spark Structured Streaming Consumer.

Consumes ride events from Apache Kafka, applies explicit 15-minute event-time tumbling windows,
deduplicates within a 10-minute watermark horizon, aggregates observed demand by H3 cell,
and writes partitioned aggregates to disk with resilient checkpointing.
"""

import os
import sys
import logging
import argparse
from typing import Optional, Dict, Any

# Ensure project root is in sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logger = logging.getLogger("rideintel.consumer")

DEFAULT_BOOTSTRAP_SERVERS = "localhost:9092"
DEFAULT_TOPIC = "ride_events_res8"
DEFAULT_CONSUMER_GROUP = "rideintel_spark_streaming"
DEFAULT_CHECKPOINT_DIR = os.path.join("data", "checkpoints", "streaming_window_agg")
DEFAULT_OUTPUT_DIR = os.path.join("data", "processed", "streaming_window_agg")
DEFAULT_WATERMARK = "10 minutes"
DEFAULT_WINDOW_DURATION = "15 minutes"


def create_spark_session(
    app_name: str = "RideIntel-Streaming-Aggregator",
    master: str = "local[2]",
    extra_configs: Optional[Dict[str, str]] = None
):
    """
    Creates a SparkSession configured with network bindings and optional Kafka connector.
    """
    # Ensure JAVA_HOME is set if available
    if not os.environ.get("JAVA_HOME") and os.path.exists(r"C:\Program Files\Java\jdk-21.0.10"):
        os.environ["JAVA_HOME"] = r"C:\Program Files\Java\jdk-21.0.10"

    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder
        .appName(app_name)
        .master(master)
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.sql.streaming.forceDeleteTempCheckpointLocation", "true")
        .config("spark.sql.session.timeZone", "UTC")
    )

    if extra_configs:
        for k, v in extra_configs.items():
            builder = builder.config(k, v)

    return builder.getOrCreate()


def build_streaming_transformation(
    raw_df,
    watermark_duration: str = DEFAULT_WATERMARK,
    window_duration: str = DEFAULT_WINDOW_DURATION
):
    """
    Pure Spark SQL Catalyst transformation.
    Parses JSON message value, validates fields, enforces event-time watermark,
    deduplicates within watermark state, and groups by 15-minute window and H3 cell.
    
    Operates 100% in JVM Catalyst to avoid Python worker issues.
    """
    from pyspark.sql import functions as F
    from pipeline.streaming.event_schema import SPARK_STREAMING_SCHEMA

    # 1. Parse JSON value
    parsed_df = (
        raw_df
        .select(
            F.from_json(F.col("value").cast("string"), SPARK_STREAMING_SCHEMA).alias("event")
        )
        .select("event.*")
    )

    # 2. Filter malformed / null records (validation filter)
    valid_df = (
        parsed_df
        .filter(
            F.col("event_id").isNotNull() &
            F.col("trip_id").isNotNull() &
            F.col("event_ts").isNotNull() &
            F.col("h3_cell").isNotNull() &
            (F.length(F.col("h3_cell")) == 15) &
            (F.col("pickup_latitude").between(41.60, 42.10)) &
            (F.col("pickup_longitude").between(-87.95, -87.50))
        )
        .withColumn("timestamp_utc", F.to_timestamp(F.col("event_ts"), "yyyy-MM-dd'T'HH:mm:ss'Z'"))
        .filter(F.col("timestamp_utc").isNotNull())
    )

    # 3. Apply Watermark and Deduplication on (event_id, timestamp_utc)
    # Deduplication within the watermark horizon ensures exactly-once semantics per window
    deduped_df = (
        valid_df
        .withWatermark("timestamp_utc", watermark_duration)
        .dropDuplicates(["event_id", "timestamp_utc"])
    )

    # 4. Event-Time Window Aggregation (Tumbling 15-minute window)
    windowed_agg = (
        deduped_df
        .groupBy(
            F.window(F.col("timestamp_utc"), window_duration),
            F.col("h3_cell")
        )
        .agg(
            F.count("*").alias("ride_count")
        )
        .select(
            F.col("window.start").alias("window_start"),
            F.col("window.end").alias("window_end"),
            F.col("h3_cell"),
            F.col("ride_count"),
            F.lit("STREAMING_OBSERVED").alias("demand_status"),
            F.lit("wrvz-psew").alias("dataset_id"),
            F.current_timestamp().alias("processed_at_utc")
        )
    )

    return windowed_agg


class SparkStreamingConsumer:
    """
    Manages Spark Structured Streaming query execution from Kafka to storage.
    """

    def __init__(
        self,
        bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
        topic: str = DEFAULT_TOPIC,
        checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR,
        output_dir: str = DEFAULT_OUTPUT_DIR,
        watermark: str = DEFAULT_WATERMARK,
        window_duration: str = DEFAULT_WINDOW_DURATION,
        spark_session=None
    ):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.checkpoint_dir = checkpoint_dir
        self.output_dir = output_dir
        self.watermark = watermark
        self.window_duration = window_duration
        self._spark = spark_session

    def get_spark(self):
        if self._spark is None:
            self._spark = create_spark_session()
        return self._spark

    def start_kafka_stream(self, output_mode: str = "append", trigger_interval: str = "10 seconds"):
        """
        Starts reading from the Kafka topic and streaming to Parquet sink.
        """
        spark = self.get_spark()

        logger.info(f"Connecting to Kafka brokers at: {self.bootstrap_servers}, topic: {self.topic}")
        raw_stream = (
            spark.readStream
            .format("kafka")
            .option("kafka.bootstrap.servers", self.bootstrap_servers)
            .option("subscribe", self.topic)
            .option("startingOffsets", "earliest")
            .option("failOnDataLoss", "false")
            .load()
        )

        agg_stream = build_streaming_transformation(
            raw_stream,
            watermark_duration=self.watermark,
            window_duration=self.window_duration
        )

        query = (
            agg_stream.writeStream
            .format("parquet")
            .outputMode(output_mode)
            .option("path", self.output_dir)
            .option("checkpointLocation", self.checkpoint_dir)
            .trigger(processingTime=trigger_interval)
            .start()
        )

        logger.info(f"Started Structured Streaming query. Checkpoint: {self.checkpoint_dir}, Output: {self.output_dir}")
        return query


def main():
    parser = argparse.ArgumentParser(description="RideIntel Spark Structured Streaming Aggregator")
    parser.add_argument("--bootstrap-servers", default=DEFAULT_BOOTSTRAP_SERVERS)
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--watermark", default=DEFAULT_WATERMARK)
    parser.add_argument("--window", default=DEFAULT_WINDOW_DURATION)
    parser.add_argument("--await-termination", action="store_true", help="Block until query termination")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    consumer = SparkStreamingConsumer(
        bootstrap_servers=args.bootstrap_servers,
        topic=args.topic,
        checkpoint_dir=args.checkpoint_dir,
        output_dir=args.output_dir,
        watermark=args.watermark,
        window_duration=args.window
    )

    query = consumer.start_kafka_stream()
    if args.await_termination:
        try:
            query.awaitTermination()
        except KeyboardInterrupt:
            logger.info("Stopping query gracefully...")
            query.stop()


if __name__ == "__main__":
    main()

