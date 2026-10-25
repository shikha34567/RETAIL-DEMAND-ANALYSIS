# RideIntel: Build Plan (solo, with AI models in Antigravity)

Tick a box ONLY when you have seen the evidence (test output, report file, screenshot). Save evidence in docs/evidence/.

## Scope
Chicago historical trips are replayed through Kafka, processed by Spark into 15-minute H3 demand windows, used to forecast the next 30 minutes, compared with SIMULATED vehicle capacity, and shown in a React dashboard.
Out of scope: Redis, LSTM, real booking or dispatch, payments, Chennai.

## Folder structure
```
rideintel/
  README.md  AGENTS.md  PLAN.md  Makefile  docker-compose.yml  .env.example
  config/        settings.yaml, city_chicago.yaml
  contracts/     event_schema.json, parquet_schemas.md, db_schema.sql, openapi.yaml
  data/          raw/ interim/ processed/ forecasts/ artifacts/   (gitignored)
  pipeline/      ingest/ producer/ spark/ spatial/ validation/
  simulation/    clock.py, vehicles.py, surge_injector.py
  ml/            split.py features.py baselines.py train_xgb.py evaluate.py
                 forecast_job.py supply.py surge_detector.py
  backend/app/   main.py routers/ schemas/ services/
  frontend/src/  api/(generated) pages/ components/ lib/
  tests/         unit/ integration/ contract/ e2e/
  docs/          dataset_card.md architecture.md limitations.md evidence/
  reports/       measured metrics only
```
Makefile: add a target only when its module exists and its tests pass. Start with `setup` and `test`.

## Rules that define "correct" (decided before coding)

### Streaming and deduplication
- Windows use `event_ts` only. Three timestamps exist: `event_ts` (historical), `emitted_at` (producer), `processed_at` (Spark).
- `event_id` = sha1(dataset_id : trip_id). Stable across retries and restarts.
- 15-minute windows, watermark 10 minutes, append mode (finalized windows only).
- **Dedup is not global.** Spark's dedup state is bounded by the watermark. A duplicate arriving after its state expires can be counted again. Dedup horizon = watermark = 10 minutes.
  - To let Spark expire state, include `event_ts` in the dedup keys (`["event_id","event_ts"]`), or use `dropDuplicatesWithinWatermark` (Spark 3.5+). `dropDuplicates(["event_id"])` on its own keeps state indefinitely.
- Test duplicates **within** the horizon (must not inflate counts) and **beyond** it (document what happens).
- Every experiment: fresh topic, fresh checkpoint directory, new `processing_run_id`.
- Late events past the watermark are dropped by streaming and kept by batch. Explain each batch vs stream difference.

### Estimated pressure index
- D = predicted pickups next 30 min. V = AVAILABLE simulated vehicles in the zone. r = assumed pickups per vehicle per 30 min (configurable).
- C = V x r, P = D / C. Rules in this order:
  1. inputs missing or stale -> `UNKNOWN`
  2. D > 0 and C = 0 -> `NO_ESTIMATED_CAPACITY`
  3. D = 0 and C = 0 -> `NORMAL` (index 0)
  4. C > 0 -> thresholds from config: `HIGH_PRESSURE`, `ELEVATED`, `NORMAL`
- The numeric index and the status are separate fields. The index is null (never infinity) when C = 0 or inputs are unknown.
- It is a scenario-based decision-support measure, not real-world utilization.

### Forecast evaluation
- Same chronological test interval for XGBoost, `baseline_rolling_avg` and `baseline_same_time_last_week`, scored on the identical (origin, zone) rows. Record how many rows were excluded and why.
- Record per row: forecast origin, target interval, model name and version, actual target count.
- Metrics: MAE, RMSE, WAPE. If sum(actual) = 0, WAPE is `null` with status `UNDEFINED_ZERO_ACTUAL`.
- Never put a metric in a report that was not measured on the held-out test set.

### API and database
- First API is four endpoints: `/api/dashboard`, `/api/zones`, `/api/models/metrics`, `/api/admin/health`.
- Add passenger requests, driver features and simulation controls only when their backend service works.
- Supabase is optional until Phase 5. Prove Kafka -> Spark -> Parquet -> forecast first. The outbox is added only if guaranteed Kafka publishing of requests is genuinely needed.
- Sources of truth: openapi.yaml -> contract test against `app.openapi()` -> generated frontend types. event_schema.json -> producer validation and a Spark schema test. parquet_schemas.md -> Arrow schema tests.

