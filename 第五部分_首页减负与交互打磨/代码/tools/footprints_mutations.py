"""Plausible in-memory defects, disposable databases, and independent property kills."""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "daily_footprints.tests.test_contract."
SUM_PROPERTY = "FootprintsProperties.test_ledger_sum_retry_and_mark_are_independent"
CASES = {
    "invalid_old_day_accepted": (
        "daily_footprints.dates",
        "    if result.year < 1900:\n",
        "    if False:\n",
        "FootprintsContract.test_day_input_floor_missing_date_and_unknown_fields_are_rejected",
        None,
    ),
    "voided_time_counted": (
        "daily_footprints.reading",
        ", voided_at__isnull=True",
        "",
        "FootprintsContract.test_parent_child_ledger_sum_edit_void_and_trash_retention",
        SUM_PROPERTY,
    ),
    "minutes_counted_twice": (
        "daily_footprints.reading",
        'rows[str(entry.date)]["minutes"] += entry.minutes',
        'rows[str(entry.date)]["minutes"] += entry.minutes * 2',
        "FootprintsContract.test_parent_child_ledger_sum_edit_void_and_trash_retention",
        SUM_PROPERTY,
    ),
    "retry_ignores_receipt": (
        "daily_footprints.writing",
        "    if prior:\n",
        "    if False:\n",
        "FootprintsContract.test_receipt_retry_collision_stale_version_and_old_replay",
        SUM_PROPERTY,
    ),
    "last_calendar_day_missing": (
        "daily_footprints.reading",
        "range((end - start).days + 1)",
        "range((end - start).days)",
        "FootprintsContract.test_recent_84_days_and_leap_year_today_mark",
        "FootprintsProperties.test_calendar_is_contiguous_bounded_and_complete",
    ),
    "foreign_time_leaked": (
        "daily_footprints.reading",
        "task__owner_id=uid, date__gte=start",
        "date__gte=start",
        "FootprintsContract.test_foreign_ledger_and_events_do_not_leak",
        None,
    ),
}


def child(name, layer):
    import importlib

    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.test.runner import DiscoverRunner

    module_name, old, new, contract, property_test = CASES[name]
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text()
    assert source.count(old) == 1, f"Mutation anchor changed: {name}"
    exec(compile(source.replace(old, new, 1), module.__file__, "exec"), module.__dict__)
    selected = PREFIX + (property_test if layer == "properties" else contract)
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
    for selected in ["contract", "properties"] if layer == "all" else [layer]:
        for name, case in CASES.items():
            if selected == "properties" and case[-1] is None:
                continue
            with tempfile.TemporaryDirectory(prefix="liubai-footprints-mutant-") as tmp:
                result = subprocess.run(
                    [sys.executable, __file__, "--child", name, "--layer", selected],
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "TASKFLOW_STATE_DIR": tmp,
                        "TASKFLOW_DB": str(Path(tmp) / "db.sqlite3"),
                        "DEEPSEEK_API_KEY": "",
                    },
                    text=True,
                    capture_output=True,
                )
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                results.append(json.loads(result.stdout.strip().splitlines()[-1]))
    report = {
        "killed": len(results),
        "mutants": results,
        "property_exclusions": "Owner privacy is covered by explicit adversarial assertions; the independent properties cover exact time sums, valid-entry filtering, retries and complete calendar ranges.",
    }
    (ROOT / f"evidence/footprints-mutations-{layer}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", choices=["all", "contract", "properties"], default="all")
    parser.add_argument("--child", choices=list(CASES))
    args = parser.parse_args()
    if args.child:
        with tempfile.TemporaryDirectory(prefix="liubai-footprints-child-") as temporary:
            os.environ["TASKFLOW_STATE_DIR"] = temporary
            os.environ["TASKFLOW_DB"] = str(Path(temporary) / "db.sqlite3")
            os.environ["DEEPSEEK_API_KEY"] = ""
            child(args.child, args.layer)
    else:
        main(args.layer)
