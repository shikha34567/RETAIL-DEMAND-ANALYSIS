"""
RideIntel Streaming Module.

Provides Kafka producer, Spark Structured Streaming consumer, event schema validation,
and window aggregation for real-time / replayed ride demand analysis.
"""

from pipeline.streaming.event_schema import (
    StreamingEvent,
    ValidationResult,
    validate_streaming_event,
    parquet_row_to_event,
    SPARK_STREAMING_SCHEMA,
    REASON_CODES
)

__all__ = [
    "StreamingEvent",
    "ValidationResult",
    "validate_streaming_event",
    "parquet_row_to_event",
    "SPARK_STREAMING_SCHEMA",
    "REASON_CODES"
]

