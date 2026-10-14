"""Apply plausible security/data-loss bugs one at a time, run checks, restore byte-for-byte."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT / ".venv/bin/python")
MUTANTS = [
    (
        "owner_scope",
        "tasks/services.py",
        "return Task.objects.filter(owner_id=user_id)",
        "return Task.objects.all()",
        "tasks.tests.test_api.ApiCase.test_isolation",
    ),
    (
        "version_guard",
        "tasks/services.py",
        ".filter(id=task_id, version=version)",
        ".filter(id=task_id)",
        "tasks.tests.test_api.ApiCase.test_optimistic_conflict",
    ),
    (
        "unknown_as_zero",
        "tasks/services.py",
        '"weekly_minutes": task.weekly_minutes,',
        '"weekly_minutes": task.weekly_minutes or 0,',
        "tasks.tests.test_api.ApiCase.test_create_persist_and_zero",
    ),
    (
        "duplicate_creation",
        "tasks/services.py",
        "if previous:",
        "if False and previous:",
        "tasks.tests.test_api.ApiCase.test_idempotency",
    ),
    (
        "missing_history",
        "tasks/services.py",
        "if new_status != task.status:",
        "if False and new_status != task.status:",
        "tasks.tests.test_api.ApiCase.test_status_history",
    ),
    (
        "empty_update",
        "tasks/services.py",
        "if not fields:",
        "if False and not fields:",
        "tasks.tests.test_adversarial.AdversarialCase.test_body_limit_and_empty_patch",
    ),
    (
        "overlong_password",
        "tasks/views.py",
        "or len(password) > 256",
        "or len(password) > 100000",
        "tasks.tests.test_adversarial.AdversarialCase.test_overlong_credentials_and_unknown_fields",
    ),
]


def run_test(name, log_path):
    result = subprocess.run(
        [PYTHON, "manage.py", "test", name, "--noinput"], cwd=ROOT, capture_output=True, text=True
    )
    output = result.stdout + result.stderr
    log_path.write_text(output)
    # A collection/setup failure is not a valid kill.
    return (
        result.returncode != 0
        and ("FAIL:" in output or "ERROR: test_" in output)
        and "Ran " in output
    )


def main():
    report = []
    for name, file, original, mutated, target in MUTANTS:
        path = ROOT / file
        source = path.read_bytes()
        content = source.decode()
        assert content.count(original) == 1, (name, content.count(original))
        try:
            path.write_text(content.replace(original, mutated))
            killed = run_test(target, ROOT / f"evidence/mutant-{name}.log")
            property_killed = run_test(
                "tasks.tests.test_properties.PropertyCase",
                ROOT / f"evidence/property-mutant-{name}.log",
            )
            report.append(
                {
                    "name": name,
                    "target": target,
                    "killed": killed,
                    "property_alone_killed": property_killed,
                }
            )
            print(
                name, "killed" if killed else "SURVIVED", "property:", property_killed, flush=True
            )
        finally:
            path.write_bytes(source)
            assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(source).digest()
    (ROOT / "evidence/mutations.json").write_text(json.dumps(report, indent=2))
    assert all(item["killed"] for item in report), "A chosen manual mutant survived"


if __name__ == "__main__":
    main()
