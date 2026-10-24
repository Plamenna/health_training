from datetime import datetime, timezone
from flask import Flask, request, jsonify
import hmac
import json
import os
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

app = Flask(__name__)

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


@app.route('/webhook', methods=['POST'])
def receive_webhook():
    # 1. Check for the secret token in the request headers
    client_token = request.headers.get('X-API-Key', '')

    # compare_digest avoids leaking the secret through response timing
    if not client_token or not hmac.compare_digest(client_token, WEBHOOK_SECRET):
        # Reject unauthorized requests immediately
        return jsonify({"status": "error", "message": "Unauthorized: Invalid or missing token"}), 401

    # 2. Extract and process the data if authorized
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400

    print("--- Secure Health Data Received ---", flush=True)
    print(data, flush=True)

    # 3. Persist the payload as Parquet
    received_at = datetime.now(timezone.utc)
    try:
        path = save_to_parquet(data, received_at)
    except pa.ArrowException as e:
        # Valid data in a shape Parquet can't hold: keep it as JSON rather than lose it.
        # Caught before ValueError because Arrow's conversion errors also subclass it.
        path = save_raw_json(data, received_at)
        print(f"Could not convert to Parquet ({e}); kept raw JSON instead", flush=True)
    except ValueError as e:
        return jsonify({"status": "error", "message": f"Could not store data: {e}"}), 400

    print(f"Saved to {path}", flush=True)

    return jsonify({"status": "success", "message": "Data received securely!"}), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
