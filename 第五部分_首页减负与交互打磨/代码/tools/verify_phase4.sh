#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
verification_state=$(mktemp -d "${TMPDIR:-/tmp}/liubai-phase4-verify.XXXXXX")
trap 'rm -rf "$verification_state"' EXIT
export TASKFLOW_STATE_DIR="$verification_state"
export TASKFLOW_DB="$verification_state/tasks.sqlite3"
export DEEPSEEK_API_KEY=""
if [ "${1:-}" != "--finish" ]; then
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/ruff check . | tee evidence/phase4-lint.log
.venv/bin/ruff format --check . | tee -a evidence/phase4-lint.log
.venv/bin/mypy tasks config execution load_analysis daily_footprints --exclude 'tests|migrations' | tee evidence/phase4-types.log
for script in static/*.js; do node --check "$script"; done
bash -n start.sh tools/verify_phase4.sh ../打开留白.command '../配置 DeepSeek.command'
.venv/bin/coverage run manage.py test tasks.tests execution.tests load_analysis.tests daily_footprints.tests --noinput --shuffle=20261015 2>&1 | tee evidence/phase4-tests.log
.venv/bin/coverage report | tee evidence/phase4-coverage.txt
.venv/bin/coverage json -o evidence/phase4-coverage.json
.venv/bin/python tools/footprints_mutations.py | tee evidence/footprints-mutations.log
.venv/bin/python tools/phase4_runtime_check.py | tee evidence/phase4-runtime.log
.venv/bin/python tools/browser_footprints.py | tee evidence/footprints-browser.log
fi
.venv/bin/python tools/browser_footprints_boot.py | tee evidence/footprints-boot.log
.venv/bin/python tools/browser_phase2.py | tee evidence/phase4-inherited-browser.log
.venv/bin/python tools/browser_phase3.py | tee evidence/phase4-budget-browser.log
.venv/bin/python tools/browser_warm_feedback.py | tee evidence/phase4-feedback-browser.log
.venv/bin/python tools/browser_daily_encouragement.py | tee evidence/phase4-daily-encouragement-browser.log
.venv/bin/python tools/browser_task_trash.py | tee evidence/phase4-trash-browser.log
.venv/bin/python tools/browser_task_trash.py --edge-only | tee evidence/phase4-trash-edge-browser.log
.venv/bin/python tools/safety_check.py | tee evidence/phase4-safety.log
.venv/bin/python tools/check_separation.py --source-only | tee evidence/phase4-source-separation.json
.venv/bin/python tools/source_state.py | tee evidence/phase4-source-sha256.txt
