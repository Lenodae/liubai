#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
# Preserve RED logs and the pre-change source snapshot; regenerate current results.
rm -f evidence/task-trash-tests.log evidence/task-trash-coverage.json \
  evidence/task-trash-changed-coverage.json evidence/task-trash-runtime.json \
  evidence/task-trash-browser.json evidence/task-trash-edge-browser.json \
  evidence/task-trash-mutations-all.json evidence/task-trash-separation.json \
  evidence/task-trash-source-sha256.txt evidence/task-trash-types.log evidence/task-trash-lint.log
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/ruff check . | tee evidence/task-trash-lint.log
.venv/bin/ruff format --check . | tee -a evidence/task-trash-lint.log
.venv/bin/mypy tasks config execution load_analysis --exclude 'tests|migrations' | tee evidence/task-trash-types.log
for source in static/*.js; do node --check "$source"; done
bash -n tools/verify_task_trash.sh tools/verify_phase3.sh start.sh
.venv/bin/coverage run manage.py test tasks.tests execution.tests load_analysis.tests --noinput --shuffle=20261014 2>&1 | tee evidence/task-trash-tests.log
.venv/bin/coverage report | tee evidence/task-trash-coverage.txt
.venv/bin/coverage json -o evidence/task-trash-coverage.json
.venv/bin/python tools/task_trash_coverage.py | tee evidence/task-trash-changed-coverage.log
.venv/bin/python tools/task_trash_runtime.py | tee evidence/task-trash-runtime.log
.venv/bin/python tools/phase3_runtime_check.py --http | tee evidence/task-trash-inherited-runtime.log
.venv/bin/python tools/task_trash_mutations.py | tee evidence/task-trash-mutations.log
.venv/bin/python tools/browser_task_trash.py | tee evidence/task-trash-browser.log
.venv/bin/python tools/browser_task_trash.py --edge-only | tee evidence/task-trash-edge-browser.log
.venv/bin/python tools/browser_phase2.py | tee evidence/task-trash-execution-browser.log
.venv/bin/python tools/browser_phase3.py | tee evidence/task-trash-load-browser.log
.venv/bin/python tools/browser_active_budget.py | tee evidence/task-trash-active-browser.log
.venv/bin/python tools/browser_warm_feedback.py | tee evidence/task-trash-encouragement-browser.log
.venv/bin/python tools/browser_warm_feedback.py --editor-only | tee evidence/task-trash-editor-browser.log
.venv/bin/python tools/safety_check.py | tee evidence/task-trash-safety.log
.venv/bin/python tools/check_separation.py | tee evidence/task-trash-separation.json
.venv/bin/python tools/source_state.py | tee evidence/task-trash-source-sha256.txt
