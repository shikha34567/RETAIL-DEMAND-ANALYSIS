# Dataset Card: City of Chicago Transportation Datasets (Taxi & TNP)

STATUS: VERIFIED DOWNLOAD COMPLETED (June 1, 2022 to July 1, 2022)  
RAW STORAGE: `data/raw/chicago_taxi_trips_2022-06.jsonl` (Immutable)  
EVIDENCE REPOSITORY: `docs/evidence/`

---

## 1. Overview & Dataset Candidates

RideIntel requires historical trip data from the City of Chicago to replay events through Kafka, aggregate demand in Spark, and forecast 30-minute demand. Two official open datasets provided by the City of Chicago Department of Business Affairs & Consumer Protection (BACP) were inspected:

| Attribute | Candidate A: Chicago Taxi Trips | Candidate B: Transportation Network Providers (TNP / Rideshare) |
| :--- | :--- | :--- |
| **Dataset Title** | Taxi Trips (2013-2023) | Transportation Network Providers - Trips (2018-2022) |
| **Socrata Dataset ID** | `wrvz-psew` | `m6dm-c72p` |
| **Official Portal URL** | [Chicago Data Portal: Taxi Trips](https://data.cityofchicago.org/Transportation/Taxi-Trips-2013-2023-/wrvz-psew) | [Chicago Data Portal: TNP Trips](https://data.cityofchicago.org/Transportation/Transportation-Network-Providers-Trips-2018-2022-/m6dm-c72p) |
| **Data Publisher** | City of Chicago, BACP | City of Chicago, BACP |
| **License / Terms** | City of Chicago Terms of Use (Public Data) | City of Chicago Terms of Use (Public Data) |
| **Overall Date Range** | 2013-01-01 to 2023-12-31 (Subsequent data in `ajtu-isnz`) | 2018-11-01 to 2022-12-31 (Subsequent data in `n26f-ihde`, `6dvr-xwnh`) |
| **Total Estimated Volume** | ~200+ million trips across 10 years | ~360+ million trips across 4 years |
| **Measured June 2022 Volume** | **639,269 trips** (measured via SODA API) | ~5-7 million trips (estimated; query timed out at >30s) |
| **Daily Volume (2022-06-01)** | **20,447 trips** (verified) | ~200,000+ trips |
| **Weekly Volume (2022-06-01..08)**| **157,641 trips** (verified) | ~1.5 million trips |

---

## 2. Recommendation for RideIntel

**Recommendation:** **Chicago Taxi Trips (`wrvz-psew`), specifically a bounded historical slice (e.g., June 2022: 639,269 trips, or Q2 2022).**

### Rationale:
1. **Manageable Volume for Local Pipeline:** Taxi trips provide ~20k events/day and ~639k events/month. This volume is realistic and completely testable for local streaming replay, Kafka topic storage, Spark watermarked deduplication, and ML evaluation without requiring multi-node Spark cluster resources or exhausting disk space.
2. **Identical Schema and Spatial Properties:** Both Taxi and TNP share the exact same geographic centroid masking rules, same 15-minute timestamp truncation, and same 40-character `trip_id` structure. TNP does not provide finer coordinates than Taxi.
3. **Availability of Pre-filtered Views:** Annual slices (such as `npd7-ywjz` for 2022) and date-filtered exports are directly supported on the portal.

---

## 3. Schema & Field Definitions

Derived directly from the official Socrata metadata (`rows.json` / `sample_wrvz-psew.json`):

| Column Name | API Field Name | Portal Type | Description & Behavior |
| :--- | :--- | :--- | :--- |
| **Trip ID** | `trip_id` | `text` | Unique 40-character hex identifier per trip. Present in 100% of probed rows. |
| **Taxi ID** | `taxi_id` | `text` | Anonymized medallion identifier (Taxi only). |
| **Trip Start Timestamp** | `trip_start_timestamp` | `calendar_date` | Timestamp of trip start, **rounded to the nearest 15 minutes** by the City. Stored in Chicago local time (`America/Chicago`). |
| **Trip End Timestamp** | `trip_end_timestamp` | `calendar_date` | Timestamp of trip end, rounded to the nearest 15 minutes. |
| **Trip Seconds** | `trip_seconds` | `number` | Duration of trip in seconds. |
| **Trip Miles** | `trip_miles` | `number` | Distance in miles. |
| **Pickup Census Tract** | `pickup_census_tract` | `text` | Census tract of pickup. Suppressed for privacy in **92.3%** of Taxi rows and **63.4%** of TNP rows. |
| **Pickup Community Area** | `pickup_community_area` | `number` | Integer ID (1 to 77) of the 77 Chicago community areas. Missing in ~11.0% of Taxi rows (out-of-city trips). |
| **Pickup Centroid Latitude** | `pickup_centroid_latitude` | `number` | Latitude of polygon centroid (Census Tract or Community Area). Missing in ~11.0% of rows. |
| **Pickup Centroid Longitude**| `pickup_centroid_longitude`| `number` | Longitude of polygon centroid (Census Tract or Community Area). Missing in ~11.0% of rows. |
| **Pickup Centroid Location** | `pickup_centroid_location` | `point` | GeoJSON / WKT Point of the centroid. |
| **Fare** | `fare` | `number` | Base fare ($). Rounded to $2.50 in TNP; recorded in Taxi. |
| **Tips** | `tips` / `tip` | `number` | Recorded tip. Cash tips not recorded. |
| **Tolls** | `tolls` | `number` | Toll amount. |
| **Extras / Additional** | `extras` / `additional_charges` | `number` | Surcharges and fees. |
| **Trip Total** | `trip_total` | `number` | Total fare charged. |
| **Payment Type** | `payment_type` | `text` | Payment method (Cash, Credit Card, Mobile, etc.). |
| **Company** | `company` | `text` | Taxi affiliation/fleet operator. |

---

## 4. Key Data Characteristics & Verified Findings

### 4.1. Spatial Representation: Centroids, NOT Raw GPS
- **Finding:** The latitude and longitude columns are **polygon centroids**, NOT raw GPS traces.
- **Evidence:** In a 1,000-row sample of 2022-06-01 Taxi trips with 890 valid coordinates, there are only **75 distinct coordinate pairs** (compression ratio = 0.084). These 75 points correspond to the centroids of Chicago's 77 Community Areas.
- **Privacy Masking Rule:** When Census Tract volume is below privacy thresholds, Census Tract is set to `null` and the centroid defaults to the Community Area centroid. If a trip originates outside Chicago city limits, coordinates and community area are `null`.
- **Coordinate Precision:** Numbers are formatted with up to 9–11 decimal places (e.g. `41.980264315`), but the spatial precision is bounded by the polygon boundary (several square kilometers).

### 4.2. Timestamp Resolution & Timezone
- **Finding:** Raw timestamps are truncated to 15-minute intervals (`:00`, `:15`, `:30`, `:45`). Seconds are always `:00.000`.
- **Timezone:** Raw data timestamps are stored in Chicago local time without explicit UTC offset (`America/Chicago`).
- **Pipeline Requirement:** Ingest must parse `trip_start_timestamp` as `America/Chicago` (handling Daylight Saving Time transitions) and convert to UTC ISO 8601 string (`...Z`) before emitting to Kafka or saving to Parquet, per `AGENTS.md`.

### 4.3. Trip Identifier Stability & Deterministic `event_id`
- **Finding:** `trip_id` is present on 100% of records in the sampled slice. It is a stable, unique 40-character hexadecimal string.
- **Deterministic Hash:** Deterministic `event_id` generation via `sha1(dataset_id + ":" + trip_id)` is **fully supported** and will reliably reproduce across replays, retries, and restarts.

---

## 5. Data Quality Exclusions (Rules for Ingest)

Based on empirical inspection, the raw data contains records that must be handled during cleaning:

1. **Missing Geography Exclusions:** ~11% of records lack pickup coordinates and Community Area IDs (typically trips originating outside city boundaries). These cannot be mapped to an H3 cell or Chicago zone and must be logged as excluded in the ingestion exclusion log.
2. **Missing or Suppressed Census Tracts:** 92.3% of Taxi records have `null` Census Tracts due to City privacy suppression. Spatial grouping must therefore rely on `pickup_centroid_latitude`/`pickup_centroid_longitude` or `pickup_community_area`.
3. **Invalid Trips:** Records with `trip_seconds <= 0`, `trip_miles < 0`, or missing `trip_start_timestamp` exist in the raw dataset and must be filtered with counts recorded in the exclusion log.
4. **Duplicate Trips:** Deduplication on `event_id` must be applied within the watermark window.

---

## 6. Spatial Resolution & H3 Decision Plan

### Why H3 Resolution Cannot Be Chosen Yet:
Because coordinates are discretized to Community Area centroids (and occasionally Census Tract centroids), mapping coordinates to a very fine H3 resolution (e.g. Resolution 8 or 9) will map all trips in a community area to a single centroid cell, leaving all surrounding H3 cells inside the same community area with 0 demand.

### Required Spatial Comparison:
Before freezing the H3 resolution in `config/settings.yaml`, `pipeline/spatial` must evaluate:
- **Resolution 6** (avg area ~36 km²): larger than community areas (~8 km²), grouping multiple community areas.
- **Resolution 7** (avg area ~5.16 km², avg edge ~1.2 km): comparable to median community area size.
- **Resolution 8** (avg area ~0.74 km², avg edge ~461 m): smaller than community areas; centroid assignment will cause artificial demand spikes in single cells.
- **Alternative:** Zone universe defined by `pickup_community_area` directly vs. H3 cells containing polygon centroids.

The comparison will measure cell coverage, empty cell proportion, and demand variance across resolutions once raw data is ingested.

---

## 7. Verified Download Slice & File Details

The requested initial slice has been downloaded and verified against the official City of Chicago SODA API:

- **Dataset ID:** `wrvz-psew` (Taxi Trips 2013–2023)
- **Temporal Interval:** `[2022-06-01T00:00:00, 2022-07-01T00:00:00)` (Half-open, 30 days)
- **Local File Path:** `data/raw/chicago_taxi_trips_2022-06.jsonl`
- **File Size:** 585,444,485 bytes (558.32 MB)
- **Total Records:** **639,269** (Exact match with expected count: 639,269)
- **Unique Trip IDs:** 639,269 (0 duplicates across the entire monthly slice)
- **SHA-256 Checksum:** `c87b096ad1d243927d557be981483f233bc1ee71109c80d64490c77882d08b23`
- **Partitioned Daily Slices:** Stored in `data/raw/daily/taxi_trips_YYYY-MM-DD.jsonl` with manifest in `data/raw/download_manifest.json`
- **Download Script:** `pipeline/ingest/download_raw.py`
- **Download Verification Evidence:** `docs/evidence/raw_download_verification.json` and `docs/evidence/download_execution.txt`

