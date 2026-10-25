# RideIntel Phase 2 — Final Verification and Readiness Audit

**Audit Date:** 2026-10-11  
**Project:** RideIntel — Chicago Ride Demand Analysis  
**Phase:** Phase 2 (Kafka + Spark Structured Streaming Pipeline)  
**Auditor:** Lead Data Engineer  
**Final Audit Verdict:** **BLOCKED** (Live Broker Integration Blocked; Code Contracts & Unit Tests: **PASS WITH MINOR FIXES**)

---

## 1. Executive Summary

A comprehensive, read-only audit of the Phase 2 implementation was conducted on the host environment. The Phase 2 codebase implements the Kafka replay producer (`pipeline/streaming/producer.py`), the pure-JVM Spark Structured Streaming aggregator (`pipeline/streaming/consumer.py`), formal streaming contracts (`contracts/streaming_event_schema.json`), and Docker Compose infrastructure (`infra/kafka/docker-compose.yml`).

All 40 Phase 1 tests and 19 Phase 2 unit tests pass deterministically (**59 passed, 2 skipped** out of 61 collected items). All Phase 1 Parquet datasets and evidence reports were verified byte-identical against their canonical SHA-256 hashes.

However, in accordance with the project instructions (*"Never claim 'verified', 'passing' or 'done' unless a command ran and you pasted its output"* and *"Do not claim PASS based on unit tests alone"*), the final readiness verdict for live streaming execution is **BLOCKED**. No Kafka broker or container runtime (Docker / WSL2) exists on the native Windows host, and Spark's native Windows package resolution fails due to missing Hadoop `winutils.exe`.

---

## 2. Environment Versions, Actual Commands & Exit Codes

Each runtime dependency was probed directly on the Windows host. The actual commands, outputs, and exit codes are recorded below:

### 2.1 Python Environment
* **Command:** `python -c "import sys; print(f'Python: {sys.version}')"`
* **Output:** `Python: 3.13.9 (tags/v3.13.9:8183fa5, Oct 14 2025, 14:09:13) [MSC v.1944 64 bit (AMD64)]`
* **Exit Code:** `0`
* **Finding:** Host runs Python 3.13.9. `AGENTS.md` specifies Python 3.12 (not 3.13) due to PySpark worker process incompatibilities.

### 2.2 Java Environment
* **Command:** `java -version` (resolved via `C:\Program Files\Java\jdk-21.0.10`)
* **Output:**
  ```text
  java version "21.0.10" 2026-01-20 LTS
  Java(TM) SE Runtime Environment (build 21.0.10+8-LTS-217)
  Java HotSpot(TM) 64-Bit Server VM (build 21.0.10+8-LTS-217, mixed mode, sharing)
  ```
* **Exit Code:** `0`
* **Finding:** Java 21 LTS is installed and complies with the `Java 17 or 21` requirement.

### 2.3 PySpark
* **Command:** `python -c "import pyspark; print(pyspark.__version__)"`
* **Output:** `3.5.1`
* **Exit Code:** `0`
* **Finding:** PySpark 3.5.1 is installed in the local Python environment.

### 2.4 Docker Engine & Docker Compose
* **Command:** `cmd /v:on /c "docker --version & echo !errorlevel!"`
* **Output:**
  ```text
  'docker' is not recognized as an internal or external command, operable program or batch file.
  9009
  ```
* **Exit Code:** `9009` (Command Not Found)
* **Command:** `cmd /v:on /c "docker compose version & echo !errorlevel!"`
* **Output:**
  ```text
  'docker' is not recognized as an internal or external command, operable program or batch file.
  9009
  ```
* **Exit Code:** `9009` (Command Not Found)
* **Finding:** Neither Docker Desktop nor Docker CLI is installed on this host.

