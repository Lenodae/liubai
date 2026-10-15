"""Restore exact source bytes after each settings security regression mutant."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTANTS = [
    ("owner guard", "execution/settings_service.py", "if not can_manage(user_id):", "if False:"),
    (
        "stale form guard",
        "execution/settings_service.py",
        'if data.get("revision") != current["revision"]:',
        "if False:",
    ),
    (
        "model availability",
        "execution/settings_service.py",
        'if model not in {item["id"] for item in data}:',
        "if False:",
    ),
    (
        "verify before saving",
        "execution/settings_service.py",
        "            verify_connection(key, model)",
        "            pass",
    ),
    (
        "hostile response safety",
        "execution/settings_service.py",
        "except (ValueError, KeyError, TypeError):",
        "except (ValueError, KeyError):",
    ),
    (
        "storage error clarity",
        "execution/views.py",
        "本机配置无法读取，请检查目录权限。",
        "未知故障。",
    ),
]


def main():
    for name, filename, old, new in MUTANTS:
        path = ROOT / filename
        original = path.read_bytes()
        source = original.decode()
        assert source.count(old) == 1
        try:
            path.write_text(source.replace(old, new))
            command = [
                sys.executable,
                "manage.py",
                "test",
                "execution.tests.test_settings",
                "execution.tests.test_settings_properties",
                "--noinput",
            ]
            run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            (ROOT / "evidence" / f"settings-mutation-{name.replace(' ', '-')}.log").write_text(
                run.stdout + run.stderr
            )
            assert run.returncode != 0 and ("FAIL:" in run.stderr or "ERROR:" in run.stderr), name
            print(f"{name}: killed", flush=True)
            if name == "model availability":
                command.remove("execution.tests.test_settings")
                property_run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                assert property_run.returncode != 0 and "FAIL:" in property_run.stderr
                print("model availability: also killed by property suite alone", flush=True)
        finally:
            path.write_bytes(original)
            assert path.read_bytes() == original


if __name__ == "__main__":
    main()
