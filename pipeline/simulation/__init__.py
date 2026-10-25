"""
RideIntel Supply Simulation & Demand-Supply Pressure Package.

Implements:
1. Time-varying vehicle fleet supply simulation.
2. Demand-supply capacity alignment and pressure indexing.
3. Potential demand surge detection heuristics.
"""

from typing import Dict, Any

SOURCE_TYPE = "SIMULATED"
SUPPLY_DATA_STATUS = "SIMULATED_ESTIMATE"

# Pressure status codes conforming to contracts/parquet_schemas.md (Table 6)
STATUS_NORMAL = "NORMAL"
STATUS_ELEVATED = "ELEVATED"
STATUS_HIGH_PRESSURE = "HIGH_PRESSURE"
STATUS_NO_CAPACITY = "NO_ESTIMATED_CAPACITY"
STATUS_UNKNOWN = "UNKNOWN"

# High-level pressure levels
LEVEL_LOW = "LOW"
LEVEL_MODERATE = "MODERATE"
LEVEL_HIGH = "HIGH"
LEVEL_CRITICAL = "CRITICAL"
LEVEL_NO_CAPACITY = "NO_CAPACITY"
LEVEL_UNKNOWN = "UNKNOWN"

# Input status codes
INPUT_STATUS_OK = "OK"
INPUT_STATUS_MISSING = "MISSING"
INPUT_STATUS_STALE = "STALE"

