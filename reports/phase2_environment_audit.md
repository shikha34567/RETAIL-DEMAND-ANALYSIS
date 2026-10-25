# RideIntel Phase 2 — Runtime Environment Audit & Compatibility Analysis

**Audit Date:** 2026-10-11  
**Project:** RideIntel (Chicago Taxi Ride Demand Analysis)  
**Phase:** Phase 2 — Kafka + Spark Structured Streaming Pipeline  
**Auditor:** Lead Data Engineer  

---

## 1. Existing Environment & Detected Versions

An empirical audit was executed directly against the local host environment. The detected runtime components and their versions are recorded below:

| Component | Target Spec (`AGENTS.md`) | Detected Host Version | Status / Verdict |
| :--- | :--- | :--- | :--- |
| **Operating System** | WSL2 (Ubuntu / Debian) | **Windows 11 AMD64 (Native, non-WSL)** | **MISMATCH** (WSL2 is not installed) |
| **Python** | Python 3.12 (not 3.13) | **Python 3.13.9** (64-bit AMD64) | **COMPATIBILITY CONCERN** (PySpark worker incompatibility) |
| **Java** | Java 17 or 21 | **Java 21.0.10 LTS** (`C:\Program Files\Java\jdk-21.0.10`) | **INSTALLED** (`JAVA_HOME` not set in system env) |
| **Docker Engine** | Docker Compose supported | **NOT INSTALLED** (`docker: NOT FOUND`) | **HARD PREREQUISITE MISSING** |
| **WSL2** | Ubuntu / Linux subsystem | **NOT INSTALLED** (`wsl.exe --install` required) | **PREREQUISITE MISSING** |
| **Apache Kafka** | Distributed Broker / KRaft | **NOT RUNNING** (No local daemon or container) | **BROKER MISSING** |
| **PySpark** | Spark 3.5.x | **PySpark 3.5.1** (Installed via pip) | **PARTIALLY COMPATIBLE** (SQL works, UDFs crash on 3.13) |
| **Kafka Python Client** | `confluent-kafka` | **confluent-kafka 2.16.0** (librdkafka C bindings) | **INSTALLED & VERIFIED** |
| **PyArrow** | PyArrow 14+ | **PyArrow 25.0.1** | **INSTALLED & VERIFIED** |
| **H3-py** | H3 v3.7 or v4 | **h3 4.5.0** | **INSTALLED & VERIFIED** |
| **pytest** | pytest 8+ | **pytest 9.0.2** | **INSTALLED & VERIFIED** |

---

## 2. Compatibility & Diagnostic Findings

### Finding A: PySpark 3.5.1 vs. Python 3.13 Worker Crash
* **Empirical Test:** Running an RDD operation or Python UDF through PySpark on Python 3.13 caused `java.lang.Exception: Python worker exited unexpectedly (crashed)`.
* **Root Cause:** PySpark 3.5.1 worker protocol (`pyspark/worker.py`) is incompatible with Python 3.13's internal C-API and module changes. Official PySpark 3.5.x support targets Python 3.8–3.12, as explicitly noted in `AGENTS.md` (`Python 3.12 (not 3.13)`).
* **Mitigation / Feasibility:** Pure Spark SQL Catalyst expressions (e.g., `from_json`, `to_timestamp`, `window()`, `groupBy()`, `count()`) run **100% inside the JVM without invoking Python worker sub-processes**. In testing, `spark.read.parquet()` and Catalyst aggregation succeeded without error. Therefore, the streaming consumer must be architected strictly using native Catalyst functions rather than Python UDFs.

### Finding B: Windows Hadoop Native Binaries (`winutils.exe` / `hadoop.dll`)
* **Empirical Test:** Attempting to download external JAR packages via Spark's `spark.jars.packages` configuration triggered `java.io.FileNotFoundException: HADOOP_HOME and hadoop.home.dir are unset.` followed by a failure in `org.apache.hadoop.fs.FileUtil.chmod`.
* **Root Cause:** On Windows, Apache Hadoop's filesystem utility relies on `winutils.exe` to manipulate POSIX file permissions (`chmod`). When `winutils.exe` is absent, Spark cannot set permissions on fetched dependency jars.
* **Mitigation / Feasibility:** Spark Structured Streaming code must be written with decoupled execution drivers. For local unit testing and parsing logic, pure PySpark / PyArrow validation pipelines can run deterministically. When deploying to a full Kafka-integrated cluster, WSL2 or a Linux container with proper Hadoop binaries is required.

