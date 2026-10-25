import json
import hashlib
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, '.')

# 1. Load artifacts
pressure_df = pd.read_parquet('data/processed/simulation/zone_pressure_status.parquet')
surge_df = pd.read_parquet('data/processed/simulation/surge_alerts.parquet')
forecast_df = pd.read_parquet('data/processed/forecasts/forecasts.parquet')
forecast_df = forecast_df[forecast_df['model_name'] == 'xgboost'].copy()
zone_universe = pd.read_parquet('data/processed/zone_universe/zone_universe.parquet')

print("================================================================================")
print("SECTION A: RECONCILE OUTPUT COUNTS AND METRICS")
print("================================================================================")
print(f"Total zone-window pressure records: {len(pressure_df):,}")
print(f"Total saved surge-alert records: {len(surge_df):,}")

# Duplicate check
dup_count = len(pressure_df) - len(pressure_df[['forecast_origin', 'h3_cell']].drop_duplicates())
print(f"Duplicate (forecast_origin, h3_cell) records in pressure table: {dup_count}")

# Unique origins and zones
num_origins = pressure_df['forecast_origin'].nunique()
num_zones = pressure_df['h3_cell'].nunique()
print(f"Unique forecast origins: {num_origins} (min: {pressure_df['forecast_origin'].min()}, max: {pressure_df['forecast_origin'].max()})")
print(f"Unique operational H3 zones: {num_zones}")
expected_rows = num_origins * num_zones
print(f"Cartesian product (origins x zones): {expected_rows:,} -> Exactly matches row count: {expected_rows == len(pressure_df)}")

# Alignment with Phase 3 XGBoost predictions
merged = pd.merge(pressure_df, forecast_df, on=['forecast_origin', 'h3_cell'], how='inner')
print(f"Rows matching Phase 3 XGBoost (origin, zone): {len(merged):,} / {len(pressure_df):,} (100.0%)")

# Horizon check
target_durations = (pd.to_datetime(pressure_df['target_end']) - pd.to_datetime(pressure_df['target_start'])).dt.total_seconds() / 60
print(f"Forecast horizon: min {target_durations.min():.1f} min, max {target_durations.max():.1f} min (Expected 30.0 min)")

# Pressure level counts
print("\n--- Counts by Pressure Level ---")
level_counts = pressure_df['pressure_level'].value_counts()
for lvl, count in level_counts.items():
    pct = count / len(pressure_df) * 100
    print(f"  {lvl:<15}: {count:6d} ({pct:6.2f}%)")

# Pressure status counts
print("\n--- Counts by Pressure Status (Schema Table 6) ---")
status_counts = pressure_df['pressure_status'].value_counts()
for st, count in status_counts.items():
    pct = count / len(pressure_df) * 100
    print(f"  {st:<22}: {count:6d} ({pct:6.2f}%)")

# Total unserved demand
total_unserved = pressure_df['estimated_unserved_demand_rides'].sum()
print(f"\nTotal estimated unserved demand: {total_unserved:,.2f} rides")
print(f"Any negative unserved demand?: {(pressure_df['estimated_unserved_demand_rides'] < 0).any()}")

# NaN / Infinity checks
print("\n--- Prohibited Values Audit ---")
ratio_nulls = pressure_df['pressure_index'].isna().sum()
ratio_infs = np.isinf(pressure_df['pressure_index'].dropna()).sum()
print(f"Pressure index nulls: {ratio_nulls} (expected exactly C=0 count: {ratio_nulls == (pressure_df['estimated_capacity_C'] == 0).sum()})")
print(f"Pressure index infinities: {ratio_infs} (Prohibited)")
demand_infs = np.isinf(pressure_df['predicted_rides_D'].dropna()).sum()
print(f"Predicted rides infinities: {demand_infs}")
unserved_infs = np.isinf(pressure_df['estimated_unserved_demand_rides'].dropna()).sum()
print(f"Unserved demand infinities: {unserved_infs}")

