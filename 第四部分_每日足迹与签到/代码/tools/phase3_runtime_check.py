"""Rehearse phase-2-to-phase-3 SQLite upgrade, rollback and backup restoration.

All databases and Django keys are disposable synthetic fixtures. Real .local files
are never opened. Optional --http checks a temporary web server on 127.0.0.1:8028;
no analysis worker is started and no external DeepSeek request is made.
"""

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"
SEED = """
import uuid
from datetime import date
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
executor = MigrationExecutor(connection)
apps = executor.loader.project_state(list(executor.loader.applied_migrations)).apps
User = apps.get_model('auth', 'User')
Task, TaskEvent = [apps.get_model('tasks', name) for name in ['Task', 'TaskEvent']]
Event, Profile, Step, TimeEntry = [apps.get_model('execution', name)
    for name in ['Event', 'Profile', 'Step', 'TimeEntry']]
user = User.objects.create(username='runtime_fixture', password='!')
task = Task.objects.create(owner=user, title='Synthetic migration fixture',
    request_key=uuid.uuid4(), request_fingerprint='fixture', status='completed')
TaskEvent.objects.create(task=task, from_status='planned', to_status='completed')
Profile.objects.create(task=task, criterion='fixture criterion', ledger_revision=3)
step = Step.objects.create(task=task, title='fixture step', criterion='fixture',
    position=0, status='completed', low=90, high=120)
TimeEntry.objects.create(task=task, step=step, date=date(2026, 10, 12), minutes=90)
TimeEntry.objects.create(task=task, step=step, date=date(2026, 10, 13), minutes=30)
TimeEntry.objects.create(task=task, date=date(2026, 10, 14), minutes=20)
Event.objects.create(task=task, step=step, actor=user, kind='complete',
    data={'note': 'synthetic completion', 'link': ''})
"""


def command(environment, *arguments):
    result = subprocess.run(
        [str(PYTHON), "manage.py", *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(f"Temporary migration command failed: {arguments}\n{result.stderr}")


def legacy_state(path):
    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert not database.execute("PRAGMA foreign_key_check").fetchall()
        names = sorted(
            row[0]
            for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] == "auth_user"
            or row[0].startswith(("tasks_", "execution_", "django_session"))
        )
        state = {}
        for name in names:
            # Compare existing business columns across additive task migrations.
            columns = [
                row[1]
                for row in database.execute(f'PRAGMA table_info("{name}")')
                if not (name == "tasks_task" and row[1] == "deleted_at")
            ]
            selected = ", ".join(f'"{column}"' for column in columns)
            rows = database.execute(f'SELECT {selected} FROM "{name}" ORDER BY rowid').fetchall()
            state[name] = {
                "rows": len(rows),
                "sha256": hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest(),
            }
        minutes = database.execute("SELECT SUM(minutes) FROM execution_timeentry").fetchone()[0]
        assert minutes == 140, "Synthetic ledger total changed"
        return state


def load_tables(path):
    with sqlite3.connect(path) as database:
        return {
            row[0]
            for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0].startswith("load_analysis_")
        }


def backup(source, destination):
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as destination_db:
        source_db.backup(destination_db)


def check_http(environment, directory):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8028))
    url = "http://127.0.0.1:8028/"
    with (directory / "server.log").open("w") as log:
        server = subprocess.Popen(
            [str(PYTHON), "manage.py", "runserver", "127.0.0.1:8028", "--noreload", "--insecure"],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(100):
                assert server.poll() is None, "Temporary web server exited before ready"
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        html = response.read().decode()
                        cookies = response.headers.get_all("Set-Cookie") or []
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                raise AssertionError("Temporary web server did not become ready")
            assert "<title>留白 · 预算与任务总览</title>" in html, "Unexpected page title"
            assert any("taskflow4_csrf=" in value for value in cookies), (
                "Missing phase-3 CSRF cookie"
            )
            return "pass (temporary port 8028; no worker)"
        finally:
            server.terminate()
            server.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", action="store_true")
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="liubai-phase3-runtime-") as name:
        directory = Path(name)
        database = directory / "fixture.sqlite3"
        snapshot = directory / "phase2-backup.sqlite3"
        environment = {
            **os.environ,
            "TASKFLOW_DB": str(database),
            "TASKFLOW_STATE_DIR": str(directory / "state"),
            "DEEPSEEK_API_KEY": "",
            "DEEPSEEK_MODEL": "",
        }
        command(environment, "migrate", "execution", "--noinput")
        command(environment, "migrate", "auth", "--noinput")
        command(environment, "migrate", "sessions", "--noinput")
        assert not load_tables(database), "Phase-2 fixture already contains phase-3 tables"
        command(environment, "shell", "-c", SEED)
        original = legacy_state(database)
        backup(database, snapshot)
        assert legacy_state(snapshot) == original

        command(environment, "migrate", "--noinput")
        assert load_tables(database), "No phase-3 tables after upgrade"
        assert legacy_state(database) == original, "Upgrade changed original records"
        command(environment, "migrate", "load_analysis", "zero", "--noinput")
        assert not load_tables(database), "Phase-3 tables remain after rollback"
        assert legacy_state(database) == original, "Rollback changed original records"
        command(environment, "migrate", "--noinput")
        assert load_tables(database), "Re-upgrade did not restore phase-3 schema"
        assert legacy_state(database) == original

        backup(snapshot, database)
        assert not load_tables(database), "Backup restore retained phase-3 tables"
        assert legacy_state(database) == original, "Backup restore changed fixture records"
        command(environment, "migrate", "--noinput")
        assert load_tables(database)
        assert legacy_state(database) == original
        command(environment, "check")
        http = check_http(environment, directory) if arguments.http else "not requested"
        result = {
            "synthetic_sqlite_backup_upgrade_rollback_restore": "pass",
            "original_task_execution_rows_preserved": True,
            "synthetic_ledger_minutes": 140,
            "sqlite_integrity_and_foreign_keys": "pass",
            "temporary_http_startup": http,
            "real_database_or_secret_contents_read": False,
            "external_api_calls": 0,
        }
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence/phase3-runtime.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
