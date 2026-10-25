-- STATUS: DRAFT v0.1. Supabase is OPTIONAL for the first working demo.
-- Prove Kafka -> Spark -> Parquet -> forecast first; add this in Phase 5.
-- Parquet is the analytical source of truth. The DB holds only application records.
-- Service-role keys stay in the backend environment. Never in frontend code.

create table if not exists simulated_ride_requests (
  ride_id        uuid primary key default gen_random_uuid(),
  pickup_name    text,
  pickup_lat     double precision not null,
  pickup_lon     double precision not null,
  pickup_h3      text not null,
  dropoff_name   text,
  dropoff_lat    double precision not null,
  dropoff_lon    double precision not null,
  dropoff_h3     text not null,
  status         text not null default 'PENDING'
                 check (status in ('PENDING','ACCEPTED','IN_PROGRESS','COMPLETED','CANCELLED')),
  source_type    text not null default 'SIMULATED' check (source_type = 'SIMULATED'),
  simulation_run_id text,
  simulation_time timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- DEFERRED: add only if guaranteed publishing of requests to Kafka is genuinely needed.
-- create table if not exists ride_event_outbox (
--   event_id uuid primary key default gen_random_uuid(),
--   ride_id uuid not null references simulated_ride_requests(ride_id),
--   event_type text not null,
--   payload jsonb not null,
--   created_at timestamptz not null default now(),
--   published_at timestamptz,
--   attempts int not null default 0
-- );
-- Request row and outbox row must be inserted in ONE transaction.
