# AGENTS.md  (workspace rules for Antigravity)

Project: RideIntel. Chicago historical trips -> Kafka -> Spark -> H3 -> forecast -> API -> React.
Read PLAN.md and the relevant file in contracts/ before editing anything.

## Process, every task
1. Inspect the repo first. Summarise what exists. Do not edit yet.
2. Work on ONE module and its contract only.
3. Write unit tests. Run them. Paste the real terminal output.
4. Stop and let the human review the diff. Do not start the next module.

## Hard rules
- Do not change anything in contracts/ without asking. If a field is missing, STOP and ask.
- Never claim "verified", "passing" or "done" unless a command ran and you pasted its output.
- Never invent metrics, counts or sample results presented as measured. Fixtures must be labelled `fixture`.
- Label every value: HISTORICAL, REPLAYED, SIMULATED, OBSERVED, PREDICTED or ESTIMATED.
- Time: store UTC only. Convert to America/Chicago in the frontend only.
- Forecasting: chronological splits only. Features at origin T use only data before T. Add a no-lookahead test.
- Evaluation: XGBoost and both baselines use the identical (origin, zone) test rows. WAPE with sum(actual)=0 is null with status UNDEFINED_ZERO_ACTUAL.
- Pressure: C = V x r. Status and numeric index are separate fields. Never serialize infinity. Follow the rule order in contracts/parquet_schemas.md.
- Missing data is not zero. Zero-fill only against zone_universe and only for complete windows.
- Streaming: event time only. Dedup horizon equals the watermark. Duplicates beyond it may be counted again, and that behaviour must be tested, not hidden.
- Each experiment uses a fresh Kafka topic, a fresh checkpoint directory and a new processing_run_id.
- Do not claim exactly-once across Kafka, Spark, Parquet and Supabase.
- Secrets: no keys in the repo or in frontend code. Service-role keys are backend-only.
- Scope: no Redis, LSTM, booking, dispatch, payments or Chennai work.
- Frontend types are generated from contracts/openapi.yaml. Never hand-write them.
- Environment: WSL2, Python 3.12 (not 3.13), Java 17 or 21.
