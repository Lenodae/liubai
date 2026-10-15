"""One-time consistent local copy. Never overwrite a populated phase-3 database."""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parents[1] / "第二部分_分析与执行/代码/.local/tasks.sqlite3"
TARGET = ROOT / ".local/tasks.sqlite3"
BACKUP = ROOT / ".local/phase2-import-backup.sqlite3"


def counts(conn):
    tables = [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if row[0].startswith(("tasks_", "execution_")) or row[0] == "auth_user"
    ]
    return {
        table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables
    }


def main():
    if TARGET.exists() and TARGET.stat().st_size:
        raise SystemExit("第三部分已有数据库，拒绝覆盖。")
    if BACKUP.exists():
        raise SystemExit("导入备份已经存在，拒绝覆盖。")
    TARGET.parent.mkdir(mode=0o700, exist_ok=True)
    with (
        sqlite3.connect(SOURCE.as_uri() + "?mode=ro", uri=True) as source,
        sqlite3.connect(BACKUP) as backup,
    ):
        source.backup(backup)
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        before = counts(backup)
    BACKUP.chmod(0o600)
    with sqlite3.connect(BACKUP) as backup, sqlite3.connect(TARGET) as target:
        backup.backup(target)
        target.execute("DELETE FROM django_session")
        interrupted = target.execute(
            "UPDATE execution_analysisrun SET status='interrupted',error='第三部分独立初始化，旧请求已中断；需要时请明确重新生成。',finished_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')"
        ).rowcount
        target.commit()
    TARGET.chmod(0o600)
    env = {**os.environ, "TASKFLOW_DB": str(TARGET), "TASKFLOW_STATE_DIR": str(TARGET.parent)}
    subprocess.run(
        [str(ROOT / ".venv/bin/python"), "manage.py", "migrate", "--noinput"],
        cwd=ROOT,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with sqlite3.connect(TARGET) as target:
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not target.execute("PRAGMA foreign_key_check").fetchall()
        after = counts(target)
        assert before == after
        assert target.execute("SELECT COUNT(*) FROM django_session").fetchone()[0] == 0
    report = {
        "source": "第二部分独立SQLite快照",
        "target": "第三部分独立SQLite副本",
        "table_counts_preserved": before,
        "integrity": "ok",
        "foreign_keys": "ok",
        "sessions_cleared": True,
        "interrupted_old_runs": interrupted,
        "deepseek_configuration_copied": False,
    }
    (ROOT / "evidence/local-initialization.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                "copied": True,
                "counts_preserved": True,
                "users": before.get("auth_user", 0),
                "tasks": before.get("tasks_task", 0),
                "interrupted_old_runs": interrupted,
                "integrity": "ok",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
