"""Rehearse phase-4 import and migration using synthetic data, never installed state."""

import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from initialize_from_phase3 import ROOT, business_snapshot, initialize

SEED = """
import uuid
from datetime import date
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.utils import timezone
from tasks.models import Task
from execution.models import AnalysisRun, Event, Step, TimeEntry
from load_analysis.models import CapacityWindow, LoadSnapshot
user = get_user_model().objects.create(username='phase4_import_fixture', password='!')
task = Task.objects.create(owner=user, title='Synthetic import fixture', status='in_progress',
    weekly_minutes=180, request_key=uuid.uuid4(), request_fingerprint='synthetic')
step = Step.objects.create(task=task, title='Synthetic step', criterion='done',position=0,status='completed')
TimeEntry.objects.create(task=task, date=date(2026,10,15), minutes=30)
TimeEntry.objects.create(task=task, step=step, date=date(2026,10,15), minutes=45)
Event.objects.create(task=task,step=step,actor=user,kind='complete',data={'note':'synthetic'})
window = CapacityWindow.objects.create(owner=user,week=date(2026,10,12),mode='week',budget_minutes=600,buffer_minutes=60)
LoadSnapshot.objects.create(owner=user,window=window,data={'synthetic': True})
Session.objects.create(session_key='synthetic_session',session_data='synthetic',expire_date=timezone.now())
for status in ['queued','running','cancelled']:
    AnalysisRun.objects.create(task=task,snapshot={},base_version=1,status=status,model='unused')
"""


def command(directory, *arguments):
    subprocess.run(
        [str(ROOT / ".venv/bin/python"), "manage.py", *arguments],
        cwd=ROOT,
        env={
            **os.environ,
            "TASKFLOW_DB": str(directory / "tasks.sqlite3"),
            "TASKFLOW_STATE_DIR": str(directory),
            "DEEPSEEK_API_KEY": "",
        },
        check=True,
        capture_output=True,
        timeout=60,
    )


def state(path):
    with sqlite3.connect(path) as connection:
        return business_snapshot(connection)


def main():
    with tempfile.TemporaryDirectory(prefix="liubai-phase4-runtime-") as temporary:
        directory = Path(temporary)
        source, target = directory / "phase3", directory / "phase4"
        source.mkdir()
        command(source, "migrate", "--noinput")
        command(source, "migrate", "daily_footprints", "zero", "--noinput")
        command(source, "shell", "-c", SEED)
        (source / "deepseek.json").write_text('{"api_key":"synthetic-only","model":"unused"}')
        before = state(source / "tasks.sqlite3")
        report = initialize(source, target)
        assert report["interrupted_old_runs"] == 2
        assert state(source / "tasks.sqlite3") == before
        assert state(target / "tasks.sqlite3") == before
        assert (source / "deepseek.json").read_bytes() == (target / "deepseek.json").read_bytes()
        assert (source / "secret-key").read_bytes() != (target / "secret-key").read_bytes()
        for name in [
            "tasks.sqlite3",
            "phase3-import-backup.sqlite3",
            "deepseek.json",
            "secret-key",
        ]:
            assert (target / name).stat().st_mode & 0o077 == 0
            assert not (target / name).is_symlink()
        with sqlite3.connect(target / "tasks.sqlite3") as connection:
            assert connection.execute(
                "SELECT SUM(minutes) FROM execution_timeentry"
            ).fetchone() == (75,)
            assert connection.execute(
                "SELECT budget_minutes,buffer_minutes FROM load_analysis_capacitywindow"
            ).fetchone() == (600, 60)
            assert connection.execute(
                "SELECT COUNT(*) FROM execution_analysisrun WHERE status IN ('queued','running')"
            ).fetchone() == (0,)
        try:
            initialize(source, target)
        except ValueError as error:
            assert "拒绝覆盖" in str(error)
        else:
            raise AssertionError("A repeated import must not overwrite the independent version")
        assert state(target / "tasks.sqlite3") == before
        command(target, "migrate", "daily_footprints", "zero", "--noinput")
        assert state(target / "tasks.sqlite3") == before
        command(target, "migrate", "--noinput")
        assert state(target / "tasks.sqlite3") == before
        with (
            sqlite3.connect(target / "phase3-import-backup.sqlite3") as backup,
            sqlite3.connect(directory / "restore.sqlite3") as restored,
        ):
            backup.backup(restored)
            assert business_snapshot(restored) == before
            assert restored.execute("SELECT COUNT(*) FROM django_session").fetchone() == (1,)
            assert restored.execute(
                "SELECT COUNT(*) FROM execution_analysisrun WHERE status IN ('queued','running')"
            ).fetchone() == (2,)
        report.update(
            {
                "test_state": "synthetic only",
                "actual_database_or_key_contents_read": False,
                "second_import_rejected_without_data_change": True,
                "migration_rollback_reapply_business_preserved": True,
                "backup_restore_preserves_source_sessions_and_jobs": True,
                "ledger_minutes": 75,
                "budget_and_buffer_minutes": [600, 60],
                "source_database_unchanged": True,
                "independent_signing_key_and_private_file_permissions": True,
            }
        )
    (ROOT / "evidence/phase4-runtime.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
