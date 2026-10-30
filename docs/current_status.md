# Current status

_Last updated: 2026-10-30_

## Working
- Authenticated webhook (`POST /webhook`) storing every delivery as Parquet, with raw JSON fallback
- Health Auto Export metrics and workouts accepted
- Docker Compose setup with the webhook and PostgreSQL 18
- `db/schema.sql` creates the tables and daily views on a fresh volume

## In progress / not done yet
- The webhook does not write to Postgres yet; nothing loads Parquet data into the tables
- No automated tests: `tests/test_webhook.sh` is a manual curl check against a running server
- No HTTPS in front of the server, so it should not be exposed publicly yet

## Next steps
- Load deliveries into Postgres (from the webhook, or a job that reads the Parquet files)
- Add pytest tests for `src/server.py` using FastAPI's `TestClient`
