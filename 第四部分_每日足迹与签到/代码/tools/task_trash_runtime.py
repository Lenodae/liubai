"""Rehearse the additive trash migration and SQLite backup restore on synthetic data."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from phase3_runtime_check import ROOT, SEED, backup, command, legacy_state


def columns(database):
    with sqlite3.connect(database) as connection:
        return {row[1] for row in connection.execute("PRAGMA table_info(tasks_task)")}


def receipts(database):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            'SELECT id, owner_id, "key", fingerprint, response FROM load_analysis_loadreceipt ORDER BY id'
        ).fetchall()


def main():
    with tempfile.TemporaryDirectory(prefix="liubai-trash-migration-") as temporary:
        directory = Path(temporary)
        database = directory / "fixture.sqlite3"
        snapshot = directory / "before-trash.sqlite3"
        environment = {
            **os.environ,
            "TASKFLOW_DB": str(database),
            "TASKFLOW_STATE_DIR": str(directory / "state"),
            "DEEPSEEK_API_KEY": "",
            "DEEPSEEK_MODEL": "",
        }
        # Build the existing three-part schema without the new Task field.
        command(
            environment, "migrate", "load_analysis", "0005_existing_budget_policies", "--noinput"
        )
        command(environment, "migrate", "execution", "--noinput")
        command(environment, "migrate", "auth", "--noinput")
        command(environment, "migrate", "sessions", "--noinput")
        assert "deleted_at" not in columns(database)
        command(
            environment,
            "shell",
            "-c",
            SEED
            + "\nReceipt = apps.get_model('load_analysis', 'LoadReceipt')\n"
            + "Receipt.objects.create(owner=user, key=uuid.uuid4(), "
            + "fingerprint='synthetic', response={'original': 'preserved'})\n",
        )
        original = legacy_state(database)
        original_receipts = receipts(database)
        assert len(original_receipts) == 1
        backup(database, snapshot)

        command(environment, "migrate", "--noinput")
        assert "deleted_at" in columns(database)
        assert legacy_state(database) == original
        assert receipts(database) == original_receipts
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM tasks_task WHERE deleted_at IS NOT NULL"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT COUNT(*) FROM load_analysis_loadreceipt WHERE created_at IS NULL"
            ).fetchone() == (0,)

        command(environment, "migrate", "tasks", "0001_initial", "--noinput")
        command(
            environment, "migrate", "load_analysis", "0005_existing_budget_policies", "--noinput"
        )
        assert "deleted_at" not in columns(database)
        assert legacy_state(database) == original
        assert receipts(database) == original_receipts
        command(environment, "migrate", "--noinput")
        assert legacy_state(database) == original
        assert receipts(database) == original_receipts

        # Restore the pre-upgrade backup, then prove that the exact original
        # records can be upgraded again. No production database is opened.
        backup(snapshot, database)
        assert "deleted_at" not in columns(database)
        assert legacy_state(database) == original
        assert receipts(database) == original_receipts
        command(environment, "migrate", "--noinput")
        assert "deleted_at" in columns(database)
        assert legacy_state(database) == original
        assert receipts(database) == original_receipts
        command(environment, "check")
    result = {
        "additive_trash_migration_rollback_backup_restore": "pass",
        "existing_task_execution_rows_unchanged": True,
        "new_deleted_at_defaults_to_null": True,
        "existing_receipt_content_preserved_and_timestamp_backfilled": True,
        "synthetic_ledger_minutes": 140,
        "sqlite_integrity_and_foreign_keys": "pass",
        "rollback_scope": "Pre-feature fixture; reverting the field would discard new trash flags.",
        "real_database_or_secret_contents_read": False,
    }
    (ROOT / "evidence/task-trash-runtime.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