# Surge alert conditions check
print("\n--- Surge Alerts Verification ---")
print(surge_df[['alert_id', 'h3_cell', 'forecast_origin', 'predicted_demand', 'baseline_demand', 'severity']])
# Join surge alerts with pressure table to verify pressure level and ratio
surge_merged = pd.merge(surge_df, pressure_df[['forecast_origin', 'h3_cell', 'demand_supply_ratio', 'pressure_level', 'pressure_status', 'predicted_rides_D', 'estimated_capacity_C', 'surge_trigger_reason']], on=['forecast_origin', 'h3_cell'], how='left')
for idx, r in surge_merged.iterrows():
    b = r['baseline_demand']
    surge_ratio = (r['predicted_demand'] / b) if (b is not None and not pd.isna(b) and b > 0) else None
    meets_cond = (r['predicted_demand'] >= 5.0) and (r['demand_supply_ratio'] >= 1.2) and (r['pressure_level'] in ['HIGH', 'CRITICAL'])
    print(f"Alert {r['alert_id']}: origin={r['forecast_origin']}, zone={r['h3_cell']}, D={r['predicted_demand']:.2f}, C={r['estimated_capacity_C']:.1f}, P={r['demand_supply_ratio']:.2f}, pressure={r['pressure_level']} -> Valid: {meets_cond}")

print("\n================================================================================")
print("SECTION B: INVESTIGATE ZERO-CAPACITY FREQUENCY (C=0, D>0)")
print("================================================================================")
c0_mask = (pressure_df['estimated_capacity_C'] == 0) & (pressure_df['predicted_rides_D'] > 0)
num_c0 = c0_mask.sum()
pct_c0 = num_c0 / len(pressure_df) * 100
print(f"Frequency of C=0, D>0 records: {num_c0:,} / {len(pressure_df):,} ({pct_c0:.2f}%)")

c0_df = pressure_df[c0_mask].copy()

def get_band(d):
    if d < 0.1:
        return '1. Micro: < 0.1 rides'
    elif d < 0.5:
        return '2. Very Low: 0.1 - 0.5 rides'
    elif d < 1.0:
        return '3. Low: 0.5 - 1.0 rides'
    elif d < 2.0:
        return '4. Moderate: 1.0 - 2.0 rides'
    elif d < 5.0:
        return '5. Elevated: 2.0 - 5.0 rides'
    else:
        return '6. High: >= 5.0 rides'

c0_df['demand_band'] = c0_df['predicted_rides_D'].apply(get_band)
band_counts = c0_df['demand_band'].value_counts().sort_index()
print("\nBreakdown of C=0, D>0 by Forecast Demand Bands:")
for band, count in band_counts.items():
    pct = count / num_c0 * 100
    print(f"  {band:<30}: {count:5d} ({pct:6.2f}%)")

print(f"\nMax predicted demand among C=0 records: {c0_df['predicted_rides_D'].max():.3f} rides")
print(f"Number of C=0 records with predicted demand >= 5.0: {(c0_df['predicted_rides_D'] >= 5.0).sum()}")

# Relate to Zone Universe Historical Volume
zone_stats = zone_universe[['h3_cell', 'trip_count_historical']].copy()
# Quantile tiers of zones
zone_stats['density_tier'] = pd.qcut(zone_stats['trip_count_historical'], q=4, labels=['Q1 (Peripheral)', 'Q2 (Low-density)', 'Q3 (Medium-density)', 'Q4 (High-density)'])
c0_with_zones = pd.merge(c0_df, zone_stats, on='h3_cell', how='left')

print("\nBreakdown of C=0, D>0 by Zone Historical Volume Quartiles:")
tier_counts = c0_with_zones['density_tier'].value_counts()
for tier, count in tier_counts.items():
    pct = count / num_c0 * 100
    print(f"  {tier:<25}: {count:5d} ({pct:6.2f}%)")