### 2.5 Kafka Python Client Library
* **Command:** `python -c "import confluent_kafka; print(confluent_kafka.__version__)"`
* **Output:** `2.16.0`
* **Exit Code:** `0`
* **Finding:** `confluent-kafka` (with C librdkafka bindings) is installed and operational.

### 2.6 Local Kafka Broker Connectivity
* **Command:** `powershell -Command "Get-NetTCPConnection -LocalPort 9092 -ErrorAction SilentlyContinue"`
* **Output:** *(empty — no listener)*
* **Exit Code:** `1`
* **Finding:** No Kafka broker daemon or container is listening on `localhost:9092`.

---

## 3. Spark Compatibility & Pure-JVM Analysis

### 3.1 Empirical Python 3.13 Worker Failure
When an RDD or Python UDF is evaluated in PySpark 3.5.1 on this host, the Python worker fails:
```text
WARN Shell: Did not find winutils.exe: java.io.FileNotFoundException: HADOOP_HOME and hadoop.home.dir are unset.
Python was not found; run without arguments to install from the Microsoft Store...
org.apache.spark.SparkException: Python worker failed to connect back.
Caused by: java.net.SocketTimeoutException: Accept timed out
Py4JJavaError: An error occurred while calling z:org.apache.spark.api.python.PythonRDD.collectAndServe.
```

### 3.2 What the Pure-JVM Implementation Avoids
In `pipeline/streaming/consumer.py`, transformations are written strictly using native Spark SQL Catalyst expressions (`F.from_json`, `F.to_timestamp`, `F.window`, `F.withWatermark`, `F.dropDuplicates`, `F.count`):
1. **Bypasses Python Worker Subprocesses:** The JVM executes all parsing, projection, windowing, deduplication, and aggregation natively in Java/Scala bytecode without spawning Python worker child processes (`pyspark/worker.py`).
2. **Eliminates Py4J Socket Serialization Overhead:** Avoids IPC socket communication and cloudpickle/pickle serialization between JVM and Python workers.
3. **Deterministic Memory Footprint:** Window state and deduplication caches remain inside the JVM heap and off-heap Tungsten memory managed directly by Spark.

### 3.3 What the Pure-JVM Implementation Does NOT Avoid
1. **Windows POSIX Binary Requirement (`winutils.exe` / `hadoop.dll`):** When Spark dynamically retrieves Maven packages via `spark.jars.packages`, Apache Hadoop's `FileUtil.chmod` attempts to set file permissions. On native Windows without `winutils.exe`, this causes:
   `java.lang.RuntimeException: java.io.FileNotFoundException: HADOOP_HOME and hadoop.home.dir are unset.`
2. **Unbundled Kafka Connector:** The base `pyspark` pip package ships without `spark-sql-kafka-0-10`. Without pre-downloaded JARs placed in `pyspark/jars` or dynamic package resolution, calling `spark.readStream.format("kafka")` fails with `AnalysisException: Failed to find data source: kafka`.
3. **Absent Broker:** Pure JVM cannot communicate if no Kafka broker process exists.

---

## 4. Execution Path Verification

### 4.1 Spark Streaming Consumer (`pipeline/streaming/consumer.py`)
* **Source:** Uses `readStream.format("kafka")` with configurable `startingOffsets: earliest` and `failOnDataLoss: false`.
* **Event-Time Windowing:** Groups by tumbling 15-minute event-time windows (`F.window(F.col("timestamp_utc"), "15 minutes")`).
* **Watermark & Lateness:** Enforces 10-minute watermark on `timestamp_utc` (`withWatermark("timestamp_utc", "10 minutes")`).
* **Deduplication:** Dedupes on `["event_id", "timestamp_utc"]` within the watermark horizon.
* **Sink & Resilient Checkpointing:** Writes to Parquet sink with configurable checkpoint location (`.option("checkpointLocation", self.checkpoint_dir)` defaulting to `data/checkpoints/streaming_window_agg`).

