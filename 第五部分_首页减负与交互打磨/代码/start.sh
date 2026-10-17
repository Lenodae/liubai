#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --disable-pip-version-check pip==26.2.1
  .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py analysis_worker >>.local/worker.log 2>&1 &
worker_pid=$!
.venv/bin/python manage.py runserver 127.0.0.1:8004 --noreload --insecure &
web_pid=$!
cleanup() {
  kill "$worker_pid" "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
wait "$web_pid"
