from datetime import datetime, timezone
from flask import Flask, request, jsonify
import hmac
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


def save_to_parquet(data):
    # Accept a single JSON object or a list of objects; each object becomes a row
    records = data if isinstance(data, list) else [data]
    if not all(isinstance(r, dict) for r in records):
        raise ValueError("Payload must be a JSON object or a list of objects")

    received_at = datetime.now(timezone.utc)
    # Infer the schema from every record, so fields missing from the first one are kept
    table = pa.Table.from_struct_array(pa.array(records))
    table = table.append_column(
        "received_at", pa.array([received_at] * len(records), pa.timestamp("us", tz="UTC"))
    )

    partition_dir = os.path.join(DATA_DIR, f"received_date={received_at:%Y-%m-%d}")
    os.makedirs(partition_dir, exist_ok=True)
    filename = f"{received_at:%H%M%S%f}-{uuid.uuid4().hex}.parquet"

    # Write to a hidden temp file then rename, so readers never see a partial file
    tmp_path = os.path.join(partition_dir, f".{filename}.tmp")
    path = os.path.join(partition_dir, filename)
    pq.write_table(table, tmp_path)
    os.replace(tmp_path, path)
    return path


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
    try:
        path = save_to_parquet(data)
    except (ValueError, pa.ArrowException) as e:
        return jsonify({"status": "error", "message": f"Could not store data: {e}"}), 400

    print(f"Saved to {path}", flush=True)

    return jsonify({"status": "success", "message": "Data received securely!"}), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