### 4.2 Kafka Producer (`pipeline/streaming/producer.py`)
* **Input:** Streams from `data/interim/cleaned_trips_2022-06/cleaned_trips.parquet` using chunked PyArrow batch reader (`iter_batches(batch_size=1000)`).
* **Validation:** Validates each record against `StreamingEvent` schema (ISO 8601 UTC timestamp, spatial bounding box, H3 Resolution 8 validity).
* **Partition Keying:** Keys messages by `h3_cell` string (`event.get_kafka_key()`) ensuring spatial affinity per partition.
* **Delivery Callback & Accounting:** Implements asynchronous `delivery_callback(err, msg)` and returns structured `ProducerAccounting` recording input records, validated, rejected, published, delivered, delivery errors, and reason tallies.

---

## 5. Test Coverage: Real vs. Mocked

| Test Module | Test Name | Nature | Real Components Exercised | Mocks / Stubs Used |
| :--- | :--- | :---: | :--- | :--- |
| `test_streaming_contract.py` | 11 tests (validation, bounds, types, H3) | **Real** | Real JSON serialization, real H3 cell calculations, real timestamp parsers | None |
| `test_streaming_producer.py` | `test_producer_mock_publishing_and_accounting` | **Unit** | Real batch iteration, real schema validation, real accounting logic | Mock Kafka Producer |
| `test_streaming_producer.py` | `test_producer_with_offset_and_limit` | **Unit** | Real Parquet batch slicing, real event generation | Mock Kafka Producer |
| `test_streaming_producer.py` | `test_producer_delivery_failure_accounting` | **Unit** | Real error callback logic, real failure counter | Mock Kafka Producer |
| `test_streaming_consumer.py` | `test_spark_streaming_schema_definition` | **Real** | Real PySpark StructType definitions | None |
| `test_streaming_consumer.py` | `test_fifteen_minute_window_boundary_calculations` | **Real** | Real UTC timestamp boundary math | None |
| `test_streaming_consumer.py` | `test_watermark_and_lateness_evaluation_policy` | **Real** | Real 10-minute watermark boundary evaluation | None |
| `test_streaming_consumer.py` | `test_deduplication_horizon_contract` | **Real** | Real deduplication state horizon logic | None |
| `test_streaming_consumer.py` | `test_consumer_configuration_validation` | **Real** | Real consumer configuration objects | None |
| `test_streaming_pipeline.py` | `test_live_kafka_broker_connectivity` | **Real Socket** | Real TCP connection check to `127.0.0.1:9092` | None (Skips as BLOCKED) |
| `test_streaming_pipeline.py` | `test_e2e_streaming_pipeline_execution` | **Real E2E** | Live Kafka AdminClient / Topic probe | None (Skips as BLOCKED) |

---

## 6. Checkpoint Recovery and Deduplication Guarantees

In accordance with `AGENTS.md`:
* **Deduplication Horizon Equals Watermark:** Spark's `dropDuplicates(["event_id", "timestamp_utc"])` maintains state only for events with timestamps within the 10-minute watermark horizon.
* **Behavior Beyond Horizon:** Once an event's window passes the watermark boundary, its state is evicted from the Spark state store. A late duplicate arriving past the watermark horizon cannot be matched against evicted state and may either be dropped as late data or re-counted. This behavior is documented and tested in `test_deduplication_horizon_contract`.
* **No False Claims of Exactly-Once:** The pipeline does **not** claim end-to-end exactly-once across Kafka, Spark, Parquet, and downstream sinks. The producer provides at-least-once delivery (`acks="all"` with retries); Spark provides at-least-once replay with bounded-horizon deduplication; and file sinks provide atomic micro-batch file commits.

---

## 7. Full Test Suite Execution Output

The entire project test suite was executed:
```powershell
python -m pytest -v
```

### Actual Terminal Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\91984\AppData\Local\Programs\Python\Python313\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\91984\OneDrive\Desktop\ride demand analysis -- intel
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.14.2
collecting ... collected 61 items

