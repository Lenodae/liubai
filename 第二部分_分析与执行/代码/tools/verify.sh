#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
rm -f .coverage evidence/coverage.json evidence/coverage.xml evidence/execution-mutations.json evidence/phase2-browser.json evidence/audit.json evidence/source-sha256.txt
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy tasks config execution
node --check static/app.js
node --check static/execution.js
bash -n start.sh tools/verify.sh ../打开留白.command '../配置 DeepSeek.command'
.venv/bin/python -m coverage run manage.py test tasks.tests execution.tests --noinput --shuffle=20261014 --verbosity 2 2>&1 | tee evidence/tests.log
.venv/bin/python -m coverage report | tee evidence/coverage.txt
.venv/bin/python -m coverage json -o evidence/coverage.json
.venv/bin/python -m coverage xml -o evidence/coverage.xml
.venv/bin/python tools/execution_mutations.py | tee evidence/execution-mutations.log
.venv/bin/python manage.py test tasks.tests execution.tests --noinput --shuffle=73 --verbosity 1 2>&1 | tee evidence/restored-tests.log
.venv/bin/python tools/browser_phase2.py | tee evidence/browser-run.log
.venv/bin/python tools/safety_check.py | tee evidence/safety.log
.venv/bin/python -m pip_audit --cache-dir .local/audit-cache --progress-spinner off -f json -o evidence/audit.json
.venv/bin/python tools/check_separation.py | tee evidence/separation.json
.venv/bin/python tools/source_state.py | tee evidence/source-sha256.txt
