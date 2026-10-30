from datetime import datetime, timezone
from typing import Any
import hmac
import json
import os
import uuid

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
import pyarrow as pa
import pyarrow.parquet as pq

app = FastAPI(
    title="Health webhook",
    description="Receives health data (e.g. from Health Auto Export) and stores it as Parquet.",
)

# Load the secret token from the environment so it never lives in source control
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET environment variable is not set")

# Each request is written to its own Parquet file under DATA_DIR/received_date=YYYY-MM-DD/
DATA_DIR = os.environ.get("DATA_DIR", "data")
# Payloads that can't become Parquet are kept as JSON here; Parquet readers skip "_" folders
RAW_DIR = os.path.join(DATA_DIR, "_raw")


def drop_empty_objects(value):
    # Parquet can't store a struct with no fields, e.g. Health Auto Export's "metadata": {}
    if isinstance(value, dict):
        return {k: drop_empty_objects(v) for k, v in value.items()} or None
    if isinstance(value, list):
        return [drop_empty_objects(v) for v in value]
    return value


def write_atomically(directory, filename, write):
    # Write to a hidden temp file then rename, so readers never see a partial file
    os.makedirs(directory, exist_ok=True)
    tmp_path = os.path.join(directory, f".{filename}.tmp")
    path = os.path.join(directory, filename)
    write(tmp_path)
    os.replace(tmp_path, path)
    return path


def new_filename(received_at, extension):
    return f"{received_at:%H%M%S%f}-{uuid.uuid4().hex}.{extension}"


def save_to_parquet(data, received_at):
    # Accept a single JSON object or a list of objects; each object becomes a row
    records = data if isinstance(data, list) else [data]
    if not all(isinstance(r, dict) for r in records):
        raise ValueError("Payload must be a JSON object or a list of objects")

    # Infer the schema from every record, so fields missing from the first one are kept
    table = pa.Table.from_struct_array(pa.array([drop_empty_objects(r) for r in records]))
    table = table.append_column(
        "received_at", pa.array([received_at] * len(records), pa.timestamp("us", tz="UTC"))
    )

    partition_dir = os.path.join(DATA_DIR, f"received_date={received_at:%Y-%m-%d}")
    return write_atomically(partition_dir, new_filename(received_at, "parquet"),
                            lambda p: pq.write_table(table, p))


def save_raw_json(data, received_at):
    def write(p):
        with open(p, "w") as f:
            json.dump(data, f)

    partition_dir = os.path.join(RAW_DIR, f"received_date={received_at:%Y-%m-%d}")
    return write_atomically(partition_dir, new_filename(received_at, "json"), write)


# Keep the {"status", "message"} error shape the phone apps already see, instead of
# FastAPI's default {"detail": ...}
@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"status": "error", "message": exc.detail}, status_code=exc.status_code)


def is_authorized(client_token: str | None) -> bool:
    # compare_digest avoids leaking the secret through response timing
    return bool(client_token) and hmac.compare_digest(client_token, WEBHOOK_SECRET)


UNAUTHORIZED = "Unauthorized: Invalid or missing token"


# A body that isn't JSON would get FastAPI's 422; answer 400 like the Flask version did.
# FastAPI parses the body before running dependencies, so check the key here too:
# otherwise callers without a key could learn whether their JSON was valid.
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if not is_authorized(request.headers.get("X-API-Key")):
        return JSONResponse({"status": "error", "message": UNAUTHORIZED}, status_code=401)
    return JSONResponse({"status": "error", "message": "No data provided"}, status_code=400)


# Declaring the header as a security scheme adds an "Authorize" button to /docs.
# auto_error=False so a missing key reaches require_api_key and gets our 401, not a 403.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(client_token: str | None = Depends(api_key_header)):
    if not is_authorized(client_token):
        raise HTTPException(status_code=401, detail=UNAUTHORIZED)


# A plain `def` (not `async def`): writing Parquet blocks, so FastAPI runs it in a thread pool
@app.post("/webhook", dependencies=[Depends(require_api_key)])
def receive_webhook(data: dict[str, Any] | list[Any] = Body(...)):
    if not data:
        raise HTTPException(status_code=400, detail="No data provided")

    print("--- Secure Health Data Received ---", flush=True)
    print(data, flush=True)

    # Persist the payload as Parquet
    received_at = datetime.now(timezone.utc)
    try:
        path = save_to_parquet(data, received_at)
    except pa.ArrowException as e:
        # Valid data in a shape Parquet can't hold: keep it as JSON rather than lose it.
        # Caught before ValueError because Arrow's conversion errors also subclass it.
        path = save_raw_json(data, received_at)
        print(f"Could not convert to Parquet ({e}); kept raw JSON instead", flush=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Could not store data: {e}")

    print(f"Saved to {path}", flush=True)

    return {"status": "success", "message": "Data received securely!"}


@app.get("/health")
def health():
    return {"status": "ok"}


# Opening the bare address in a browser lands on the interactive docs instead of a 404
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=os.environ.get("RELOAD") == "1")
