# RideIntel: Chicago Ride Demand & Spatial Pressure Analytics Platform

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.142.2-green.svg)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-cyan.svg)](https://react.dev/)
[![Tailwind CSS v4](https://img.shields.io/badge/TailwindCSS-v4-38bdf8.svg)](https://tailwindcss.com/)
[![H3 Spatial Index](https://img.shields.io/badge/Uber%20H3-Res%208-orange.svg)](https://h3geo.org/)

RideIntel is an end-to-end urban mobility intelligence and decision-support platform built on historical Chicago taxi trips and simulated fleet supply. It features Uber H3 spatial resolution 8 indexing, machine learning demand forecasting, dynamic supply-demand pressure evaluation, real-time surge detection, and an interactive React geospatial dashboard.

---

## 🚀 Key Features

- **Spatial Demand Aggregation**: Partitions Chicago into Uber H3 Resolution 8 hexagonal cells (~460m edge length), aggregating historical trips into 15-minute sliding windows.
- **Machine Learning Demand Forecasting**: Multi-horizon forecasting comparing XGBoost against rolling average and week-over-week seasonal baselines.
- **Supply & Capacity Pressure Modeling**: Evaluates real-time demand-to-supply pressure ratios ($P = D / C$) across four strict decision regimes (`NORMAL`, `ELEVATED`, `HIGH_PRESSURE`, and `NO_ESTIMATED_CAPACITY`).
- **Surge Detection Engine**: Automated surge detection flagging sudden spikes in demand relative to local supply capacity and historical baselines.
- **Geospatial Fleet Simulation**: Deterministic in-memory simulation engine modeling vehicle states (`AVAILABLE`, `PICKUP`, `ON_TRIP`, `OFFLINE`) and concentric dispatch across H3 rings.
- **Interactive Dashboard**: Responsive web frontend with Leaflet choropleth maps, live fleet simulation controls, pressure heatmaps, and model performance metrics.

---

## 🏗️ Architecture

```
rideintel/
├── api/                    # FastAPI backend service
│   ├── routers/            # Endpoints: forecasts, pressure, surge, simulation, metrics
│   └── services/           # Fleet simulation and artifact loaders
├── frontend/               # React 19 + Vite + Tailwind CSS dashboard
│   ├── src/components/     # UI views: Map, Zone Intelligence, Surge, System Status
│   └── src/services/       # API client & H3 zone catalog
├── data/
│   ├── contracts/          # Schemas and validation definitions
│   └── processed/          # Pre-computed parquet artifacts for instant execution
├── contracts/              # OpenAPI specs, Parquet schemas, and event contracts
├── docs/                   # Dataset cards, cleaning policies, and architecture evidence
├── pipeline/               # Ingest, Spark windowing, and streaming aggregation
├── models/                 # Model definitions and training pipelines
└── tests/                  # Contract, unit, and integration tests
```

---

## ⚡ Quickstart

### Prerequisites

- Python 3.12+ (or 3.13 / 3.14)
- Node.js 20+ and npm

### 1. Backend Setup

```bash
# Install Python dependencies
pip install -r requirements.txt

# Start the FastAPI server
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```
- API Health: [http://127.0.0.1:8000/api/admin/health](http://127.0.0.1:8000/api/admin/health)
- Swagger Documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 2. Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```
- Web Application: [http://localhost:5173](http://localhost:5173)

---

## 📊 Core API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/admin/health` | GET | System and artifact readiness status |
| `/api/forecasts` | GET | Spatial demand forecasts by H3 cell |
| `/api/pressure` | GET | Zone supply-demand pressure status |
| `/api/surge` | GET | Active surge alerts and anomalies |
| `/api/simulation/state`| GET | Live simulated fleet locations and trip lifecycles |
| `/api/simulation/tick` | POST | Advance simulation clock by 1 tick |
| `/api/metrics` | GET | Evaluated model metrics (MAE, RMSE, WAPE) |

---

## 📜 License

MIT License. Designed for urban mobility research and demand-supply analytics.
