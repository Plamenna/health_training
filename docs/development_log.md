# Development log

Newest at the top. Add a short entry at the end of each work session.

## 2026-10-30
- Reorganised the repo into `src/`, `tests/`, `docs/` and added `CLAUDE.md`.
- Dockerfile now copies from `src/`; README commands updated to the new paths.

## 2026-10-27
- Added the PostgreSQL 18 `db` service and `db/schema.sql`.
- Replaced Flask with FastAPI.

## 2026-10-24
- Accepted Health Auto Export workouts; payloads Parquet can't hold are kept as raw JSON.
- Stopped tracking `.env.example`; README explains how to generate `.env`.
- Added the authenticated webhook server with Parquet storage.

## 2026-10-21
- Initial commit.