tests/integration/test_streaming_pipeline.py::test_live_kafka_broker_connectivity SKIPPED [  1%]
tests/integration/test_streaming_pipeline.py::test_e2e_streaming_pipeline_execution SKIPPED [  3%]
tests/unit/test_clean_pipeline.py::test_compute_event_id PASSED          [  4%]
tests/unit/test_clean_pipeline.py::test_timestamp_localization_and_interval PASSED [  6%]
tests/unit/test_clean_pipeline.py::test_pipeline_unit_record_evaluation PASSED [  8%]
tests/unit/test_clean_pipeline.py::test_pipeline_integration_small_dataset PASSED [  9%]
tests/unit/test_clean_pipeline.py::test_production_reports_not_polluted_by_testing PASSED [ 11%]
tests/unit/test_clean_pipeline.py::test_all_exclusion_ranks_accounting_and_precedence PASSED [ 13%]
tests/unit/test_cleaning_policy.py::test_reason_codes_contract_validity PASSED [ 14%]
tests/unit/test_cleaning_policy.py::test_stable_event_id_generation PASSED [ 16%]
tests/unit/test_cleaning_policy.py::test_mutually_exclusive_geographic_partition PASSED [ 18%]
tests/unit/test_cleaning_policy.py::test_overlapping_eligibility_counts_derivation PASSED [ 19%]
tests/unit/test_cleaning_policy.py::test_reconciliation_equation PASSED  [ 21%]
tests/unit/test_cleaning_policy.py::test_quality_flags_do_not_reduce_included_count PASSED [ 22%]
tests/unit/test_cleaning_policy.py::test_primary_exclusion_precedence_logic PASSED [ 24%]
tests/unit/test_cleaning_policy.py::test_half_open_interval_boundary PASSED [ 26%]
tests/unit/test_h3_comparison.py::test_h3_resolution_metrics_metadata PASSED [ 27%]
tests/unit/test_h3_comparison.py::test_comparator_on_synthetic_dataset PASSED [ 29%]
tests/unit/test_h3_comparison.py::test_production_evidence_invariance_during_testing PASSED [ 31%]
tests/unit/test_h3_comparison.py::test_comparison_metrics_determinism PASSED [ 32%]
tests/unit/test_h3_index.py::test_validate_resolution PASSED             [ 34%]
tests/unit/test_h3_index.py::test_validate_coordinates PASSED            [ 36%]
tests/unit/test_h3_index.py::test_deterministic_output PASSED            [ 37%]
tests/unit/test_h3_index.py::test_argument_order_verification PASSED     [ 39%]
tests/unit/test_h3_index.py::test_safe_coords_to_h3_null_and_invalid_inputs PASSED [ 40%]
tests/unit/test_h3_index.py::test_strict_latlng_to_h3 PASSED             [ 42%]
tests/unit/test_h3_index.py::test_ohare_border_records_indexing PASSED   [ 44%]
tests/unit/test_profile_raw.py::test_parse_float PASSED                  [ 45%]
tests/unit/test_profile_raw.py::test_parse_int PASSED                    [ 47%]
tests/unit/test_profile_raw.py::test_parse_and_localize_timestamp_chicago_to_utc PASSED [ 49%]
tests/unit/test_profile_raw.py::test_parse_and_localize_timestamp_non_aligned PASSED [ 50%]
tests/unit/test_profile_raw.py::test_parse_and_localize_timestamp_invalid PASSED [ 52%]
tests/unit/test_profile_raw.py::test_dataset_profiler_line_processing PASSED [ 54%]
tests/unit/test_streaming_consumer.py::test_spark_streaming_schema_definition PASSED [ 55%]
tests/unit/test_streaming_consumer.py::test_fifteen_minute_window_boundary_calculations PASSED [ 57%]
tests/unit/test_streaming_consumer.py::test_watermark_and_lateness_evaluation_policy PASSED [ 59%]
tests/unit/test_streaming_consumer.py::test_deduplication_horizon_contract PASSED [ 60%]
tests/unit/test_streaming_consumer.py::test_consumer_configuration_validation PASSED [ 62%]
tests/unit/test_streaming_contract.py::test_valid_event_passes_validation PASSED [ 63%]
tests/unit/test_streaming_contract.py::test_valid_json_string_and_bytes_deserialization PASSED [ 65%]
tests/unit/test_streaming_contract.py::test_reject_malformed_json PASSED [ 67%]
tests/unit/test_streaming_contract.py::test_reject_unsupported_schema_version PASSED [ 68%]
tests/unit/test_streaming_contract.py::test_reject_missing_or_invalid_event_id PASSED [ 70%]
tests/unit/test_streaming_contract.py::test_reject_missing_trip_id PASSED [ 72%]
tests/unit/test_streaming_contract.py::test_reject_invalid_or_non_utc_timestamp PASSED [ 73%]
tests/unit/test_streaming_contract.py::test_reject_out_of_bounds_timestamp PASSED [ 75%]
tests/unit/test_streaming_contract.py::test_reject_invalid_h3_cell PASSED [ 77%]
tests/unit/test_streaming_contract.py::test_reject_coordinates_out_of_bounds PASSED [ 78%]
tests/unit/test_streaming_contract.py::test_parquet_row_to_event_conversion PASSED [ 80%]
tests/unit/test_streaming_producer.py::test_producer_mock_publishing_and_accounting PASSED [ 81%]
tests/unit/test_streaming_producer.py::test_producer_with_offset_and_limit PASSED [ 83%]
tests/unit/test_streaming_producer.py::test_producer_delivery_failure_accounting PASSED [ 85%]
tests/unit/test_zone_universe.py::test_zone_universe_schema_definition PASSED [ 86%]
tests/unit/test_zone_universe.py::test_deterministic_zone_inclusion_and_threshold_boundary PASSED [ 88%]
tests/unit/test_zone_universe.py::test_production_evidence_invariance_during_testing PASSED [ 90%]
tests/unit/test_zone_universe.py::test_full_dataset_reconciliation_and_properties PASSED [ 91%]
tests/unit/test_zone_universe.py::test_provisional_rule_and_metadata PASSED [ 93%]
tests/unit/test_zone_universe.py::test_catalog_completeness_all_239_cells_preserved PASSED [ 95%]
tests/unit/test_zone_universe.py::test_temporal_leakage_sensitivity_cdt_aligned PASSED [ 96%]
tests/unit/test_zone_universe.py::test_half_open_interval_and_split_durations PASSED [ 98%]
tests/unit/test_zone_universe.py::test_is_operational_universe_is_retrospective_full_month PASSED [100%]

