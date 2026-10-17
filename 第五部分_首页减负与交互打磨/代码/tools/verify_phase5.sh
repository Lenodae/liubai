#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
verification_state=$(mktemp -d "${TMPDIR:-/tmp}/liubai-phase5-verify.XXXXXX")
trap 'rm -rf "$verification_state"' EXIT
export TASKFLOW_STATE_DIR="$verification_state"
export TASKFLOW_DB="$verification_state/tasks.sqlite3"
export DEEPSEEK_API_KEY=""
if [ "${1:-}" != "--finish" ]; then
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/ruff check . | tee evidence/phase5-lint.log
.venv/bin/ruff format --check . | tee -a evidence/phase5-lint.log
.venv/bin/mypy tasks config execution load_analysis daily_footprints --exclude 'tests|migrations' | tee evidence/phase5-types.log
for script in static/*.js; do node --check "$script"; done
bash -n start.sh tools/verify_phase5.sh ../打开留白.command '../配置 DeepSeek.command'
.venv/bin/coverage run manage.py test tasks.tests execution.tests load_analysis.tests daily_footprints.tests --noinput --shuffle=20261015 2>&1 | tee evidence/phase5-tests.log
.venv/bin/coverage report | tee evidence/phase5-coverage.txt
.venv/bin/coverage json -o evidence/phase5-coverage.json
node tools/overview_focus_checks.cjs | tee evidence/overview-focus-checks.log
.venv/bin/python tools/phase5_runtime_check.py --legacy-snapshot-red | tee evidence/phase5-import-red.log
.venv/bin/python tools/phase5_runtime_check.py | tee evidence/phase5-runtime.log
.venv/bin/python tools/phase5_import_race_check.py --legacy-red | tee evidence/phase5-import-race-red.log
.venv/bin/python tools/phase5_import_race_check.py | tee evidence/phase5-import-race.log
.venv/bin/python tools/browser_overview.py --baseline | tee evidence/overview-baseline.log
.venv/bin/python tools/overview_focus_adversarial.py | tee evidence/overview-focus-adversarial.log
.venv/bin/python tools/browser_overview.py | tee evidence/overview-browser.log
.venv/bin/python tools/browser_footprints.py | tee evidence/footprints-browser.log
fi
.venv/bin/python tools/browser_footprints_boot.py | tee evidence/footprints-boot.log
.venv/bin/python tools/browser_phase2.py | tee evidence/phase5-inherited-browser.log
.venv/bin/python tools/browser_phase3.py | tee evidence/phase5-budget-browser.log
.venv/bin/python tools/browser_active_budget.py | tee evidence/phase5-active-budget-browser.log
.venv/bin/python tools/browser_warm_feedback.py | tee evidence/phase5-feedback-browser.log
.venv/bin/python tools/browser_daily_encouragement.py | tee evidence/phase5-daily-encouragement-browser.log
.venv/bin/python tools/browser_task_trash.py | tee evidence/phase5-trash-browser.log
.venv/bin/python tools/browser_task_trash.py --edge-only | tee evidence/phase5-trash-edge-browser.log
.venv/bin/python tools/safety_check.py | tee evidence/phase5-safety.log
.venv/bin/python tools/check_separation.py --source-only | tee evidence/phase5-source-separation.json
.venv/bin/python tools/source_state.py | tee evidence/phase5-source-sha256.txt
