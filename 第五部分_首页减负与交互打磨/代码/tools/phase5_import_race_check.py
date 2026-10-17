"""Probe import publication races using disposable synthetic files only.

The migration subprocess is replaced with a callback that creates a target file
after initial validation. This models another process starting the independent
app during import. --legacy-red substitutes the previous overwrite publication
behavior in memory; no production file or source code is edited.
"""

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import initialize_from_phase4 as importer

OUTPUTS = (
    "phase4-import-backup.sqlite3",
    "secret-key",
    "deepseek.json",
    "tasks.sqlite3",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(directory):
    source, target = directory / "source", directory / "target"
    source.mkdir()
    target.mkdir()
    with sqlite3.connect(source / "tasks.sqlite3") as connection:
        connection.executescript(
            "CREATE TABLE django_session (id INTEGER);"
            "CREATE TABLE execution_analysisrun "
            "(id INTEGER, status TEXT, error TEXT, finished_at TEXT);"
            "CREATE TABLE tasks_task (id INTEGER, title TEXT);"
            "CREATE TABLE daily_footprints_daymark (id INTEGER, kind TEXT);"
            "CREATE TABLE daily_footprints_markreceipt (id INTEGER, response TEXT);"
            "INSERT INTO django_session VALUES (1);"
            "INSERT INTO tasks_task VALUES (1, 'source fixture');"
            "INSERT INTO daily_footprints_daymark VALUES (1, 'rest');"
            "INSERT INTO daily_footprints_markreceipt VALUES (1, 'receipt fixture');"
        )
    (source / "deepseek.json").write_text('{"api_key":"synthetic-source-only"}')
    return source, target


def create_concurrent_file(path):
    if path.name == "tasks.sqlite3":
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE concurrent_user_write (value TEXT)")
            connection.execute("INSERT INTO concurrent_user_write VALUES ('concurrent fixture')")
    else:
        path.write_text("synthetic concurrent file; this must survive")


def run_case(directory, name, *, race_file=None, failure_file=None, legacy=False):
    source, target = fixture(directory)
    source_before = digest(source / "tasks.sqlite3")
    source_config_before = digest(source / "deepseek.json")
    protected = target / race_file if race_file else None
    protected_before = None
    migration_called = False
    if name == "existing_empty_database":
        protected = target / "tasks.sqlite3"
        protected.touch()
        protected_before = digest(protected)

    def migration(*args, env, **kwargs):
        nonlocal migration_called, protected_before
        migration_called = True
        Path(env["TASKFLOW_STATE_DIR"], "secret-key").write_text("synthetic-new-signing-key")
        if race_file:
            create_concurrent_file(protected)
            protected_before = digest(protected)

    original_link, original_replace = importer.os.link, importer.os.replace

    def publish(source_file, destination_file, *, link):
        if failure_file and Path(destination_file).resolve() == (target / failure_file).resolve():
            raise OSError("Synthetic publication failure")
        if legacy or not link:
            return original_replace(source_file, destination_file)
        return original_link(source_file, destination_file)

    rejected = False
    rejection_type = None
    with (
        patch.object(importer.subprocess, "run", migration),
        patch.object(importer.os, "link", lambda src, dst: publish(src, dst, link=True)),
        patch.object(importer.os, "replace", lambda src, dst: publish(src, dst, link=False)),
    ):
        try:
            importer.initialize(source, target)
        except (ValueError, FileExistsError, OSError) as error:
            rejected, rejection_type = True, type(error).__name__
    issues = []
    if not rejected:
        issues.append("Import must fail instead of completing this collision/fault case")
    if protected and (not protected.exists() or digest(protected) != protected_before):
        issues.append("A target file created by another process was overwritten")
    if name == "existing_empty_database" and migration_called:
        issues.append("An existing target must be rejected before staging migration")
    if digest(source / "tasks.sqlite3") != source_before:
        issues.append("Source database changed")
    if digest(source / "deepseek.json") != source_config_before:
        issues.append("Source configuration changed")
    backup = target / OUTPUTS[0]
    if failure_file and failure_file != OUTPUTS[0]:
        if not backup.exists():
            issues.append("A published source backup must remain available after failure")
        else:
            with (
                sqlite3.connect(backup) as backup_connection,
                sqlite3.connect(source / "tasks.sqlite3") as source_connection,
            ):
                if importer.business_snapshot(backup_connection) != importer.business_snapshot(
                    source_connection
                ):
                    issues.append("Preserved backup does not match source business facts")
        if (target / "tasks.sqlite3").exists():
            issues.append("A failure before final database publication exposed a partial database")
    return {
        "case": name,
        "pass": not issues,
        "rejected": rejected,
        "rejection_type": rejection_type,
        "issues": issues,
    }


def main(legacy):
    results = []
    with tempfile.TemporaryDirectory(prefix="phase5-import-publication-") as temporary:
        base = Path(temporary)
        cases = [(f"concurrent_{name}", {"race_file": name}) for name in OUTPUTS]
        cases += [(f"failure_{name}", {"failure_file": name}) for name in OUTPUTS]
        cases.append(("existing_empty_database", {}))
        for index, (name, options) in enumerate(cases):
            directory = base / str(index)
            directory.mkdir()
            results.append(run_case(directory, name, legacy=legacy, **options))
    failures = [result for result in results if not result["pass"]]
    if legacy:
        assert all(
            not result["pass"] for result in results if result["case"].startswith("concurrent_")
        ), "The overwrite-publication negative control must expose every collision"
    report = {
        "synthetic_only": True,
        "actual_database_or_secret_contents_read": False,
        "migration": "mocked only to place competing writes after preflight",
        "publication": "legacy overwrite mutation" if legacy else "current implementation",
        "cases": results,
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "expected_red_observed": bool(legacy and failures),
    }
    evidence = importer.ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    suffix = "red" if legacy else "green"
    (evidence / f"phase5-import-publication-{suffix}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))
    if failures and not legacy:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-red", action="store_true")
    main(parser.parse_args().legacy_red)
