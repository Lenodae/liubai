"""Small, reversible fault injection for completion editing invariants."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTANTS = [
    (
        "completed target",
        "execution/services.py",
        'if (step or task).status != "completed":',
        "if False:",
    ),
    (
        "current completion",
        "execution/services.py",
        'if v.integer(data.get("event_id"), minimum=1, nullable=True) != expected_id:',
        "if False:",
    ),
    (
        "latest revision",
        "execution/serialization.py",
        "if record.step_id not in completions:",
        "if True:",
    ),
]


def main():
    for label, filename, before, after in MUTANTS:
        path = ROOT / filename
        original = path.read_bytes()
        source = original.decode()
        assert source.count(before) == 1
        try:
            path.write_text(source.replace(before, after))
            run = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "test",
                    "execution.tests.test_completion_edit",
                    "--noinput",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            (
                ROOT / "evidence" / f"completion-edit-mutation-{label.replace(' ', '-')}.log"
            ).write_text(run.stdout + run.stderr)
            assert run.returncode != 0 and "FAIL:" in run.stderr, label
            print(f"{label}: killed", flush=True)
        finally:
            path.write_bytes(original)
            assert path.read_bytes() == original


if __name__ == "__main__":
    main()
