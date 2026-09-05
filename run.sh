#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo " Starting Aarogya-Vāyu Civic Health Resilience Platform "
echo "=========================================================="
echo "📍 Serving on: http://127.0.0.1:8000"
echo "=========================================================="

"$DIR/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000
