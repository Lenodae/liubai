#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
inline_verification_state=$(mktemp -d "${TMPDIR:-/tmp}/liubai-inline-verify.XXXXXX")
trap 'rm -rf "$inline_verification_state"' EXIT
export TASKFLOW_STATE_DIR="$inline_verification_state"
export TASKFLOW_DB="$inline_verification_state/tasks.sqlite3"
export DEEPSEEK_API_KEY=""
.venv/bin/python tools/isolated_manage.py check
.venv/bin/python tools/isolated_manage.py makemigrations --check --dry-run
.venv/bin/ruff check . | tee evidence/inline-steps-lint.log
.venv/bin/ruff format --check . | tee -a evidence/inline-steps-lint.log
.venv/bin/mypy tasks config execution load_analysis daily_footprints --exclude 'tests|migrations' | tee evidence/inline-steps-types.log
for script in static/*.js; do node --check "$script"; done
bash -n tools/verify_inline_steps.sh start.sh ../打开留白.command
.venv/bin/coverage run tools/isolated_manage.py test tasks.tests execution.tests load_analysis.tests daily_footprints.tests --noinput --shuffle=20261017 2>&1 | tee evidence/inline-steps-tests.log
.venv/bin/coverage report --include='execution/overview.py' | tee evidence/inline-steps-coverage.log
.venv/bin/coverage json -o evidence/inline-steps-coverage.json
node tools/overview_focus_checks.cjs | tee evidence/inline-steps-focus-rules.log
.venv/bin/python tools/overview_steps_adversarial.py | tee evidence/inline-steps-properties.log
.venv/bin/python tools/browser_inline_steps.py | tee evidence/inline-steps-browser.log
.venv/bin/python tools/browser_overview.py --baseline | tee evidence/inline-steps-overview-baseline.log
.venv/bin/python tools/browser_overview.py | tee evidence/inline-steps-overview.log
.venv/bin/python tools/overview_focus_adversarial.py | tee evidence/inline-steps-focus-adversarial.log
.venv/bin/python tools/browser_phase2.py | tee evidence/inline-steps-execution.log
.venv/bin/python tools/browser_active_budget.py | tee evidence/inline-steps-budget.log
.venv/bin/python tools/browser_footprints.py | tee evidence/inline-steps-footprints.log
.venv/bin/python tools/browser_task_trash.py | tee evidence/inline-steps-trash.log
.venv/bin/python tools/safety_check.py | tee evidence/inline-steps-safety.log
.venv/bin/python tools/check_separation.py --source-only | tee evidence/inline-steps-separation.json
.venv/bin/python tools/source_state.py | tee evidence/inline-steps-source-sha256.txt