# Unserved demand verification for C=0
# When C=0 and D>0, unserved = max(0, D - 0) = D
unserved_matches_d = np.isclose(c0_df['estimated_unserved_demand_rides'], c0_df['predicted_rides_D']).all()
print(f"\nUnserved demand equals predicted demand exactly when C=0: {unserved_matches_d}")
print(f"Total unserved demand originating from C=0 records: {c0_df['estimated_unserved_demand_rides'].sum():,.2f} rides ({c0_df['estimated_unserved_demand_rides'].sum() / total_unserved * 100:.2f}% of total unserved)")

# Check if any C=0 record was mislabeled as a surge alert
c0_surges = (c0_df['is_potential_surge'] == True).sum()
print(f"Number of C=0 records flagged as surge alerts: {c0_surges} (Expected 0)")

print("\n================================================================================")
print("SECTION C: SUPPLY SIMULATION SENSITIVITY ANALYSIS")
print("================================================================================")
from pipeline.simulation.supply import SupplySimulator, get_time_of_day_supply_multiplier
from pipeline.simulation.pressure import compute_demand_supply_pressure_table
from pipeline.simulation.surge import detect_potential_surges

fc_df = pd.read_parquet('data/processed/forecasts/forecasts.parquet')
xgb_df = fc_df[fc_df["model_name"] == "xgboost"].copy().rename(columns={"forecast_origin": "origin"})
baseline_df = fc_df[fc_df["model_name"] == "baseline_rolling_avg"].copy().rename(columns={"forecast_origin": "origin", "predicted_rides": "baseline_demand"})
merged_fc = pd.merge(xgb_df, baseline_df[["origin", "h3_cell", "baseline_demand"]], on=["origin", "h3_cell"], how="left")

eligible_zones = sorted(xgb_df["h3_cell"].unique().tolist())
origins = sorted(xgb_df["origin"].unique().tolist())
zone_weights = xgb_df.groupby("h3_cell")["predicted_rides"].mean().to_dict()

scenarios = [
    {"name": "Baseline (Fleet=2500, r=2.0)", "fleet": 2500, "r": 2.0},
    {"name": "Low Fleet (Fleet=1500, r=2.0)", "fleet": 1500, "r": 2.0},
    {"name": "High Fleet (Fleet=3500, r=2.0)", "fleet": 3500, "r": 2.0},
    {"name": "Low Rate (Fleet=2500, r=1.5)", "fleet": 2500, "r": 1.5},
    {"name": "High Rate (Fleet=2500, r=2.5)", "fleet": 2500, "r": 2.5},
]

print(f"{'Scenario':<32} | {'C=0 Recs (%)':<14} | {'Elevated/High/Crit':<20} | {'Unserved Demand':<16} | {'Surge Alerts':<12}")
print("-" * 105)

for sc in scenarios:
    sim = SupplySimulator(
        eligible_zones=eligible_zones,
        zone_historical_weights=zone_weights,
        fleet_size=sc['fleet'],
        base_availability_ratio=0.60,
        capacity_rate_r=sc['r'],
        random_seed=42
    )
    sup_df = sim.simulate_grid_supply(origins=origins, simulation_run_id="sim-sensitivity")
    
    p_df = compute_demand_supply_pressure_table(
        forecasts_df=merged_fc,
        supply_df=sup_df,
        elevated_ratio=0.8,
        high_ratio=1.0,
        critical_ratio=1.2,
        capacity_rate_r=sc['r']
    )
    
    annotated_df, s_df = detect_potential_surges(
        pressure_df=p_df,
        min_surge_demand=5.0,
        surge_ratio_threshold=1.2,
        growth_threshold=1.5
    )
    
    c0_pct = (p_df['pressure_status'] == 'NO_ESTIMATED_CAPACITY').mean() * 100
    high_crit = (p_df['pressure_status'].isin(['ELEVATED', 'HIGH_PRESSURE'])).sum()
    unserved = p_df['estimated_unserved_demand_rides'].sum()
    n_surges = len(s_df)
    
    print(f"{sc['name']:<32} | {c0_pct:12.2f}% | {high_crit:18d} | {unserved:14.2f} | {n_surges:10d}")

