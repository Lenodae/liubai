#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python tools/load_rule_mutations.py --properties-only | tee evidence/phase3-properties.log
.venv/bin/python tools/load_rule_mutations.py | tee evidence/phase3-rule-mutations.log
.venv/bin/python tools/load_api_mutations.py | tee evidence/phase3-api-mutations.log
.venv/bin/python tools/budget_policy_mutations.py | tee evidence/budget-policy-mutations.log
.venv/bin/python tools/budget_reservation_property_check.py | tee evidence/budget-property-check.log
.venv/bin/python tools/phase3_runtime_check.py --http | tee evidence/phase3-runtime.log
.venv/bin/python tools/load_benchmark.py | tee evidence/phase3-benchmark.log
.venv/bin/python tools/browser_phase2.py | tee evidence/phase3-inherited-browser.log
.venv/bin/python tools/browser_settings.py | tee evidence/phase3-settings-browser.log
.venv/bin/python tools/browser_phase3.py | tee evidence/phase3-browser.log
.venv/bin/python tools/browser_budget_reservation.py | tee evidence/budget-browser.log
.venv/bin/python tools/safety_check.py | tee evidence/phase3-safety.log
.venv/bin/python -m pip_audit --cache-dir .local/audit-cache --progress-spinner off -f json -o evidence/phase3-audit.json 2>&1 | tee evidence/phase3-audit.log
.venv/bin/python tools/check_separation.py --source-only | tee evidence/phase3-source-separation.json
if [ -f ../代码/.local/tasks.sqlite3 ] && [ -f ../../第二部分_分析与执行/代码/.local/tasks.sqlite3 ]; then
  .venv/bin/python tools/check_separation.py | tee evidence/phase3-separation.json
fi
.venv/bin/python tools/source_state.py | tee evidence/phase3-source-sha256.txt
