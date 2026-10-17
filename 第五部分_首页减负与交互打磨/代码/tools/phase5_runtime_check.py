"""Rehearse phase-5 import and migration using synthetic data, never installed state."""

import argparse
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from initialize_from_phase4 import ROOT, business_snapshot, initialize

SEED = """
import uuid
from datetime import date
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.utils import timezone
from tasks.models import Task
from execution.models import AnalysisRun, Event, Step, TimeEntry
from load_analysis.models import CapacityWindow, LoadSnapshot
from daily_footprints.models import DayMark, MarkReceipt
user = get_user_model().objects.create(username='phase5_import_fixture', password='!')
task = Task.objects.create(owner=user, title='Synthetic import fixture', status='in_progress',
    weekly_minutes=180, request_key=uuid.uuid4(), request_fingerprint='synthetic')
step = Step.objects.create(task=task, title='Synthetic step', criterion='done',position=0,status='completed')
TimeEntry.objects.create(task=task, date=date(2026,10,15), minutes=30)
TimeEntry.objects.create(task=task, step=step, date=date(2026,10,15), minutes=45)
Event.objects.create(task=task,step=step,actor=user,kind='complete',data={'note':'synthetic'})
window = CapacityWindow.objects.create(owner=user,week=date(2026,10,12),mode='week',budget_minutes=600,buffer_minutes=60)
LoadSnapshot.objects.create(owner=user,window=window,data={'synthetic': True})
Session.objects.create(session_key='synthetic_session',session_data='synthetic',expire_date=timezone.now())
for day, kind in [(12, 'checkin'), (13, 'rest'), (14, None)]:
    DayMark.objects.create(owner=user,date=date(2026,10,day),kind=kind,version=2)
MarkReceipt.objects.create(owner=user,key=uuid.uuid4(),fingerprint='f'*64,
    response={'date':'2026-10-12','kind':'checkin','version':2,'synthetic':True})
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
    with tempfile.TemporaryDirectory(prefix="liubai-phase5-runtime-") as temporary:
        directory = Path(temporary)
        source, target = directory / "phase4", directory / "phase5"
        source.mkdir()
        command(source, "migrate", "--noinput")
        command(source, "shell", "-c", SEED)
        (source / "deepseek.json").write_text('{"api_key":"synthetic-only","model":"unused"}')
        before = state(source / "tasks.sqlite3")
        assert "daily_footprints_daymark" in before
        assert "daily_footprints_markreceipt" in before
        assert before["daily_footprints_daymark"][0] == 3
        assert before["daily_footprints_markreceipt"][0] == 1
        report = initialize(source, target)
        assert report["interrupted_old_runs"] == 2
        assert state(source / "tasks.sqlite3") == before
        assert state(target / "tasks.sqlite3") == before
        assert (source / "deepseek.json").read_bytes() == (target / "deepseek.json").read_bytes()
        assert (source / "secret-key").read_bytes() != (target / "secret-key").read_bytes()
        for name in [
            "tasks.sqlite3",
            "phase4-import-backup.sqlite3",
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
        command(target, "migrate", "--noinput")
        assert state(target / "tasks.sqlite3") == before
        with (
            sqlite3.connect(target / "phase4-import-backup.sqlite3") as backup,
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
                "migration_reapply_business_preserved": True,
                "checkin_rest_cleared_marks_and_receipts_preserved": True,
                "backup_restore_preserves_source_sessions_and_jobs": True,
                "ledger_minutes": 75,
                "budget_and_buffer_minutes": [600, 60],
                "source_database_unchanged": True,
                "independent_signing_key_and_private_file_permissions": True,
            }
        )
    (ROOT / "evidence/phase5-runtime.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-snapshot-red", action="store_true")
    arguments = parser.parse_args()
    if arguments.legacy_snapshot_red:
        import initialize_from_phase3 as legacy

        # The pre-existing checker omitted all footprint facts. Show that the new
        # contract detects that omission on populated synthetic tables.
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE TABLE daily_footprints_daymark (id INTEGER, kind TEXT)")
            connection.execute("INSERT INTO daily_footprints_daymark VALUES (1, 'rest')")
            assert legacy.business_snapshot(connection) == {}
            current = business_snapshot(connection)
            assert current["daily_footprints_daymark"][0] == 1
            try:
                assert "daily_footprints_daymark" in legacy.business_snapshot(connection)
            except AssertionError:
                print(
                    "RED observed: inherited snapshot omits footprint records; new contract rejects it"
                )
            else:
                raise AssertionError("The historical omission must fail the preservation contract")
    else:
        main()
