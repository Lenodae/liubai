#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy tasks config execution
node --check static/app.js
node --check static/execution.js
node --check static/deepseek_settings.js
.venv/bin/python tools/settings_mutations.py | tee evidence/settings-mutations.log
.venv/bin/python -m coverage run manage.py test tasks.tests execution.tests --shuffle=20261014 --noinput 2>&1 | tee evidence/settings-tests.log
.venv/bin/python -m coverage report --include='execution/settings_service.py,execution/views.py' | tee evidence/settings-coverage.txt
.venv/bin/python manage.py test execution.tests.test_settings execution.tests.test_settings_properties --shuffle=73 --noinput
.venv/bin/python tools/browser_settings.py | tee evidence/settings-browser.log
.venv/bin/python tools/browser_phase2.py | tee evidence/settings-existing-browser.log
.venv/bin/python tools/safety_check.py | tee evidence/settings-safety.log
.venv/bin/python tools/check_separation.py | tee evidence/settings-separation.json
.venv/bin/python tools/source_state.py | tee evidence/settings-source-sha256.txt
