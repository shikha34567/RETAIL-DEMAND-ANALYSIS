# RideIntel Phase 5A — FastAPI Backend Documentation

**Project:** RideIntel — Chicago Ride Demand Analysis  
**Component:** Phase 5A Backend REST API  
**Status:** Implemented & Verified  
**Default Host & Port:** `http://127.0.0.1:8000`  
**Interactive Swagger UI:** `http://127.0.0.1:8000/docs`  
**ReDoc Specification:** `http://127.0.0.1:8000/redoc`  

---

## 1. Overview & Architecture

The RideIntel Phase 5A backend is a production-grade, read-only FastAPI application designed to serve the complete Phase 1–4 project artifacts to the future React web interface.

The backend does not query a live database, retrain models, or simulate new driver inventory on the fly. Instead, it serves validated, cached, read-only Parquet and JSON pipeline artifacts with zero lookahead, rigorous parameter validation, and strict contract conformance.

### Project Layout

```text
api/
├── __init__.py
├── main.py                     # Application entry point, CORS middleware, exception handlers
├── config.py                   # Configuration and artifact path resolution
├── dependencies.py             # FastAPI dependency injection for ArtifactService
├── schemas.py                  # Pydantic response models and validation schemas
├── routers/
│   ├── __init__.py
│   ├── health.py               # GET /api/v1/health & GET /api/v1/metadata
│   ├── forecasts.py            # GET /api/v1/forecasts
│   ├── pressure.py             # GET /api/v1/pressure
│   ├── surge.py                # GET /api/v1/surge-alerts
│   └── metrics.py              # GET /api/v1/metrics
└── services/
    ├── __init__.py
    └── artifact_service.py     # Thread-safe cached loader, filter, and serializer
```

---

## 2. Installation & Quickstart

### 2.1 Dependencies Installation

Run the following command in Windows PowerShell inside the repository root:

```powershell
python -m pip install -r requirements.txt
```

### 2.2 Launching the API Server

Start the local development server with auto-reload:

