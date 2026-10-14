"""Real, reversible mutants; exact byte restoration and per-layer attribution."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTANTS = [
    ("version guard", "execution/services.py", "if task.version != version:", "if False:"),
    (
        "ownership",
        "execution/services.py",
        "task = owned_task(user_id, task_id)",
        'task = __import__("tasks.models", fromlist=["Task"]).Task.objects.get(id=task_id)',
    ),
    ("duplicate write", "execution/services.py", "if prior:\n", "if False:\n"),
    (
        "voided time counted",
        "execution/serialization.py",
        'query.filter(voided_at__isnull=True).aggregate(total=Sum("minutes"))',
        'query.aggregate(total=Sum("minutes"))',
    ),
    ("range upper boundary", "execution/rules.py", "if available < high", "if available <= high"),
    (
        "zero time allowed",
        "execution/services.py",
        'v.integer(data.get("minutes"), minimum=1, maximum=10080)',
        'v.integer(data.get("minutes"), minimum=0, maximum=10080)',
    ),
    ("cancel ignored", "execution/jobs.py", 'if run.status != "running":', "if False:"),
]


def main():
    results = []
    for name, filename, old, new in MUTANTS:
        path = ROOT / filename
        original = path.read_bytes()
        source = original.decode()
        assert source.count(old) == 1, (name, source.count(old))
        try:
            path.write_text(source.replace(old, new))
            scopes = []
            for label, test in [
                ("full", "execution.tests"),
                ("properties", "execution.tests.test_properties"),
            ]:
                run = subprocess.run(
                    [
                        str(ROOT / ".venv/bin/python"),
                        "manage.py",
                        "test",
                        test,
                        "--noinput",
                        "--verbosity",
                        "0",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                log = ROOT / "evidence" / f"mutation-{len(results) + 1}-{label}.log"
                log.write_text(run.stdout + run.stderr)
                scopes.append({"scope": label, "killed": run.returncode != 0})
            results.append({"name": name, "results": scopes})
            print(name, scopes, flush=True)
        finally:
            path.write_bytes(original)
            assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(original).digest()
    (ROOT / "evidence/execution-mutations.json").write_text(json.dumps(results, indent=2))
    assert all(r["results"][0]["killed"] for r in results), results


if __name__ == "__main__":
    main()