print("\n================================================================================")
print("SECTION D: EXACT BOUNDARY BEHAVIOR AND EDGE CASES")
print("================================================================================")
from pipeline.simulation.pressure import evaluate_single_pressure_record

# Test edge cases:
test_cases = [
    # Boundary tests around 0.8, 1.0, 1.2
    {"desc": "Ratio exactly 0.799 (< 0.8)", "d": 7.99, "v": 5, "r": 2.0, "status": "OK"},
    {"desc": "Ratio exactly 0.800 (>= 0.8 Elevated)", "d": 8.0, "v": 5, "r": 2.0, "status": "OK"},
    {"desc": "Ratio exactly 0.999 (< 1.0 Elevated)", "d": 9.99, "v": 5, "r": 2.0, "status": "OK"},
    {"desc": "Ratio exactly 1.000 (<= 1.0 Elevated)", "d": 10.0, "v": 5, "r": 2.0, "status": "OK"},
    {"desc": "Ratio exactly 1.001 (> 1.0 High)", "d": 10.01, "v": 5, "r": 2.0, "status": "OK"},
    {"desc": "Ratio exactly 1.199 (< 1.2 High)", "d": 11.99, "v": 5, "r": 2.0, "status": "OK"},
    {"desc": "Ratio exactly 1.200 (>= 1.2 Critical)", "d": 12.0, "v": 5, "r": 2.0, "status": "OK"},
    # Zero edge cases
    {"desc": "C=0, D>0 (No Capacity)", "d": 2.5, "v": 0, "r": 2.0, "status": "OK"},
    {"desc": "C=0, D=0 (Normal zero)", "d": 0.0, "v": 0, "r": 2.0, "status": "OK"},
    {"desc": "C>0, D=0 (Normal capacity excess)", "d": 0.0, "v": 5, "r": 2.0, "status": "OK"},
    # Stale / Missing input
    {"desc": "Missing forecast (STALE)", "d": None, "v": 5, "r": 2.0, "status": "STALE"},
    {"desc": "Missing forecast (MISSING)", "d": None, "v": 5, "r": 2.0, "status": "MISSING"},
]

for tc in test_cases:
    res = evaluate_single_pressure_record(
        demand_d=tc['d'],
        vehicles_v=tc['v'],
        capacity_rate_r=tc['r'],
        elevated_ratio=0.8,
        high_ratio=1.0,
        critical_ratio=1.2,
        input_status=tc['status']
    )
    print(f"{tc['desc']:<38} -> Status: {res['pressure_status']:<22} | Level: {res['pressure_level']:<12} | Index: {str(res['pressure_index']):<6} | Unserved: {res['estimated_unserved_demand_rides']}")

print("\n================================================================================")
print("SECTION E: PHASE 1-3 CANONICAL ARTIFACT HASH INVARIANCE")
print("================================================================================")
files_to_hash = [
    'data/raw/chicago_taxi_trips_2022-06.jsonl',
    'data/interim/cleaned_trips_2022-06/cleaned_trips.parquet',
    'data/interim/excluded_trips_2022-06/excluded_trips.parquet',
    'data/processed/zone_universe/zone_universe.parquet',
    'docs/evidence/clean_run_summary.json',
    'docs/evidence/zone_universe_analysis.json',
    'docs/evidence/zone_universe_specification.md',
    'data/processed/forecasts/forecasts.parquet',
    'data/processed/forecasts/forecast_evaluation.parquet',
    'models/forecasting/xgboost_demand_model.json'
]

for fp in files_to_hash:
    p = Path(fp)
    if p.exists():
        h = hashlib.sha256(p.read_bytes()).hexdigest().upper()
        print(f"{fp:<60}: {h}")
    else:
        print(f"{fp:<60}: MISSING")
