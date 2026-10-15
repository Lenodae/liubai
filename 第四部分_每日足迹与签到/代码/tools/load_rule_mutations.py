"""Exercise real rule assertions against in-memory mutants, without editing source files."""

import argparse
import hashlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "load_analysis" / "rules.py"
SEED = 20261014
MUTANTS = {
    "unknown_as_zero": (
        "if unknown or capacity is None:",
        "if capacity is None:",
    ),
    "paused_keeps_maintenance": (
        'if status != "in_progress" and task.get("historical") is not True:',
        'if status not in {"in_progress", "paused"} and task.get("historical") is not True:',
    ),
    "buffer_not_reserved": ("return budget - buffer, []", "return budget, []"),
    "exact_boundary_conflicts": ("if low > capacity:", "if low >= capacity:"),
    "largest_goal_replaces_cumulative": (
        "known_low += low or 0",
        "known_low = max(known_low, low or 0)",
    ),
    "other_commitments_subtracted_twice": (
        "cumulative += budget - buffer - other",
        "cumulative += budget - buffer - 2 * other",
    ),
}


def run_child(mutant, properties_only):
    from hypothesis import seed, settings, statistics

    settings.register_profile("load_rule_verification", max_examples=100, deadline=None)
    settings.load_profile("load_rule_verification")
    sys.path.insert(0, str(ROOT))
    from load_analysis.tests import test_properties, test_rules

    source = SOURCE.read_text()
    if mutant:
        before, after = MUTANTS[mutant]
        if source.count(before) != 1:
            raise RuntimeError(f"Mutant anchor count changed: {mutant}")
        namespace = {"__name__": "load_analysis.rules"}
        exec(compile(source.replace(before, after), str(SOURCE), "exec"), namespace)
        for module in (test_rules, test_properties):
            module.analyze = namespace["analyze"]
            module.deadline_checks = namespace["deadline_checks"]
    # Set a recorded Hypothesis seed on each generated test, in a fresh process.
    for cls in (test_properties.LoadProperties, test_properties.DeadlineProperties):
        for name in unittest.defaultTestLoader.getTestCaseNames(cls):
            setattr(cls, name, seed(SEED)(getattr(cls, name)))
    labels = ["load_analysis.tests.test_properties"]
    if not properties_only:
        labels.append("load_analysis.tests.test_rules")
    output = io.StringIO()
    collected = []
    with statistics.collector.with_value(collected.append):
        result = unittest.TextTestRunner(stream=output, verbosity=1).run(
            unittest.defaultTestLoader.loadTestsFromNames(labels)
        )
    valid_examples = sum(
        case["status"] == "valid"
        for report in collected
        for phase in ("reuse-phase", "generate-phase", "shrink-phase")
        for case in report.get(phase, {}).get("test-cases", [])
    )
    print(
        json.dumps(
            {
                "tests": result.testsRun,
                "failures": [str(test) for test, _ in result.failures],
                "errors": [str(test) for test, _ in result.errors],
                "passed": result.wasSuccessful(),
                "killed": bool(result.failures) and not result.errors,
                "property_tests": len(collected),
                "passing_property_examples": valid_examples,
                "output": output.getvalue() if result.errors else "",
            }
        )
    )


def invoke(mutant=None, properties_only=False):
    command = [sys.executable, str(Path(__file__).resolve()), "--child"]
    if mutant:
        command += ["--mutant", mutant]
    if properties_only:
        command.append("--properties-only")
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--mutant", choices=list(MUTANTS))
    parser.add_argument("--properties-only", action="store_true")
    args = parser.parse_args()
    if args.child:
        run_child(args.mutant, args.properties_only)
        return
    before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    baseline = invoke(properties_only=args.properties_only)
    if not baseline["passed"]:
        raise RuntimeError(f"Original suite failed: {baseline}")
    if args.properties_only:
        report = {"seed": SEED, "max_examples_per_property": 100, **baseline}
        output = ROOT / "evidence" / "load-rule-properties.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return
    results = {}
    for mutant in MUTANTS:
        all_tests = invoke(mutant)
        properties = invoke(mutant, properties_only=True)
        results[mutant] = {"all_tests": all_tests, "properties_only": properties}
        if not all_tests["killed"] or not properties["killed"]:
            raise RuntimeError(
                f"Mutant survived or failed for an invalid reason: {mutant}: {results[mutant]}"
            )
        print(f"KILLED by suite and properties: {mutant}")
    after = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("Rule source changed during mutation run")
    report = {
        "seed": SEED,
        "max_examples_per_property": 100,
        "source_sha256": after,
        "source_unchanged": before == after,
        "baseline": baseline,
        "mutants": results,
    }
    output = ROOT / "evidence" / "load-rule-mutations.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(results)}/{len(MUTANTS)} mutants killed; report: {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
