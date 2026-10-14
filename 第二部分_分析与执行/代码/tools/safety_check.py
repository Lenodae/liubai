"""Rehearse migrations in a disposable DB; inventory licenses and scan source patterns."""

import importlib.metadata as metadata
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from source_state import EXCLUDE, ROOT


def main():
    python = str(ROOT / ".venv/bin/python")
    with tempfile.TemporaryDirectory(prefix="taskflow-migrate-") as tmp:
        env = {**os.environ, "TASKFLOW_DB": str(Path(tmp) / "migration.sqlite3")}
        for command in [
            ["migrate", "--noinput"],
            ["migrate", "tasks", "zero", "--noinput"],
            ["migrate", "--noinput"],
            ["check"],
        ]:
            subprocess.run(
                [python, "manage.py", *command],
                cwd=ROOT,
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
            )
    packages = []
    for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        m = distribution.metadata
        packages.append(
            {
                "name": m["Name"],
                "version": m["Version"],
                "license": m.get("License-Expression")
                or m.get("License")
                or [c for c in m.get_all("Classifier", []) if c.startswith("License ::")],
            }
        )
    (ROOT / "evidence/licenses.json").write_text(json.dumps(packages, indent=2))
    hits = []
    patterns = [
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    ]
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDE for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix in {".py", ".js", ".html", ".sh", ".toml", ".txt"}:
            content = path.read_text()
            for pattern in patterns:
                if pattern.search(content):
                    hits.append(str(path.relative_to(ROOT)))
    assert not hits, hits
    print(
        json.dumps(
            {
                "migration_roundtrip": "pass",
                "secret_pattern_hits": hits,
                "packages_inventoried": len(packages),
                "capabilities": "localhost HTTP, isolated SQLite/session/secret files; explicit-consent DeepSeek HTTPS requests and dependency installation/audit; worker subprocess launched locally",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
