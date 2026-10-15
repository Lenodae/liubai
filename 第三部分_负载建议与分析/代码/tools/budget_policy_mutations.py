"""In-memory behavior mutants; each run owns a disposable SQLite database."""

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "count_idea_as_running": "test_budget_policy.BudgetPolicyTests.test_weekly_idea_waits_until_started_before_occupying_budget",
    "count_paused_as_running": "test_budget_policy.BudgetPolicyTests.test_start_pause_and_resume_gate_total_reservation",
    "drop_recurring_future_weeks": "test_budget_policy_public.BudgetPolicyPublicTests.test_weekly_and_long_term_are_separate_and_complete_releases",
    "child_completion_ends_parent": "test_budget_policy_public.BudgetPolicyPublicTests.test_child_completion_keeps_parent_reservation",
    "drop_legacy_running_weekly_time": "test_active_budget_rules.ActiveLegacyBudgetTests.test_legacy_running_without_policy_is_included_and_get_does_not_write",
    "rewrite_old_history_with_current_status": "test_active_budget_rules.ActiveLegacyBudgetTests.test_old_revision_without_status_uses_old_historical_basis",
}


def child(name):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.test.runner import DiscoverRunner

    from load_analysis import policies, rules

    if name in {"count_idea_as_running", "count_paused_as_running"}:
        original = rules._task_demand
        state = "planned" if name == "count_idea_as_running" else "paused"

        def faulty(task):
            if task["status"] == state:
                minutes = task["weekly_minutes"]
                return minutes, minutes, []
            return original(task)

        rules._task_demand = faulty
    elif name == "drop_legacy_running_weekly_time":
        original = rules._task_demand

        def faulty(task):
            if task.get("reservation_basis") == "running_weekly_time":
                return 0, 0, []
            return original(task)

        rules._task_demand = faulty
    elif name == "rewrite_old_history_with_current_status":
        original = policies.reservation_state

        def faulty(task, week):
            active, amount, status, basis = original(task, week)
            if week < policies.monday():
                return False, None, task.status, basis
            return active, amount, status, basis

        policies.reservation_state = faulty
    elif name == "drop_recurring_future_weeks":
        original = policies.reservation_state

        def faulty(task, week):
            if week > policies.monday():
                return False, None, task.status, "current_status"
            return original(task, week)

        policies.reservation_state = faulty
    elif name == "child_completion_ends_parent":
        from execution import services
        from execution.models import Step

        original = services.change_status

        def faulty(task, target, status):
            original(task, target, status)
            if isinstance(target, Step) and status == "completed":
                task.status = "completed"
                task.save(update_fields=["status"])
                policies.synchronize(task)

        services.change_status = faulty
    stream = io.StringIO()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    kwargs = runner.get_test_runner_kwargs
    runner.get_test_runner_kwargs = lambda: {**kwargs(), "stream": stream}
    failures = runner.run_tests([f"load_analysis.tests.{CASES[name]}"])
    report = stream.getvalue()
    assert failures == 1 and "AssertionError" in report and "FAILED (failures=1)" in report, report
    print(json.dumps({"mutant": name, "killed_by": CASES[name], "assertion_failure": True}))


def main():
    results = []
    for name in CASES:
        with tempfile.TemporaryDirectory(prefix="liubai-policy-mutant-") as tmp:
            env = {
                **os.environ,
                "TASKFLOW_STATE_DIR": tmp,
                "TASKFLOW_DB": str(Path(tmp) / "db.sqlite3"),
            }
            result = subprocess.run(
                [sys.executable, __file__, "--child", name],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            results.append(json.loads(result.stdout.strip().splitlines()[-1]))
    (ROOT / "evidence/budget-policy-mutations.json").write_text(json.dumps(results, indent=2))
    print(json.dumps({"killed": len(results), "mutants": results}))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        child(sys.argv[2])
    else:
        main()