### Finding C: Kafka Broker Availability
* **Empirical Test:** `docker --version` reported `NOT FOUND`. `where.exe kafka-server-start` reported `NOT FOUND`. No process is listening on port 9092.
* **Root Cause:** Neither Docker Desktop nor a standalone Apache Kafka distribution is installed on the host OS.
* **Mitigation / Feasibility:**
  1. The Kafka Producer (`pipeline/streaming/producer.py`) will be implemented using `confluent-kafka` with configurable bootstrap servers, delivery callbacks, batching, replay pacing, and full accounting.
  2. Unit tests will validate serialization, schema conformance, error handling, and producer accounting using mock adapters and test fixtures.
  3. Integration tests requiring a live broker on `localhost:9092` will be provided, but gracefully tagged as `BLOCKED: No active Kafka broker detected on localhost:9092`.
  4. Exact Docker Compose and Linux setup instructions will be documented for reproducibility when the user enables Docker or WSL2.

---

## 3. Recommended Execution Strategy

To satisfy academic engineering standards while respecting the host's actual runtime constraints:

1. **Strict Decoupling of Contract & Implementation:**
   - Define a formal, machine-readable streaming event contract (`docs/contracts/streaming_event_contract.md` and schema validator in `pipeline/streaming/event_schema.py`).
   - Validate every record against strict types, UTC ISO 8601 timestamps, and H3 Resolution 8 cell validity.
2. **Production-Ready Kafka Producer:**
   - Implement `pipeline/streaming/producer.py` to stream from `data/interim/cleaned_trips_2022-06/cleaned_trips.parquet`.
   - Implement configurable replay speed, batch sizes, finite test fixtures, and error accounting.
3. **Production-Ready Spark Structured Streaming Consumer:**
   - Implement `pipeline/streaming/consumer.py` using **native Spark SQL Catalyst functions** (`from_json`, `to_timestamp`, `window`, `withWatermark`) to prevent Python 3.13 worker crashes.
   - Configure 15-minute event-time tumbling windows and a 10-minute watermark.
   - Implement deduplication on `(event_id, event_ts)` and checkpointing.
4. **Comprehensive Test Suite:**
   - Write comprehensive unit tests in `tests/unit/test_streaming_contract.py`, `tests/unit/test_streaming_producer.py`, and `tests/unit/test_streaming_consumer.py`.
   - Provide integration test harness in `tests/integration/test_streaming_pipeline.py`.
   - Report live broker integration tests as `BLOCKED` with actionable remediation commands.

---

## 4. Files to be Modified or Created

### New Pipeline Modules:
- `pipeline/streaming/__init__.py`
- `pipeline/streaming/event_schema.py`: Shared streaming schema, event contract validation, and reason codes.
- `pipeline/streaming/producer.py`: High-throughput, bounded Kafka producer reading cleaned Parquet.
- `pipeline/streaming/consumer.py`: Spark Structured Streaming application with event-time windowing and checkpointing.

### New Contracts & Documentation:
- `docs/contracts/streaming_event_contract.md`: Schema, keying strategy, and watermark policy.
- `infra/kafka/docker-compose.yml`: Reproducible KRaft/Zookeeper Kafka broker setup for deployment.
- `reports/phase2_environment_audit.md`: This audit document.
- `reports/phase2_implementation_report.md`: Final evidence-based report.

### New Test Suites:
- `tests/unit/test_streaming_contract.py`: Contract schema, timestamp, H3, and serialization tests.
- `tests/unit/test_streaming_producer.py`: Producer batching, accounting, and error-handling tests.
- `tests/unit/test_streaming_consumer.py`: Windowing logic, watermark boundary, and aggregation tests.
- `tests/integration/test_streaming_pipeline.py`: End-to-end Kafka/Spark pipeline integration tests.

### Configuration Updates:
- `settings.yaml`: Add streaming Kafka topic, watermark, and bootstrap server defaults.

---

## 5. Risks and Mitigation Matrix

| Risk | Impact | Mitigation |
| :--- | :--- | :--- |
| **No Local Kafka Broker** | Live integration test fails | Provide full code, Docker Compose file, and explicit diagnostic check that marks live integration as `BLOCKED` rather than pretending it passed. |
| **Python 3.13 Worker Crash** | PySpark crashes on Python UDFs | Build Spark Structured Streaming transformations using 100% native Catalyst SQL expressions (`F.from_json`, `F.window`, `F.count`). |
| **Hadoop `winutils.exe` Missing** | External jar resolution fails | Document dependency requirements; provide self-contained driver scripts and standalone verification harnesses. |
| **Phase 1 Contract Mutation** | Broken upstream reproducibility | Treat Phase 1 Parquet datasets (`cleaned_trips.parquet`, `zone_universe.parquet`) as immutable read-only inputs. |
| **Lookahead Leakage in Streaming** | Future data influences window aggregates | Use strictly original event-time (`event_ts`) with 10-minute watermark. Never substitute processing wall-clock time for event time. |

