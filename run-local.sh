#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
(cd frontend && npm ci && npm run build)
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