```powershell
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Once running:
- **Interactive API Docs (Swagger):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **API Metadata:** [http://127.0.0.1:8000/api/v1/metadata](http://127.0.0.1:8000/api/v1/metadata)
- **Health Check:** [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

---

## 3. Endpoints Specification

### 3.1 Health Check & Metadata

#### `GET /api/v1/health`
Returns the operational status of the service and accessibility of all underlying data artifacts.
- **Success (200 OK):** All artifacts present and readable.
- **Service Unavailable (503):** One or more required artifacts missing or corrupt.

```json
{
  "status": "HEALTHY",
  "version": "0.1.0",
  "timestamp": "2026-10-11T15:20:00.000000Z",
  "components": [
    {
      "name": "zone_universe",
      "status": "HEALTHY",
      "path": "zone_universe.parquet",
      "records": 239,
      "detail": "139 operational zones out of 239"
    },
    {
      "name": "forecast_store",
      "status": "HEALTHY",
      "path": "forecasts.parquet",
      "records": 349515,
      "detail": "Models: ['xgboost', 'baseline_rolling_avg', 'baseline_same_time_last_week']"
    },
    {
      "name": "pressure_store",
      "status": "HEALTHY",
      "path": "zone_pressure_status.parquet",
      "records": 116505,
      "detail": "Pressure levels: ['LOW', 'NO_CAPACITY', 'MODERATE', 'CRITICAL', 'HIGH']"
    },
    {
      "name": "surge_store",
      "status": "HEALTHY",
      "path": "surge_alerts.parquet",
      "records": 8,
      "detail": "8 surge alerts persisted"
    },
    {
      "name": "metrics_summary",
      "status": "HEALTHY",
      "path": "forecasting_evaluation_summary.json",
      "records": 3,
      "detail": "Held-out test metrics available"
    }
  ]
}
```

#### `GET /api/v1/metadata`
Returns data governance metadata, coordinate resolutions, timezones, and simulation disclaimers.

```json
{
  "dataset_period": "2022-06-01T05:00:00Z to 2022-07-01T05:00:00Z",
  "split_boundary_utc": "2022-06-22T05:00:00Z",
  "storage_timezone": "UTC",
  "display_timezone": "America/Chicago",
  "operational_zone_count": 135,
  "forecast_eligible_zones": 135,
  "retrospective_operational_zones": 139,
  "total_catalog_zones": 239,
  "h3_resolution": 8,
  "window_minutes": 15,
  "forecast_horizon_minutes": 30,
  "available_models": ["baseline_rolling_avg", "baseline_same_time_last_week", "xgboost"],
  "default_model": "xgboost",
  "source_labels": {
    "observed_demand": "HISTORICAL",
    "predicted_rides": "PREDICTED",
    "available_vehicles": "SIMULATED",
    "estimated_capacity": "SIMULATED_ESTIMATE",
    "demand_supply_pressure": "ESTIMATED"
  },
  "streaming_status": "OFFLINE_PROTOTYPE (Host Docker/WSL2 unavailable; live Kafka broker tests skipped)",
  "supply_data_status": "SIMULATED_ESTIMATE (Synthetic driver supply simulation seeded per origin)",
  "disclaimer": "All vehicle counts and supply capacity values are SIMULATED decision-support estimates. No live fleet tracking or real-world driver inventory is present in the historical Chicago taxi dataset."
}
```

---

### 3.2 Demand Forecasts

#### `GET /api/v1/forecasts`
Serves forward 30-minute demand predictions ($[T, T + 30\text{m})$).

**Query Parameters:**
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `model` | string | `xgboost` | Model identifier: `xgboost`, `baseline_rolling_avg`, `baseline_same_time_last_week` |
| `zone` | string | `null` | Optional H3 Resolution 8 cell identifier |
| `start` | ISO-8601 | `null` | Filter `forecast_origin >= start` (UTC) |
| `end` | ISO-8601 | `null` | Filter `forecast_origin <= end` (UTC) |
| `limit` | integer | `50` | Number of items to return (1 – 1000) |
| `offset` | integer | `0` | Pagination offset |

**Example Request:**
```http
GET /api/v1/forecasts?model=xgboost&zone=882664cf21fffff&limit=2
```

**Example Response (200 OK):**
```json
{
  "total_records": 863,
  "limit": 2,
  "offset": 0,
  "model_name": "xgboost",
  "data": [
    {
      "forecast_id": "fc-f6c7d48d66c6",
      "h3_cell": "882664cf21fffff",
      "forecast_origin": "2022-06-22T05:00:00Z",
      "target_start": "2022-06-22T05:00:00Z",
      "target_end": "2022-06-22T05:30:00Z",
      "predicted_rides": 3.8421,
      "model_name": "xgboost",
      "model_version": "v1.0.0",
      "forecast_status": "CURRENT",
      "source_type": "PREDICTED"
    }
  ]
}
```

---

### 3.3 Demand-Supply Pressure

#### `GET /api/v1/pressure`
Serves 30-minute demand-supply pressure evaluation records. Missing numeric ratios are serialized strictly as JSON `null` (never NaN or infinity).

**Query Parameters:**
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `zone` | string | `null` | Optional H3 Resolution 8 cell |
| `pressure_level` | string | `null` | Filter by level: `LOW`, `MODERATE`, `HIGH`, `CRITICAL`, `NO_CAPACITY` |
| `start` | ISO-8601 | `null` | Filter `forecast_origin >= start` (UTC) |
| `end` | ISO-8601 | `null` | Filter `forecast_origin <= end` (UTC) |
| `limit` | integer | `50` | Pagination page size (1 – 1000) |
| `offset` | integer | `0` | Pagination offset |

**Example Request:**
```http
GET /api/v1/pressure?pressure_level=NO_CAPACITY&limit=1
```

**Example Response (200 OK):**
```json
{
  "total_records": 39183,
  "limit": 1,
  "offset": 0,
  "data": [
    {
      "h3_cell": "8826641915fffff",
      "forecast_origin": "2022-06-22T05:00:00Z",
      "target_start": "2022-06-22T05:00:00Z",
      "target_end": "2022-06-22T05:30:00Z",
      "model_name": "xgboost",
      "capacity_rate_r": 2.0,
      "forecast_demand_rides_30m": 0.0693,
      "predicted_rides_D": 0.0693,
      "simulated_available_vehicles": 0,
      "available_vehicles_V": 0,
      "estimated_supply_capacity_rides_30m": 0.0,
      "estimated_capacity_C": 0.0,
      "demand_supply_ratio": null,
      "pressure_index": null,
      "estimated_unserved_demand_rides": 0.0693,
      "pressure_status": "NO_ESTIMATED_CAPACITY",
      "pressure_level": "NO_CAPACITY",
      "input_status": "OK",
      "supply_data_status": "SIMULATED_ESTIMATE",
      "is_potential_surge": false,
      "surge_severity": "NONE",
      "source_type": "ESTIMATED"
    }
  ]
}
```

---

### 3.4 Surge Alerts

#### `GET /api/v1/surge-alerts`
Serves persisted heuristic surge alerts flagged in Phase 4.

**Query Parameters:**
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `zone` | string | `null` | Optional H3 cell filter |
| `severity` | string | `null` | Filter: `HIGH` or `CRITICAL` |
| `start` / `end` | ISO-8601 | `null` | UTC origin range |
| `limit` / `offset` | integer | `50` / `0` | Pagination |

**Example Request:**
```http
GET /api/v1/surge-alerts?severity=CRITICAL
```

**Example Response (200 OK):**
```json
{
  "total_records": 3,
  "limit": 50,
  "offset": 0,
  "disclaimer": "SIMULATED_ESTIMATE: Surge alerts are heuristic decision-support flags computed against simulated supply scenarios. They do not represent real-world price surges.",
  "data": [
    {
      "alert_id": "alert-ce6d2948df5a",
      "h3_cell": "882664cf21fffff",
      "detected_at": "2022-06-23T16:45:00Z",
      "forecast_origin": "2022-06-23T16:45:00Z",
      "observed_demand": 6,
      "predicted_demand": 6.1644,
      "baseline_demand": null,
      "severity": "CRITICAL",
      "simulation_run_id": "sim-676cb38f",
      "source_type": "SIMULATED_ESTIMATE"
    }
  ]
}
```

---

### 3.5 Model Evaluation Metrics

#### `GET /api/v1/metrics`
Serves held-out test evaluation metrics (MAE, RMSE, WAPE) evaluated on the identical 116,505 rows across all three models.

**Query Parameters:**
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `model` | string | `null` | Optional filter for single model (`xgboost`, etc.) |

**Example Request:**
```http
GET /api/v1/metrics?model=xgboost
```

**Example Response (200 OK):**
```json
{
  "evaluation_type": "HELD_OUT_TEST_SET",
  "test_interval": {
    "start": "2022-06-22T05:00:00Z",
    "end": "2022-07-01T05:00:00Z",
    "total_test_days": 9
  },
  "test_rows_per_model": 116505,
  "overall_metrics": {
    "xgboost": {
      "model_name": "xgboost",
      "model_version": "v1.0.0",
      "count": 116505,
      "sum_actual": 340399.0,
      "mae": 0.931024,
      "rmse": 2.236630,
      "wape": 0.318653,
      "wape_status": "VALID"
    }
  },
  "density_group_breakdown": [...],
  "hourly_breakdown": [...],
  "notes": "All models were evaluated on the identical set of 116,505 held-out test rows (863 prediction origins x 135 operational zones). Metrics are strictly historical and never recomputed or fabricated at runtime."
}
```

---

## 4. Error Handling Protocol

All API errors adhere to standard HTTP status codes and provide clean diagnostic JSON payloads without leaking local filesystem paths or internal stack traces:

| HTTP Status | Error Code | Description / Trigger |
| :--- | :--- | :--- |
| **400 Bad Request** | `INVALID_PARAMETER` | Malformed parameters, `start > end`, unknown model, or invalid severity string |
| **404 Not Found** | `RESOURCE_NOT_FOUND` | Queried H3 zone is not in the zone universe catalog |
| **422 Unprocessable** | `VALIDATION_ERROR` | FastAPI parameter type or pagination bound failure (`limit < 1` or `limit > 1000`) |
| **503 Unavailable** | `ARTIFACT_UNAVAILABLE` | Required underlying Parquet/JSON file cannot be located or read |
| **500 Server Error** | `INTERNAL_ERROR` | Sanitized server error message |

---

## 5. Security & Configuration

1. **CORS:** Restricted by default to local React development origins:
   - `http://localhost:5173`
   - `http://127.0.0.1:5173`
   - Configurable via the `RIDEINTEL_CORS_ORIGINS` environment variable.
2. **Secrets:** Zero API keys or database credentials are required or embedded.
3. **Immutability:** Every request is strictly read-only. Production Parquet and JSON files are never modified by the API.

