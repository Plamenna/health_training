# health_training

A small Flask webhook server that accepts health data over `POST /webhook`, but only
from callers who send the shared secret in the `X-API-Key` header. Requests without
the header, or with the wrong value, get `401 Unauthorized`.

## Run with Docker

```sh
echo "WEBHOOK_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" > .env
docker compose up --build
```

The server listens on <http://localhost:5000>.

Without Compose:

```sh
docker build -t health-webhook .
docker run --rm -p 5000:5000 -e WEBHOOK_SECRET=<your-secret> health-webhook
```

## Verify

With the server running:

```sh
WEBHOOK_SECRET=<your-secret> ./test_webhook.sh
```

Expected:

| Request | Response |
|---|---|
| No `X-API-Key` header | `401` `{"status": "error", "message": "Unauthorized: Invalid or missing token"}` |
| Wrong `X-API-Key` | `401` |
| Correct `X-API-Key`, JSON body | `200` `{"status": "success", "message": "Data received securely!"}` |
| Correct `X-API-Key`, no/empty JSON body | `400` |

Received payloads are printed to the container logs (`docker compose logs -f`).

## Stored data

Each accepted payload is saved as its own Parquet file under
`$DATA_DIR/received_date=YYYY-MM-DD/` (`DATA_DIR` defaults to `data/`, and to `/app/data` in Docker,
where Compose stores it in the `health_data` volume). The body can be one JSON object
(one row) or a list of objects (one row each), and a `received_at` UTC timestamp column is
added. Payloads that can't be turned into a table, such as `[1, 2]` or a field that is a
number in one record and a string in another, get `400`.

Read everything back as one dataset:

```python
import pandas as pd
df = pd.read_parquet("data")   # the received_date=... folders become a `received_date` column
```

To copy the files out of the Docker volume: `docker compose cp webhook:/app/data ./data`.

To see which variables have arrived, their types, how often each is missing, and sample rows:

```sh
docker compose exec webhook python inspect_data.py   # in Docker
python inspect_data.py data                          # locally
```

## Endpoints

- `POST /webhook` — authenticated by `X-API-Key`, expects a JSON body.
- `GET /health` — unauthenticated liveness check.

## Run without Docker

```sh
pip install -r requirements.txt
WEBHOOK_SECRET=<your-secret> python server.py
```

## Notes

- The secret comes from the `WEBHOOK_SECRET` environment variable; the server refuses to
  start without it. `.env` is git-ignored so real secrets aren't committed.
- The token is compared with `hmac.compare_digest` to avoid timing leaks.
- In Docker the app runs under gunicorn as a non-root user, not Flask's debug server.
- Use HTTPS in front of this (a reverse proxy or tunnel) when exposing it publicly,
  otherwise the API key travels in plain text.
