"""Backups of the database and passport files, and restoring them (US 126). No AWS needed."""

import ast
from contextlib import closing
import io
import importlib.util
import json
import os
import sqlite3
import subprocess
import tarfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
import pytest

from app.schema import migration_config

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup_tools.py"
REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("backup_tools", SCRIPT)
backup_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup_tools)
NOW = datetime(2026, 10, 31, 3, 0, tzinfo=timezone.utc)


def traveler(database, email):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("INSERT INTO traveler (name,email,password_hash,auth_type) VALUES (?,?,?,?)",
                           ("Specimen", email, "hash", "email_password"))


def emails(database):
    with closing(sqlite3.connect(database)) as connection:
        return [row[0] for row in connection.execute("SELECT email FROM traveler ORDER BY id")]


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A data directory laid out like /srv/taasheera, with a migrated database and one passport image."""
    root = tmp_path / "srv"
    root.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(root / 'taasheera.db').as_posix()}")
    command.upgrade(migration_config(), "head")
    traveler(root / "taasheera.db", "kept@example.com")
    (root / "passports" / "1").mkdir(parents=True)
    (root / "passports" / "1" / ("a" * 32)).write_bytes(b"specimen image bytes")
    (root / "activity-logs").mkdir()
    (root / "activity-logs" / "1.jsonl").write_text('{"event_type":"page_visit"}\n')
    (root / "private").mkdir()
    (root / "private" / "app.env").write_text("JWT_SECRET=never-in-a-backup\nORIGIN_TOKEN=" + "f" * 64 + "\n")
    return root


def test_script_runs_on_the_hosts_python_39():
    # The host has Amazon Linux's Python 3.9 and no packages: newer syntax or a third-party import would break it.
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), feature_version=(3, 9))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported <= {"__future__", "argparse", "contextlib", "fcntl", "hashlib", "io", "json", "os", "re", "shutil",
                        "sqlite3", "subprocess", "sys", "tarfile", "tempfile", "time", "datetime", "pathlib", "typing"}


def test_backup_holds_the_database_files_and_a_manifest_but_no_secrets(data, tmp_path):
    archive = backup_tools.create_backup(data, tmp_path / "out", NOW)
    assert archive.name == "20261031T030000Z.tar.gz"
    assert archive.with_name(archive.name + ".sha256").read_text().split()[0] == backup_tools.sha256(archive)
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        manifest = json.load(tar.extractfile("manifest.json"))
    assert names == {"taasheera.db", "manifest.json", f"passports/1/{'a' * 32}", "activity-logs/1.jsonl"}
    assert not any(name.startswith("private") for name in names)
    assert b"never-in-a-backup" not in archive.read_bytes()
    assert manifest["counts"]["traveler"] == 1
    assert manifest["revision"]
    assert set(manifest["files"]) == names - {"manifest.json"}


def test_backup_is_consistent_while_the_api_keeps_writing(data, tmp_path):
    stop = threading.Event()

    def write():
        number = 0
        while not stop.is_set():
            number += 1
            traveler(data / "taasheera.db", f"writer{number}@example.com")

    writer = threading.Thread(target=write)
    writer.start()
    try:
        archive = backup_tools.create_backup(data, tmp_path / "out", NOW)
    finally:
        stop.set()
        writer.join()
    manifest = backup_tools.verify_backup(archive, archive.with_name(archive.name + ".sha256"), tmp_path / "check")
    assert manifest["counts"]["traveler"] >= 1


def test_restore_round_trip_brings_back_rows_and_files_and_keeps_what_it_replaced(data, tmp_path):
    archive = backup_tools.create_backup(data, tmp_path / "out", NOW)
    # After the backup: a newer traveler, and the passport image is lost.
    traveler(data / "taasheera.db", "newer@example.com")
    (data / "passports" / "1" / ("a" * 32)).unlink()

    staging = tmp_path / "staging"
    backup_tools.verify_backup(archive, archive.with_name(archive.name + ".sha256"), staging)
    commands = []
    kept = backup_tools.restore_backup(data, staging, REPO, run=commands.append, now=NOW)

    assert emails(data / "taasheera.db") == ["kept@example.com"]
    assert (data / "passports" / "1" / ("a" * 32)).read_bytes() == b"specimen image bytes"
    # The data it replaced is kept aside, never deleted.
    assert emails(kept / "taasheera.db") == ["kept@example.com", "newer@example.com"]
    assert (data / "private" / "app.env").is_file()
    # Stop, migrate, start and wait for health, then check readiness through the origin.
    assert [command[4:6] if command[0] == "docker" else command[0] for command in commands] == [
        ["stop", "web"], ["run", "--rm"], ["up", "-d"], "curl"]
    assert commands[-1][-1] == "http://127.0.0.1/health/ready"
    assert f"X-Taasheera-Origin: {'f' * 64}" in commands[-1]


def test_damaged_or_mismatched_backups_are_refused_before_anything_changes(data, tmp_path):
    archive = backup_tools.create_backup(data, tmp_path / "out", NOW)
    checksum = archive.with_name(archive.name + ".sha256")
    before = (data / "taasheera.db").read_bytes()

    good = checksum.read_text()
    checksum.write_text("0" * 64 + "  x\n")
    with pytest.raises(backup_tools.BackupError, match="checksum"):
        backup_tools.verify_backup(archive, checksum, tmp_path / "one")
    checksum.write_text(good)

    # A backup whose database is corrupt but whose checksums were rewritten to match.
    broken = tmp_path / "broken.tar.gz"
    with tarfile.open(archive) as source, tarfile.open(broken, "w:gz") as target:
        for member in source.getmembers():
            content = source.extractfile(member).read()
            if member.name == "taasheera.db":
                content = content[:100] + b"\x00" * 4096 + content[4196:]
            if member.name == "manifest.json":
                manifest = json.loads(content)
                manifest["files"]["taasheera.db"] = None
                content = json.dumps(manifest).encode()
            member.size = len(content)
            target.addfile(member, io.BytesIO(content))
    broken.with_name(broken.name + ".sha256").write_text(backup_tools.sha256(broken) + "  broken.tar.gz\n")
    with pytest.raises(backup_tools.BackupError):
        backup_tools.verify_backup(broken, broken.with_name(broken.name + ".sha256"), tmp_path / "two")
    assert (data / "taasheera.db").read_bytes() == before


def test_entries_outside_the_backup_layout_are_refused(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("x")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload, arcname="../private/app.env")
    archive.with_name(archive.name + ".sha256").write_text(backup_tools.sha256(archive) + "  evil.tar.gz\n")
    with pytest.raises(backup_tools.BackupError, match="unexpected entry"):
        backup_tools.verify_backup(archive, archive.with_name(archive.name + ".sha256"), tmp_path / "staging")
    assert not (tmp_path / "private").exists()


def test_prune_keeps_the_newest_backups_and_their_checksums(data, tmp_path):
    out = tmp_path / "out"
    for day in range(4):
        backup_tools.create_backup(data, out, NOW + timedelta(days=day))
    removed = backup_tools.prune(out, keep=2)
    assert [path.name for path in removed] == ["20261031T030000Z.tar.gz", "20261101T030000Z.tar.gz"]
    assert sorted(path.name for path in out.iterdir()) == [
        "20261102T030000Z.tar.gz", "20261102T030000Z.tar.gz.sha256",
        "20261103T030000Z.tar.gz", "20261103T030000Z.tar.gz.sha256"]
    with pytest.raises(backup_tools.BackupError):
        backup_tools.prune(out, keep=0)


def test_backups_upload_through_the_aws_cli_encrypted_and_to_the_backup_prefix(data, tmp_path):
    commands = []
    uploader = backup_tools.AwsCliUploader("taasheera-backups-example", run=commands.append,
                                           output=lambda command: json.dumps([
                                               "db/20261030T030000Z.tar.gz", "db/20261030T030000Z.tar.gz.sha256",
                                               "db/manual-copy.tar.gz"]))
    archive = backup_tools.create_backup(data, tmp_path / "out", NOW)
    assert backup_tools.upload_backup(uploader, archive) == "db/20261031T030000Z.tar.gz"
    assert commands[0] == ["aws", "s3", "cp", str(archive), "s3://taasheera-backups-example/db/20261031T030000Z.tar.gz",
                           "--sse", "AES256", "--only-show-errors"]
    assert commands[1][4].endswith(".tar.gz.sha256")
    # Only the timer's own names count for --latest; a hand-named upload can't sort its way to the top.
    assert uploader.keys() == ["db/20261030T030000Z.tar.gz"]
    with pytest.raises(backup_tools.BackupError):
        backup_tools.AwsCliUploader("")


def test_command_line_backup_and_verify_only_restore(data, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TAASHEERA_BACKUP_BUCKET", raising=False)
    # Without a bucket the scheduled backup fails loudly, before doing any work.
    lock = ["--data-dir", str(data), "--lock", str(tmp_path / "lock")]
    assert backup_tools.main([*lock, "backup"]) == 1
    assert not (data / "private" / "backups").exists()
    assert backup_tools.main([*lock, "backup", "--no-upload"]) == 0
    archive = next((data / "private" / "backups" / "scheduled").glob("*.tar.gz"))
    # Without --yes, restore only checks the backup.
    before = (data / "taasheera.db").read_bytes()
    assert backup_tools.main([*lock, "restore", "--archive", str(archive)]) == 0
    assert "Nothing changed" in capsys.readouterr().out
    assert (data / "taasheera.db").read_bytes() == before


def test_systemd_units_run_daily_as_root_and_hold_no_secrets():
    folder = REPO / "deploy" / "aws" / "backup"
    service = (folder / "taasheera-backup.service").read_text()
    timer = (folder / "taasheera-backup.timer").read_text()
    assert "Persistent=true" in timer and "OnCalendar=" in timer
    assert "User=" not in service and "EnvironmentFile=/etc/taasheera/backup.env" in service
    assert "/opt/taasheera/backend/scripts/backup_tools.py backup" in service
    installer = (folder / "install-backup-timer.sh").read_text()
    # Deployments require a clean checkout, so the installer writes nothing inside it.
    assert "/opt/taasheera/" not in installer.replace("/opt/taasheera/deploy/aws/backup/install-backup-timer.sh", "")
    for text in (service, timer, installer):
        assert "AKIA" not in text and "SECRET" not in text


def test_restore_over_a_damaged_database_keeps_the_damaged_file_and_brings_the_backup_back(data, tmp_path):
    archive = backup_tools.create_backup(data, tmp_path / "out", NOW)
    (data / "taasheera.db").write_bytes(b"not a database at all")
    staging = tmp_path / "staging"
    backup_tools.verify_backup(archive, archive.with_name(archive.name + ".sha256"), staging)
    kept = backup_tools.restore_backup(data, staging, REPO, run=lambda command: None, now=NOW)
    assert emails(data / "taasheera.db") == ["kept@example.com"]
    assert (kept / "taasheera.db").read_bytes() == b"not a database at all"


def test_readiness_is_retried_and_a_failure_never_shows_the_origin_token(data, tmp_path):
    archive = backup_tools.create_backup(data, tmp_path / "out", NOW)

    def restore(failures):
        staging = tmp_path / f"staging-{failures}"
        backup_tools.verify_backup(archive, archive.with_name(archive.name + ".sha256"), staging)
        calls = []

        def run(command):
            calls.append(command[0])
            if command[0] == "curl" and calls.count("curl") <= failures:
                raise subprocess.CalledProcessError(7, command)
        backup_tools.restore_backup(data, staging, REPO, run=run, now=NOW + timedelta(seconds=failures),
                                    sleep=lambda seconds: None)
        return calls

    # nginx can need a moment after the containers report healthy.
    assert restore(3).count("curl") == 4
    with pytest.raises(backup_tools.BackupError) as failed:
        restore(99)
    assert "readiness check failed" in str(failed.value)
    assert "pre-restore-" in str(failed.value)
    assert "f" * 64 not in str(failed.value)


def test_hard_linked_files_back_up_as_plain_files_that_restore(data, tmp_path):
    original = data / "passports" / "1" / ("a" * 32)
    try:
        os.link(original, data / "passports" / "1" / ("b" * 32))
    except OSError:
        pytest.skip("No hard links on this file system.")
    archive = backup_tools.create_backup(data, tmp_path / "out", NOW)
    manifest = backup_tools.verify_backup(archive, archive.with_name(archive.name + ".sha256"), tmp_path / "staging")
    assert f"passports/1/{'b' * 32}" in manifest["files"]


def test_backup_checks_its_own_archive_and_rejects_keeping_none(data, tmp_path, capsys):
    with pytest.raises(SystemExit):
        backup_tools.main(["--data-dir", str(data), "--lock", str(tmp_path / "lock"), "backup", "--no-upload",
                           "--keep", "0"])
    out = data / "private" / "backups" / "scheduled"
    out.mkdir(parents=True)
    (out / "20261001T030000Z.tar.gz.partial").write_bytes(b"left by a killed run")
    assert backup_tools.main(["--data-dir", str(data), "--lock", str(tmp_path / "lock"), "backup", "--no-upload"]) == 0
    assert "created and checked" in capsys.readouterr().out
    assert not list(out.glob("*.partial"))
