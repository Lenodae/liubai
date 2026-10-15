"""Run behavior tests against three in-memory service bugs; source stays untouched."""

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "ignore_source_changes": "test_new_task_and_versions_expire_preview",
    "forget_idempotent_receipt": "test_preview_apply_idempotency_and_undo",
    "drop_atomic_boundary": "test_atomic_rollback",
}


def child(name):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.test.runner import DiscoverRunner

    from load_analysis import services

    if name == "ignore_source_changes":
        services.assert_current = lambda *_: None
    elif name == "forget_idempotent_receipt":
        services.save_receipt = lambda *_: None
    elif name == "drop_atomic_boundary":
        services.mutate = services.mutate.__wrapped__
    output = io.StringIO()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    runner_kwargs = runner.get_test_runner_kwargs
    runner.get_test_runner_kwargs = lambda: {**runner_kwargs(), "stream": output}
    failures = runner.run_tests([f"load_analysis.tests.test_api.LoadApiTests.{CASES[name]}"])
    report = output.getvalue()
    assert failures == 1 and "AssertionError" in report and "FAILED (failures=1)" in report, report
    print(json.dumps({"mutant": name, "killed_by": CASES[name], "assertion_failure": True}))


def main():
    results = []
    for name in CASES:
        with tempfile.TemporaryDirectory(prefix="liubai-api-mutant-") as tmp:
            env = {
                **os.environ,
                "TASKFLOW_STATE_DIR": tmp,
                "TASKFLOW_DB": str(Path(tmp) / "db.sqlite3"),
            }
            run = subprocess.run(
                [sys.executable, __file__, "--child", name],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            if run.returncode:
                raise RuntimeError(run.stdout + run.stderr)
            results.append(json.loads(run.stdout.strip().splitlines()[-1]))
    (ROOT / "evidence/load-api-mutations.json").write_text(json.dumps(results, indent=2))
    print(json.dumps({"killed": len(results), "mutants": results}))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        child(sys.argv[2])
    else:
        main()
