#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy tasks config execution
node --check static/execution.js
.venv/bin/python tools/completion_edit_mutations.py | tee evidence/completion-edit-mutations.log
.venv/bin/python -m coverage run manage.py test tasks.tests execution.tests --shuffle=20261014 --noinput 2>&1 | tee evidence/completion-edit-tests.log
.venv/bin/python -m coverage report | tee evidence/completion-edit-coverage.txt
.venv/bin/python manage.py test execution.tests.test_completion_edit --shuffle=73 --noinput
.venv/bin/python tools/browser_phase2.py | tee evidence/completion-edit-browser.log
.venv/bin/python tools/safety_check.py | tee evidence/completion-edit-safety.log
.venv/bin/python tools/check_separation.py | tee evidence/completion-edit-separation.json
.venv/bin/python tools/source_state.py | tee evidence/completion-edit-source-sha256.txt
