#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy tasks config execution
.venv/bin/python -m coverage run manage.py test tasks.tests execution.tests --noinput --shuffle=20261014 2>&1 | tee evidence/tls-tests.log
.venv/bin/python -m coverage report --include='execution/provider.py' | tee evidence/tls-coverage.txt
.venv/bin/python tools/tls_mutations.py | tee evidence/tls-mutations.log
.venv/bin/python manage.py test execution.tests.test_provider --shuffle=73 --noinput
.venv/bin/python tools/safety_check.py | tee evidence/tls-safety.log
.venv/bin/python -m pip_audit --cache-dir .local/audit-cache --progress-spinner off -f json -o evidence/tls-audit.json
.venv/bin/python tools/check_separation.py
.venv/bin/python tools/source_state.py | tee evidence/tls-source-sha256.txt
# Live probe is read-only, optional, and separate from deterministic regression tests:
if [[ "${1:-}" == "--live" ]]; then
  .venv/bin/python tools/check_deepseek_connection.py | tee evidence/tls-connection.log
fi
