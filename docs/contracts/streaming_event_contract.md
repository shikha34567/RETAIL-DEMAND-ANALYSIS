# RideIntel Streaming Event Contract (v1.0.0)

**Contract Status:** ACTIVE  
**Machine-Readable Schema:** `contracts/streaming_event_schema.json`  
**Shared Implementation:** `pipeline/streaming/event_schema.py`  
**Kafka Topic:** `ride_events_res8` (configurable via `settings.yaml`)  

---

## 1. Specification Overview

This document specifies the streaming event contract published to Apache Kafka by the RideIntel ingestion producer and consumed by Spark Structured Streaming for 15-minute event-time aggregation by H3 Resolution 8 cell.

Every message published to Kafka represents a single taxi ride pickup event with verified spatial coordinates in the City of Chicago.

---

## 2. Kafka Message Format & Keying Strategy

### 2.1 Message Key
* **Selected Key:** `h3_cell` (UTF-8 string, 15 hex characters, e.g., `"882664c1edfffff"`).
* **Rationale:**
  1. **Spatial Locality & Partition Affinity:** Grouping events by H3 cell routes all trips in the same geographic zone to the same Kafka partition, preserving per-zone arrival order.
  2. **Scalability:** With 239 observed Resolution 8 cells, default partitioners (murmur2) distribute zones evenly across multiple Kafka partitions without hot-spotting single partitions.
  3. **Fallback:** If an event lacks an H3 cell during error/quarantine testing, the key falls back to `event_id`.

### 2.2 Message Value
* **Encoding:** JSON, UTF-8.
* **Content-Type:** `application/json`.
* **Compression:** Snappy or none (configurable on producer).

---

## 3. JSON Event Schema (v1.0.0)

| Field Name | Data Type | Nullable | Description & Constraints |
| :--- | :--- | :--- | :--- |
| `schema_version` | `string` | No | Constant `"1.0.0"`. Identifies contract revision. |
| `event_id` | `string` | No | Stable deterministic hash `sha1(dataset_id + ":" + trip_id)`. 40 hex chars. |
| `trip_id` | `string` | No | Source trip identifier from City of Chicago open data. |
| `event_ts` | `string` | No | ISO 8601 UTC timestamp format: `YYYY-MM-DDTHH:MM:SSZ` (e.g. `2022-06-01T05:00:00Z`). |
| `h3_cell` | `string` | No | Valid H3 Resolution 8 hexagon index (15 lowercase hex characters). |
| `pickup_latitude` | `float` | No | Centroid latitude within Chicago bounds ($41.60 \le \text{lat} \le 42.10$). |
| `pickup_longitude` | `float` | No | Centroid longitude within Chicago bounds ($-87.95 \le \text{lon} \le -87.50$). |
| `pickup_community_area`| `integer`| Yes | Community area code ($1 \le \text{ca} \le 77$). Null if unassigned (e.g. 326 border trips). |
| `dataset_id` | `string` | No | Identifier of source dataset: `"wrvz-psew"`. |
| `provenance` | `string` | No | Processing label: `"HISTORICAL_REPLAY"` or `"REPLAYED"`. |

### 3.1 Example Valid Payload
```json
{
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
```

---

## 4. Validation & Rejection Reason Codes

When records are read from the cleaned Parquet source or received over the wire, each record is validated. Malformed or invalid records are rejected or quarantined with an explicit reason code:

| Reason Code | Category | Condition |
| :--- | :--- | :--- |
| `REJECT_MALFORMED_JSON` | Parse Error | Value cannot be deserialized as valid UTF-8 JSON. |
| `REJECT_MISSING_EVENT_ID` | Contract Error | Field `event_id` is missing, null, or empty string. |
| `REJECT_MISSING_TRIP_ID` | Contract Error | Field `trip_id` is missing, null, or empty string. |
| `REJECT_INVALID_TIMESTAMP` | Temporal Error | `event_ts` is not ISO 8601 UTC parseable or has non-UTC timezone. |
| `REJECT_OUT_OF_BOUNDS_TIMESTAMP`| Temporal Error | `event_ts` falls outside experimental window $[2022-06-01\text{T}05:00:00\text{Z}, 2022-07-01\text{T}05:00:00\text{Z})$. |
| `REJECT_INVALID_H3_CELL` | Spatial Error | `h3_cell` is not a valid 15-character H3 index at Resolution 8. |
| `REJECT_COORDINATES_OUT_OF_BOUNDS`| Spatial Error | Latitude or longitude outside valid Chicago bounding box. |
| `REJECT_UNSUPPORTED_SCHEMA_VERSION`| Version Error | `schema_version` does not start with `"1."`. |

---

## 5. Deduplication, Watermarking, and Window Semantics

### 5.1 Deduplication
* **Dedup Horizon:** 10 minutes (matching the Spark Structured Streaming watermark).
* **Dedup Keys:** `(event_id, event_ts)`.
* **Behavior:** Events with identical `event_id` arriving within the watermark horizon are deduplicated by Spark. Duplicates arriving beyond the watermark horizon may be re-counted; this is an inherent property of bounded state streaming and must be tested explicitly.

### 5.2 Windowing
* **Window Duration:** 15 minutes.
* **Window Alignment:** Tumbling, half-open interval $[T_{\text{start}}, T_{\text{end}})$.
* **Boundary Rule:** An event timestamped exactly at `10:15:00Z` belongs to `[10:15:00Z, 10:30:00Z)`, **not** `[10:00:00Z, 10:15:00Z)`.

### 5.3 Watermark & Late Event Handling
* **Watermark Duration:** 10 minutes (`withWatermark("event_ts", "10 minutes")`).
* **Lateness Policy:** Events arriving with `event_ts < (max_event_ts - 10 minutes)` are dropped by the streaming engine as late data.

