#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
rm -f .coverage evidence/coverage.json evidence/coverage.xml evidence/mutations.json evidence/browser.json evidence/audit.json evidence/source-sha256.txt
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy tasks config
node --check static/app.js
bash -n start.sh tools/verify.sh
.venv/bin/coverage run manage.py test tasks.tests --noinput --shuffle=20261013 --verbosity 2 2>&1 | tee evidence/tests.log
.venv/bin/coverage report | tee evidence/coverage.txt
.venv/bin/coverage json -o evidence/coverage.json
.venv/bin/coverage xml -o evidence/coverage.xml
.venv/bin/python tools/mutations.py | tee evidence/mutations.log
.venv/bin/python manage.py test tasks.tests --noinput --shuffle=73 2>&1 | tee evidence/restored-tests.log
.venv/bin/python tools/browser_check.py | tee evidence/browser-run.log
.venv/bin/python tools/safety_check.py | tee evidence/safety.log
.venv/bin/pip-audit --cache-dir .local/audit-cache --progress-spinner off -f json -o evidence/audit.json
.venv/bin/python tools/source_state.py | tee evidence/source-sha256.txt
