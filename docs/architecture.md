# Architecture

## Data flow

```
Health Auto Export (iPhone)
        │  POST /webhook, X-API-Key header, JSON body
        ▼
webhook service (FastAPI + uvicorn, src/server.py)
        │
        ├─► Parquet: $DATA_DIR/received_date=YYYY-MM-DD/<time>-<uuid>.parquet
        └─► raw JSON fallback: $DATA_DIR/_raw/received_date=YYYY-MM-DD/*.json
                                    (health_data volume in Docker)

db service (PostgreSQL 18, db/schema.sql)        ← not yet fed by the webhook
```

## Components

| Component | Where | Role |
|---|---|---|
| Webhook | `src/server.py` | Checks the API key, writes each payload atomically as one Parquet file |
| Inspector | `src/inspect_data.py` | Prints columns, types, missing counts and sample rows of the Parquet dataset |
| Export explorer | `src/explore_health_export.py` | Reads a full Apple Health `export.zip` and saves recent data as Parquet |
| Database | `db/schema.sql` | Cleaned, de-duplicated tables and daily views |

## Database objects

- `metric_definition`, `metric_sample` — one generic table for all metrics (metric × time slot)
- `sleep_night` — one row per night, filed under the wake-up morning
- `workout`, `workout_sample` — workouts and their per-minute series
- Views: `daily_metric`, `daily_summary`, `workout_overview`, all grouped with `local_day()`

## Deployment

`docker-compose.yml` runs both services on this Mac. Ports are bound to `127.0.0.1` only
(webhook `5001`, Postgres `5432`). Secrets come from `.env`.
