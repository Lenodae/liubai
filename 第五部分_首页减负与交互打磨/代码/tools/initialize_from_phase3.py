"""Copy a consistent phase-3 snapshot into an empty independent phase-4 state directory."""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parents[1] / "第三部分_负载建议与分析/代码/.local"


def business_snapshot(connection):
    names = [
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if row[0].startswith(("tasks_", "execution_", "load_analysis_")) or row[0] == "auth_user"
    ]
    result = {}
    for name in names:
        columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')]
        # Imported unfinished requests are deliberately interrupted, never executed twice.
        if name == "execution_analysisrun":
            columns = [c for c in columns if c not in {"status", "error", "finished_at"}]
        selected = ",".join(f'"{column}"' for column in columns)
        rows = sorted(repr(row) for row in connection.execute(f'SELECT {selected} FROM "{name}"'))
        result[name] = (len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest())
    return result


def initialize(source_dir, target_dir):
    source_dir, target_dir = source_dir.resolve(), target_dir.resolve()
    if source_dir == target_dir or not (source_dir / "tasks.sqlite3").is_file():
        raise ValueError("需要独立且存在的第三部分数据库。")
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target_dir.chmod(0o700)
    with (target_dir / "import.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target, backup = target_dir / "tasks.sqlite3", target_dir / "phase3-import-backup.sqlite3"
        if (target.exists() and target.stat().st_size) or backup.exists():
            raise ValueError("第四部分已有数据库或导入备份，拒绝覆盖。")
        with tempfile.TemporaryDirectory(prefix="import-", dir=target_dir) as temporary:
            stage = Path(temporary)
            with (
                sqlite3.connect(
                    (source_dir / "tasks.sqlite3").as_uri() + "?mode=ro", uri=True
                ) as source,
                sqlite3.connect(stage / "backup.sqlite3") as saved,
            ):
                source.backup(saved)
                assert saved.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                before = business_snapshot(saved)
            with (
                sqlite3.connect(stage / "backup.sqlite3") as saved,
                sqlite3.connect(stage / "tasks.sqlite3") as destination,
            ):
                saved.backup(destination)
                destination.execute("DELETE FROM django_session")
                previous_runs = destination.execute(
                    "SELECT id,status,error,finished_at FROM execution_analysisrun "
                    "WHERE status NOT IN ('queued','running') ORDER BY id"
                ).fetchall()
                interrupted = destination.execute(
                    "UPDATE execution_analysisrun SET status='interrupted',"
                    "error='第四部分独立初始化，旧请求已中断；需要时请明确重新生成。',"
                    "finished_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')"
                ).rowcount
                destination.commit()
            environment = {
                **os.environ,
                "TASKFLOW_DB": str(stage / "tasks.sqlite3"),
                "TASKFLOW_STATE_DIR": str(stage),
                "DEEPSEEK_API_KEY": "",
            }
            subprocess.run(
                [str(ROOT / ".venv/bin/python"), "manage.py", "migrate", "--noinput"],
                cwd=ROOT,
                env=environment,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            with sqlite3.connect(stage / "tasks.sqlite3") as destination:
                assert business_snapshot(destination) == before
                assert destination.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                assert destination.execute("PRAGMA foreign_key_check").fetchall() == []
                assert destination.execute("SELECT COUNT(*) FROM django_session").fetchone() == (0,)
                for row in previous_runs:
                    assert (
                        destination.execute(
                            "SELECT id,status,error,finished_at FROM execution_analysisrun WHERE id=?",
                            (row[0],),
                        ).fetchone()
                        == row
                    )
            configuration = source_dir / "deepseek.json"
            if configuration.is_file():
                shutil.copyfile(configuration, stage / "deepseek.json")
                assert (
                    hashlib.sha256(configuration.read_bytes()).digest()
                    == hashlib.sha256((stage / "deepseek.json").read_bytes()).digest()
                )
            for name in ["backup.sqlite3", "secret-key", "deepseek.json", "tasks.sqlite3"]:
                path = stage / name
                if path.exists():
                    path.chmod(0o600)
                    os.replace(path, backup if name == "backup.sqlite3" else target_dir / name)
        return {
            "source": "第三部分一致性SQLite快照",
            "target": "第四部分独立副本",
            "business_tables_preserved": len(before),
            "original_business_rows_and_columns_preserved": True,
            "sessions_cleared": True,
            "interrupted_old_runs": interrupted,
            "deepseek_configuration_copied_byte_for_byte": configuration.is_file(),
            "secret_key": "new independent value",
            "secret_contents_logged": False,
            "integrity_and_foreign_keys": "pass",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SOURCE)
    parser.add_argument("--target-dir", type=Path, default=ROOT / ".local")
    args = parser.parse_args()
    report = initialize(args.source_dir, args.target_dir)
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence/phase4-initialization.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit("第五部分请使用 tools/initialize_from_phase4.py；旧导入入口已停用。")
