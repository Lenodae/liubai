"""Disposable in-memory mutants; never edit application files or the user's database."""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "tasks.tests.test_lifecycle."
PROPERTY = (
    PREFIX + "LifecycleProperties.test_round_trip_preserves_facts_and_releases_exact_contribution"
)
CASES = {
    "no_tombstone": (
        "tasks.lifecycle",
        "deleted_at=stamp if deleting else None",
        "deleted_at=None",
        "LifecycleCase.test_delete_and_restore_all_statuses_and_list_counts",
        True,
    ),
    "deleted_still_budgeted": (
        "load_analysis.workspace",
        "return [task for task in tasks if task.deleted_at is None]",
        "return list(tasks)",
        "LifecycleCase.test_current_future_release_historical_preservation_and_token_consistency",
        True,
    ),
    "historical_uses_current_tombstone": (
        "load_analysis.workspace",
        "if week >= policies.monday():",
        "if True:",
        "LifecycleCase.test_restore_does_not_rewrite_prior_deleted_weeks",
        True,
    ),
    "restore_loses_state": (
        "tasks.lifecycle",
        "    task.refresh_from_db()",
        '    if not deleting:\n        task.status = "planned"\n        task.save(update_fields=["status"])\n    task.refresh_from_db()',
        "LifecycleCase.test_delete_and_restore_all_statuses_and_list_counts",
        True,
    ),
    "delete_loses_actual_time": (
        "tasks.lifecycle",
        "    if deleting:\n",
        "    if deleting:\n        task.time_entries.all().delete()\n",
        "LifecycleCase.test_preserves_relations_completion_ledger_verification_and_snapshots",
        True,
    ),
    "retry_writes_twice": (
        "tasks.lifecycle",
        "    if prior:\n",
        "    if False:\n",
        "LifecycleCase.test_idempotency_collision_and_stale_version",
        True,
    ),
    "owner_filter_removed": (
        "tasks.services",
        "Task.objects.filter(owner_id=user_id).select_related",
        "Task.objects.all().select_related",
        "LifecycleCase.test_owner_scope_auth_csrf_and_hostile_fields",
        False,
    ),
    "transaction_removed": (
        "tasks.lifecycle",
        "@transaction.atomic\n",
        "",
        "LifecycleCase.test_receipt_failure_rolls_back_task_and_ai_cancellation",
        False,
    ),
    "deadline_replay_wrong_shape": (
        "load_analysis.services",
        "return deadlines.get(uid, week, mode)",
        "return w.build(uid, week, mode)",
        "LifecycleCase.test_deadline_receipt_retry_keeps_forecast_contract_after_trash_and_restore",
        False,
    ),
}


def child(name, layer):
    import importlib

    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.test.runner import DiscoverRunner

    module_name, old, new, test, _ = CASES[name]
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text()
    assert source.count(old) == 1, f"Mutation anchor changed: {name}"
    exec(compile(source.replace(old, new, 1), module.__file__, "exec"), module.__dict__)
    selected = PROPERTY if layer == "properties" else PREFIX + test
    if layer == "properties" and name == "historical_uses_current_tombstone":
        selected = PREFIX + "LifecycleProperties.test_time_passage_preserves_deleted_whole_weeks"
    stream = io.StringIO()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    kwargs = runner.get_test_runner_kwargs
    runner.get_test_runner_kwargs = lambda: {**kwargs(), "stream": stream}
    failures = runner.run_tests([selected])
    report = stream.getvalue()
    assert failures == 1 and "AssertionError" in report and "FAILED (failures=1)" in report, report
    print(
        json.dumps(
            {"mutant": name, "layer": layer, "killed_by": selected, "assertion_failure": True}
        )
    )


def main(layer):
    results = []
    layers = ["contract", "properties"] if layer == "all" else [layer]
    for chosen in layers:
        for name, case in CASES.items():
            if chosen == "properties" and not case[-1]:
                continue
            with tempfile.TemporaryDirectory(prefix="liubai-trash-mutant-") as tmp:
                env = {
                    **os.environ,
                    "TASKFLOW_STATE_DIR": tmp,
                    "TASKFLOW_DB": str(Path(tmp) / "db.sqlite3"),
                }
                result = subprocess.run(
                    [sys.executable, __file__, "--child", name, "--layer", chosen],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                results.append(json.loads(result.stdout.strip().splitlines()[-1]))
    report = {
        "killed": len(results),
        "mutants": results,
        "property_exclusions": "Owner isolation and rollback are contract/adversarial assertions; property layer targets state, budget, data retention and retries.",
    }
    (ROOT / f"evidence/task-trash-mutations-{layer}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", choices=["all", "contract", "properties"], default="all")
    parser.add_argument("--child", choices=list(CASES))
    args = parser.parse_args()
    child(args.child, args.layer) if args.child else main(args.layer)
