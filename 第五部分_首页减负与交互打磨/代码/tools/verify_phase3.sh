#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidence
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/ruff check . | tee evidence/phase3-lint.log
.venv/bin/ruff format --check . | tee -a evidence/phase3-lint.log
.venv/bin/mypy tasks config execution load_analysis --exclude 'tests|migrations' | tee evidence/phase3-types.log
node --check static/app.js
node --check static/duration.js
node --check static/load_feeling.js
node --check static/encouragement.js
node --check static/daily_encouragement.js
node --check static/execution.js
node --check static/load.js
node --check static/deepseek_settings.js
node --check static/budget_reservation.js
bash -n start.sh tools/verify.sh tools/verify_phase3.sh ../打开留白.command '../配置 DeepSeek.command'
.venv/bin/coverage run manage.py test tasks.tests execution.tests load_analysis.tests --noinput --shuffle=20261014 2>&1 | tee evidence/phase3-tests.log
.venv/bin/coverage report | tee evidence/phase3-coverage.txt
.venv/bin/coverage json -o evidence/phase3-coverage.json
.venv/bin/python tools/load_rule_mutations.py --properties-only | tee evidence/phase3-properties.log
.venv/bin/python tools/load_rule_mutations.py | tee evidence/phase3-rule-mutations.log
.venv/bin/python tools/load_api_mutations.py | tee evidence/phase3-api-mutations.log
.venv/bin/python tools/budget_policy_mutations.py | tee evidence/budget-policy-mutations.log
.venv/bin/python tools/budget_reservation_property_check.py | tee evidence/budget-property-check.log
.venv/bin/python tools/phase3_runtime_check.py --http | tee evidence/phase3-runtime.log
.venv/bin/python tools/task_trash_runtime.py | tee evidence/task-trash-runtime.log
.venv/bin/python tools/task_trash_mutations.py | tee evidence/task-trash-mutations.log
.venv/bin/python tools/load_benchmark.py | tee evidence/phase3-benchmark.log
.venv/bin/python tools/browser_phase2.py | tee evidence/phase3-inherited-browser.log
.venv/bin/python tools/browser_settings.py | tee evidence/phase3-settings-browser.log
.venv/bin/python tools/browser_phase3.py | tee evidence/phase3-browser.log
.venv/bin/python tools/browser_budget_reservation.py | tee evidence/budget-browser.log
.venv/bin/python tools/browser_active_budget.py | tee evidence/active-budget-browser.log
.venv/bin/python tools/browser_warm_feedback.py | tee evidence/warm-feedback-browser.log
.venv/bin/python tools/browser_warm_feedback.py --editor-only | tee evidence/warm-feedback-editor-browser.log
.venv/bin/python tools/browser_daily_encouragement.py | tee evidence/daily-encouragement-browser.log
.venv/bin/python tools/browser_task_trash.py | tee evidence/task-trash-browser.log
.venv/bin/python tools/browser_task_trash.py --edge-only | tee evidence/task-trash-edge-browser.log
.venv/bin/python tools/safety_check.py | tee evidence/phase3-safety.log
.venv/bin/python -m pip_audit --cache-dir .local/audit-cache --progress-spinner off -f json -o evidence/phase3-audit.json 2>&1 | tee evidence/phase3-audit.log
.venv/bin/python tools/check_separation.py --source-only | tee evidence/phase3-source-separation.json
if [ -f ../代码/.local/tasks.sqlite3 ] && [ -f ../../第二部分_分析与执行/代码/.local/tasks.sqlite3 ]; then
  .venv/bin/python tools/check_separation.py | tee evidence/phase3-separation.json
fi
.venv/bin/python tools/source_state.py | tee evidence/phase3-source-sha256.txt
