# CLAUDE.md

FastAPI webhook that receives Apple Health data from the Health Auto Export app, stores each
delivery as Parquet, and (in progress) loads it into PostgreSQL.

## Layout

- `src/server.py` — the webhook (`POST /webhook`, `GET /health`, `/docs`)
- `src/inspect_data.py` — summary of the stored Parquet data
- `src/explore_health_export.py` — one-off explorer for a full Apple Health export zip
- `tests/test_webhook.sh` — curl checks of the auth behaviour against a running server
- `db/schema.sql` — Postgres tables and views, mounted into the `db` container on first start
- `docs/` — read `current_status.md` first; record design choices in `decisions.md` and
  what was done each session in `development_log.md`

## Commands

```sh
docker compose up --build                                  # webhook on :5001, Postgres on :5432
WEBHOOK_SECRET=<secret> ./tests/test_webhook.sh            # smoke test
WEBHOOK_SECRET=<secret> python src/server.py               # run locally without Docker
python src/inspect_data.py data                            # inspect local Parquet data
```

## Conventions

- Secrets only come from `.env` (git-ignored). Never commit or print real values.
- In the image, `src/` files are copied flat into `/app`, so container commands use
  `python inspect_data.py`, not `src/...`. Keep the Dockerfile `COPY` line in sync when
  adding modules.
- Never drop a delivery: data Parquet can't hold is saved as raw JSON under `_raw/`.
- Times are stored as UTC / `timestamptz`; days are computed in `Europe/Zurich`.
- `db/schema.sql` must stay safe to re-run (`IF NOT EXISTS`, `CREATE OR REPLACE`, upserts).
