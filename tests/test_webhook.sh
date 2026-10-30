#!/usr/bin/env sh
# Sends three requests to verify the webhook's auth behaviour.
# Usage: WEBHOOK_SECRET=... ./tests/test_webhook.sh [url]
URL="${1:-http://localhost:5001/webhook}"
SECRET="${WEBHOOK_SECRET:?Set WEBHOOK_SECRET to the value in .env}"

echo "1) No header (expect 401):"
curl -s -w "  -> HTTP %{http_code}\n" -X POST "$URL" \
  -H "Content-Type: application/json" -d '{"heart_rate": 72}'

echo "2) Wrong token (expect 401):"
curl -s -w "  -> HTTP %{http_code}\n" -X POST "$URL" \
  -H "Content-Type: application/json" -H "X-API-Key: wrong" -d '{"heart_rate": 72}'

echo "3) Correct token (expect 200):"
curl -s -w "  -> HTTP %{http_code}\n" -X POST "$URL" \
  -H "Content-Type: application/json" -H "X-API-Key: $SECRET" \
  -d '{"heart_rate": 72, "steps": 8500}'
