"""Count fresh property examples and kill plausible reservation double-count bugs."""

import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTANTS = [
    "add_maintenance_twice",
    "stack_old_total_on_manual",
    "unknown_total_as_zero",
    "count_nonrunning_auto",
    "count_nonrunning_manual",
    "unknown_nonrunning_blocks_budget",
]


def child(mutant=None):
    sys.path.insert(0, str(ROOT))
    from hypothesis import statistics

    from load_analysis import rules

    original = rules._task_demand
    if mutant:

        def faulty(task):
            low, high, fields = original(task)
            if task.get("status") != "in_progress":
                source = task.get("allocation_source")
                if (mutant == "count_nonrunning_auto" and source == "auto") or (
                    mutant == "count_nonrunning_manual" and source == "manual"
                ):
                    return original({**task, "status": "in_progress"})
                if (
                    mutant == "unknown_nonrunning_blocks_budget"
                    and source == "auto"
                    and task.get("reservation_minutes") is None
                ):
                    return 0, 0, ["reservation_minutes"]
            if (
                mutant == "add_maintenance_twice"
                and task.get("allocation_source") == "auto"
                and task.get("reservation_minutes") is not None
            ):
                return low + 10080, high + 10080, fields
            if mutant == "stack_old_total_on_manual" and task.get("allocation_source") == "manual":
                extra = task.get("reservation_minutes") or 0
                return low + extra, high + extra, fields
            if (
                mutant == "unknown_total_as_zero"
                and task.get("allocation_source") == "auto"
                and task.get("reservation_minutes") is None
            ):
                return 0, 0, []
            return low, high, fields

        rules._task_demand = faulty
    collected = []
    stream = io.StringIO()
    with statistics.collector.with_value(collected.append):
        result = unittest.TextTestRunner(stream=stream, verbosity=1).run(
            unittest.defaultTestLoader.loadTestsFromName(
                "load_analysis.tests.test_budget_reservation_properties"
            )
        )
    count = sum(
        case["status"] == "valid"
        for report in collected
        for phase in ("reuse-phase", "generate-phase", "shrink-phase")
        for case in report.get(phase, {}).get("test-cases", [])
    )
    print(
        json.dumps(
            {
                "mutant": mutant,
                "tests": result.testsRun,
                "passed": result.wasSuccessful(),
                "killed": bool(result.failures) and not result.errors,
                "failures": len(result.failures),
                "errors": len(result.errors),
                "passing_examples": count,
                "output": stream.getvalue() if result.errors else "",
            }
        )
    )


def invoke(mutant=None):
    command = [sys.executable, __file__, "--child"] + ([mutant] if mutant else [])
    result = subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def main():
    baseline = invoke()
    assert baseline["passed"], baseline
    mutants = [invoke(name) for name in MUTANTS]
    assert all(m["killed"] for m in mutants), mutants
    report = {
        "seed": 20261014,
        "max_examples_per_property": 100,
        "baseline": baseline,
        "mutants": mutants,
    }
    (ROOT / "evidence/budget-property-evidence.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "properties": baseline["tests"],
                "passing_examples": baseline["passing_examples"],
                "mutants_killed": len(mutants),
                "seed": 20261014,
            }
        )
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        child(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        main()
