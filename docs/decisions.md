# Decisions

One entry per decision: what was chosen, and why. Newest at the bottom.

## 2026-10-24 — Shared secret in `X-API-Key`
Health Auto Export can send a custom header, so a shared secret is the simplest auth. It is
compared with `hmac.compare_digest` to avoid timing leaks, and read from the environment so it
never lives in source control.

## 2026-10-24 — One Parquet file per delivery, partitioned by day
Each request is written to its own file (temp file, then rename), so concurrent requests never
clash and readers never see a partial file. `received_date=` folders let pandas/pyarrow read the
whole folder as one dataset.

## 2026-10-24 — Never drop a delivery
Valid JSON that Parquet can't hold (for example mixed types in a field) is kept as raw JSON in
`_raw/`. Parquet readers skip `_` folders.

## 2026-10-27 — FastAPI instead of Flask
Gives the interactive `/docs` page with an Authorize button. The webhook handler stays a plain
`def` because writing Parquet blocks. The `{"status", "message"}` error shape and the 400 for a
bad body were kept so the phone app sees the same responses.

## 2026-10-27 — PostgreSQL 18 alongside Parquet
Parquet stays the raw archive; Postgres holds cleaned, de-duplicated data for querying. Metrics
use one generic table so a new metric needs no schema change. Times are `timestamptz`, and days
are computed in `Europe/Zurich` so clock changes are handled.

## 2026-10-30 — `src/`, `tests/`, `docs/` layout
Code moved into `src/` and the smoke test into `tests/`. The Dockerfile still copies the scripts
flat into `/app`, so container commands did not change.