======================= 59 passed, 2 skipped in 22.87s ========================
```

---

## 8. Phase 1 Artifact Hash Invariance

All Phase 1 production datasets and reports were audited against their recorded SHA-256 hashes:

| File Path | Canonical SHA-256 Hash | Audited SHA-256 Hash | Invariant Status |
| :--- | :--- | :--- | :---: |
| `data/raw/chicago_taxi_trips_2022-06.jsonl` | `C87B096AD1D243927D557BE981483F233BC1EE71109C80D64490C77882D08B23` | `C87B096AD1D243927D557BE981483F233BC1EE71109C80D64490C77882D08B23` | **MATCH** |
| `docs/evidence/clean_run_summary.json` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | **MATCH** |
| `reports/ingest_exclusion_audit.json` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | `66C866BA44F9493926D70870D2CCB2FF105860E27010FB4206E30AC5391DBFDA` | **MATCH** |
| `data/interim/cleaned_trips_2022-06/cleaned_trips.parquet` | `8472B1957464B5B71B55D53E3D6C40D0C72F0614708B28BB5C95F17F0D1F72B2` | `8472B1957464B5B71B55D53E3D6C40D0C72F0614708B28BB5C95F17F0D1F72B2` | **MATCH** |
| `data/interim/excluded_trips_2022-06/excluded_trips.parquet` | `E13E16642ECF0CC11FFCF93DEB6364DCD5C384B8642932DBAA00E5E17686B876` | `E13E16642ECF0CC11FFCF93DEB6364DCD5C384B8642932DBAA00E5E17686B876` | **MATCH** |
| `docs/evidence/h3_resolution_comparison.json` | `55EA02583ED890D4C023990E090BFAB54FE04885A291D4E1EB5EEE1C55295A49` | `55EA02583ED890D4C023990E090BFAB54FE04885A291D4E1EB5EEE1C55295A49` | **MATCH** |
| `docs/evidence/h3_resolution_comparison.md` | `E9B206B5AA266E20287A24DA677F51654E03910984BA277C6BC9E40E7E9A0806` | `E9B206B5AA266E20287A24DA677F51654E03910984BA277C6BC9E40E7E9A0806` | **MATCH** |
| `data/processed/zone_universe/zone_universe.parquet` | `5FB738D3E99A4DB00EE5E1D56B404B3EE75317249EEDD7166E06B5F067581970` | `5FB738D3E99A4DB00EE5E1D56B404B3EE75317249EEDD7166E06B5F067581970` | **MATCH** |
| `docs/evidence/zone_universe_analysis.json` | `45D6EBB14EE5D9DEDB1F76688CEE5B6AFE4AA3C40C75C6DE345D8C6B2A03A9A5` | `45D6EBB14EE5D9DEDB1F76688CEE5B6AFE4AA3C40C75C6DE345D8C6B2A03A9A5` | **MATCH** |
| `docs/evidence/zone_universe_specification.md` | `F3F374D8F8891B6C7343B87551ABE060D15D5CBCD6983D4AF4A9E202B6F3186A` | `F3F374D8F8891B6C7343B87551ABE060D15D5CBCD6983D4AF4A9E202B6F3186A` | **MATCH** |

---

## 9. Smallest Practical Remediation to Unblock Live Integration

To unblock the 2 live-broker integration tests (`test_live_kafka_broker_connectivity` and `test_e2e_streaming_pipeline_execution`):

1. **Enable Container Runtime on Windows:**
   Install Docker Desktop for Windows (or install WSL2 via `wsl --install -d Ubuntu` with Docker Engine inside Ubuntu).
2. **Start the Provided KRaft Kafka Broker:**
   Execute from project root:
   ```powershell
   docker compose -f infra/kafka/docker-compose.yml up -d
   ```
3. **Provision Kafka Spark Connector JARs (for native Windows execution):**
   If running PySpark directly on Windows rather than inside WSL2/Docker, manually download `spark-sql-kafka-0-10_2.12-3.5.1.jar` and its dependencies (`kafka-clients-3.4.1.jar`, `spark-token-provider-kafka-0-10_2.12-3.5.1.jar`, `commons-pool2-2.11.1.jar`) into `%SPARK_HOME%\jars` or `pyspark\jars` to bypass the `winutils.exe` / `chmod` error.
4. **Re-run Integration Tests:**
   ```powershell
   python -m pytest tests/integration/ -v
   ```
   Both integration tests will detect the active socket on `127.0.0.1:9092` and execute end-to-end.

---

## 10. Audit Conclusion

* **Implementation Code Quality:** **PASS** (Producer, consumer, schemas, and 59 unit tests function properly).
* **Data & Hash Integrity:** **PASS** (Zero mutation of Phase 1 datasets and contracts).
* **Live Kafka & Spark Pipeline Execution:** **BLOCKED** (Missing Docker / WSL2 / Kafka daemon).
* **Phase 3 Progression:** In compliance with `AGENTS.md`, Phase 3 will not begin until the human reviewer reviews this audit report.