## Phases (each ends in a demo; commit after each verified module)

### Phase 1: Data and contracts
- [ ] WSL2, Python 3.12, Java, Docker, Node working
- [ ] Chicago dataset downloaded; `docs/dataset_card.md` records dataset type, source URL, download date, date range, row count, pickup geography (coordinates vs area/tract)
- [ ] Contracts reviewed against the real schema, then **frozen** (tag in Git); `AGENTS.md` in place
- [ ] `ingest/` inspect + clean, exclusion log with counts before and after
- [ ] `spatial/` H3 helper; resolution comparison on the real data; resolution chosen and recorded
- [ ] `zone_universe` defined with its rule
- Demo: cleaned Parquet and a per-zone demand chart

### Phase 2: Aggregation and Kafka -> Spark
- [ ] Spark batch job; counts match an independent pandas recompute
- [ ] Producer: schema validation, broker acks, dry-run, simulation-clock replay
- [ ] Streaming job on a file source (stand-in only, labelled as such)
- [ ] Streaming job on **real Kafka** (fresh topic and checkpoint)
- [ ] Duplicate test within the dedup horizon: counts unchanged
- [ ] Duplicate test beyond the horizon: behaviour documented
- [ ] Late-event test; `batch_vs_stream` with every difference explained
- Demo: real Kafka -> Spark windows matching batch

### Phase 3: Forecasting
- [ ] `split.py` chronological (record boundaries)
- [ ] `features.py` with a no-lookahead unit test
- [ ] Both baselines implemented
- [ ] XGBoost trained
- [ ] `evaluate.py`: identical test rows for all three models; MAE, RMSE, WAPE (null case handled); by zone group and hour
- [ ] `forecast_job.py`: append-only forecasts with origin and target interval
- Demo: measured metrics table. If a baseline wins, report it honestly.
- Milestone: Kafka -> Spark -> Parquet -> forecast proven end to end (no Supabase needed)

### Phase 4: Simulation, supply and surge
- [ ] `clock.py`: speed, pause, resume, reset
- [ ] `vehicles.py`: seeded, AVAILABLE/BUSY/OFFLINE, inside Chicago bounds
- [ ] `supply.py`: all four pressure rules tested, including C = 0 and stale input
- [ ] `surge_detector.py` thresholds calibrated by replay experiments
- [ ] `surge_injector.py`; injected surge raises an alert, pressure changes, earlier forecast preserved
- [ ] Duplicate delivery does not multiply the surge count (within horizon)
- Demo: surge experiment output saved with timestamps

### Phase 5: API, frontend, persistence, verification
- [ ] Backend: the four endpoints only; real health checks; contract test passes
- [ ] Frontend types generated from openapi.yaml
- [ ] React: Dashboard -> Model Performance -> Admin Health, every value source-labelled
- [ ] Add endpoints and pages one at a time as services work: Passenger Map + request form, Driver Portal, simulation controls
- [ ] Supabase for simulated requests (service-role key backend-only); outbox only if justified
- [ ] e2e tests: replay, pause, reset, surge
- [ ] Performance measurements recorded; `docs/limitations.md` written
- [ ] Review 0 slides updated (remove Cassandra/Redis, HDFS, LSTM)

## Definition of Done (evidence required for each)
- [ ] Exact dataset documented, with its limitations
- [ ] Cleaning and coordinate validation reproducible
- [ ] Producer publishes valid events to the topic
- [ ] Spark reads real Kafka and produces demand windows
- [ ] H3 and 15-minute windows validated
- [ ] Batch vs streaming compared, differences explained
- [ ] Next-30-minute forecasts produced and stored
- [ ] Chronological evaluation with both baselines on identical rows
- [ ] Metrics come from held-out test data
- [ ] Supply and capacity labelled SIMULATED / ESTIMATED
- [ ] Zero-capacity case tested
- [ ] Surge detection passes a repeatable test
- [ ] Dashboard separates observed, historical, simulated, estimated, predicted
- [ ] No credentials in frontend or repo
- [ ] Setup instructions and end-to-end tests exist
- [ ] Limitations documented

## Antigravity workflow (every task)
1. Ask it to inspect the repo and summarise, with no edits.
2. Give it one module and its contract.
3. Require unit tests and the real terminal output.
4. Read the diff and run the tests yourself.
5. Commit the verified result, then move on.
