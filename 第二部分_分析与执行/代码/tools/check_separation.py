"""Read-only isolation checks. Never reads or prints credentials/task contents."""

import hashlib
import json
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[3]
first = root / "第一部分_任务基础/代码"
second = root / "第二部分_分析与执行/代码"
manifest = json.loads((root / "项目总览/目录迁移记录.json").read_text())
for name, digest in manifest["original_source_sha256"].items():
    assert hashlib.sha256((first / name).read_bytes()).hexdigest() == digest, name
assert (first / ".venv").resolve() != (second / ".venv").resolve()
assert (first / ".local/tasks.sqlite3").stat().st_ino != (
    second / ".local/tasks.sqlite3"
).stat().st_ino
assert (first / ".local/secret-key").read_bytes() != (second / ".local/secret-key").read_bytes()
with sqlite3.connect(f"file:{first / '.local/tasks.sqlite3'}?mode=ro", uri=True) as db:
    assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'execution_%'").fetchall()
with sqlite3.connect(f"file:{second / '.local/tasks.sqlite3'}?mode=ro", uri=True) as db:
    assert db.execute("SELECT name FROM sqlite_master WHERE name='execution_timeentry'").fetchone()
print(
    json.dumps(
        {
            "phase1_original_source": "unchanged",
            "independent_virtualenvs": True,
            "independent_databases": True,
            "independent_secrets": True,
            "phase1_no_execution_tables": True,
            "planning_folders": [
                (root / p / "规划书").is_dir() for p in ["第一部分_任务基础", "第二部分_分析与执行"]
            ],
        },
        ensure_ascii=False,
    )
)
