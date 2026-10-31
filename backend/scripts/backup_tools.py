#!/usr/bin/env python3
"""Back up and restore the live SQLite database and passport files (US 126).

Runs on the AWS host, outside the containers, as root from a systemd timer
(deploy/aws/backup/). The host's Python is 3.9 and has nothing installed, so
this file uses the standard library only and must stay 3.9-compatible;
uploads go through the AWS CLI with the instance role's credentials.

A backup is one private .tar.gz with a consistent copy of the database (SQLite's
online backup, so the API keeps running), the passport images, the activity log
mirrors and a manifest with checksums. The secrets in private/ (app.env) are
never included. Restore checks the checksum and the database before it touches
anything, keeps the current data aside, then migrates and checks readiness.
See docs/BACKUPS.md.

    python3 backup_tools.py backup  [--data-dir /srv/taasheera] [--keep 7]
    python3 backup_tools.py restore (--latest | --key db/<name> | --archive <file>) [--yes]
"""

from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

DATABASE = "taasheera.db"
# What a backup holds, relative to the data directory. Never private/ (JWT secret, origin token).
FOLDERS = ("passports", "activity-logs")
PREFIX = "db/"
SUFFIX = ".tar.gz"
# Only names the timer writes count for --latest, so a hand-named upload can't win by sorting last.
SCHEDULED_KEY = re.compile(r"^db/\d{8}T\d{6}Z\.tar\.gz$")
LOCK = Path("/run/taasheera-backup.lock")
COUNTED_TABLES = ("traveler", "application", "applicationanswer")

Runner = Callable[[Sequence[str]], None]


class BackupError(Exception):
    """Something is wrong with a backup, the place it goes, or a restore step. The message says which."""


class StepFailed(BackupError):
    """A command failed. Only the step is named: the command line can hold the origin token."""

    def __init__(self, step: str, code: int) -> None:
        super().__init__(f"{step} failed (exit {code}).")


def run_command(command: Sequence[str]) -> None:
    subprocess.run(list(command), check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_database(path: Path) -> Dict[str, Optional[object]]:
    """Fail unless SQLite says the file is sound; return its schema revision and row counts."""
    try:
        # closing(): a connection's own `with` only commits, and an open file can't be replaced on Windows.
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as database:
            result = database.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise BackupError("The database copy failed SQLite's integrity check.")
            tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            revision = None
            if "alembic_version" in tables:
                row = database.execute("SELECT version_num FROM alembic_version").fetchone()
                revision = row[0] if row else None
            counts = {table: database.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                      for table in COUNTED_TABLES if table in tables}
    except sqlite3.DatabaseError as error:
        raise BackupError(f"The database copy can't be read: {error}") from None
    return {"revision": revision, "counts": counts}


def snapshot_database(source: Path, destination: Path) -> None:
    # The online backup API copies a consistent snapshot even while the API writes; a file copy could tear.
    with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as database:
        with closing(sqlite3.connect(destination)) as copy:
            database.backup(copy)
    os.chmod(destination, 0o600)


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _needed_space(data_dir: Path) -> int:
    total = (data_dir / DATABASE).stat().st_size if (data_dir / DATABASE).is_file() else 0
    for folder in FOLDERS:
        for path in (data_dir / folder).rglob("*") if (data_dir / folder).is_dir() else []:
            if path.is_file():
                total += path.stat().st_size
    return total


def _check_space(directory: Path, needed: int) -> None:
    # Twice the data: the staged copy and the archive both exist for a moment.
    if shutil.disk_usage(directory).free < 2 * needed + (64 << 20):
        raise BackupError("Not enough free disk space for a backup copy.")


def create_backup(data_dir: Path, out_dir: Path, now: Optional[datetime] = None) -> Path:
    """Write <timestamp>.tar.gz and its .sha256 into out_dir and return the archive's path."""
    database = data_dir / DATABASE
    if not database.is_file():
        raise BackupError(f"No database at {database}. Only the SQLite deployment is supported.")
    os.umask(0o077)
    _private_directory(out_dir)
    _check_space(out_dir, _needed_space(data_dir))
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    archive = out_dir / f"{stamp}{SUFFIX}"
    if archive.exists():
        raise BackupError(f"A backup named {archive.name} already exists.")

    with tempfile.TemporaryDirectory(dir=out_dir) as staging:
        copy = Path(staging) / DATABASE
        # The database first: a passport file added after it is harmless, a missing one would not be.
        snapshot_database(database, copy)
        details = check_database(copy)
        files = {DATABASE: sha256(copy)}
        # Copied first and archived from the copies: a log appended mid-backup then still matches its
        # checksum, and hard links become plain files.
        for folder in FOLDERS:
            root = data_dir / folder
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                name = path.relative_to(data_dir).as_posix()
                if not path.is_file() or path.is_symlink():
                    continue
                target = Path(staging) / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                try:
                    shutil.copyfile(path, target)
                except FileNotFoundError:
                    continue  # removed while we walked the folder: nothing to keep
                files[name] = sha256(target)
        partial = archive.with_name(archive.name + ".partial")
        with tarfile.open(partial, "w:gz") as tar:
            for name in files:
                tar.add(Path(staging) / name, arcname=name, recursive=False)
            manifest = json.dumps({
                "created_at": stamp, "database": "sqlite", "revision": details["revision"],
                "counts": details["counts"], "files": files,
            }, indent=2, sort_keys=True).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size, info.mode = len(manifest), 0o600
            tar.addfile(info, io.BytesIO(manifest))
        os.chmod(partial, 0o600)
        os.replace(partial, archive)
    checksum = archive.with_name(archive.name + ".sha256")
    checksum.write_text(f"{sha256(archive)}  {archive.name}\n")
    os.chmod(checksum, 0o600)
    return archive


def prune(directory: Path, keep: int) -> List[Path]:
    """Keep the newest `keep` archives (names sort by time) and their checksums; return what was removed."""
    if keep < 1:
        raise BackupError("Keep at least one backup.")
    for leftover in directory.glob(f"*{SUFFIX}.partial"):
        leftover.unlink()  # from a run that was killed mid-way
    archives = sorted(directory.glob(f"*{SUFFIX}"))
    removed = archives[:-keep]
    for archive in removed:
        archive.unlink()
        archive.with_name(archive.name + ".sha256").unlink(missing_ok=True)
    return removed


# --- Where backups go -----------------------------------------------------------


class AwsCliUploader:
    """A private S3 bucket, through the AWS CLI and the host's instance role. No keys on disk."""

    def __init__(self, bucket: str, run: Runner = run_command,
                 output: Optional[Callable[[Sequence[str]], str]] = None) -> None:
        if not bucket or "/" in bucket:
            raise BackupError("Set TAASHEERA_BACKUP_BUCKET to the backup bucket's name.")
        self.bucket, self.run = bucket, run
        self.output = output or (lambda command: subprocess.run(list(command), check=True, capture_output=True,
                                                                  text=True).stdout)

    def upload(self, path: Path, key: str) -> None:
        self.run(["aws", "s3", "cp", str(path), f"s3://{self.bucket}/{key}", "--sse", "AES256", "--only-show-errors"])

    def download(self, key: str, destination: Path) -> None:
        self.run(["aws", "s3", "cp", f"s3://{self.bucket}/{key}", str(destination), "--only-show-errors"])

    def keys(self) -> List[str]:
        text = self.output(["aws", "s3api", "list-objects-v2", "--bucket", self.bucket, "--prefix", PREFIX,
                            "--query", "Contents[].Key", "--output", "json"])
        return [key for key in (json.loads(text) or []) if SCHEDULED_KEY.match(key)]


class LocalDirUploader:
    """A folder standing in for the bucket, for tests and for a rehearsal without AWS."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def upload(self, path: Path, key: str) -> None:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def download(self, key: str, destination: Path) -> None:
        shutil.copyfile(self.root / key, destination)

    def keys(self) -> List[str]:
        keys = (path.relative_to(self.root).as_posix() for path in (self.root / PREFIX).glob("*"))
        return sorted(key for key in keys if SCHEDULED_KEY.match(key))


def upload_backup(uploader, archive: Path) -> str:
    key = PREFIX + archive.name
    uploader.upload(archive, key)
    uploader.upload(archive.with_name(archive.name + ".sha256"), key + ".sha256")
    return key


# --- Restore ----------------------------------------------------------------------


def _safe_members(tar: tarfile.TarFile) -> List[tarfile.TarInfo]:
    allowed = {DATABASE, "manifest.json"}
    members = []
    for member in tar.getmembers():
        path = Path(member.name)
        top = path.parts[0] if path.parts else ""
        if (path.is_absolute() or ".." in path.parts or not member.isfile()
                or (member.name not in allowed and top not in FOLDERS)):
            raise BackupError("The backup contains an unexpected entry; refusing to extract it.")
        members.append(member)
    return members


def verify_backup(archive: Path, checksum: Path, staging: Path) -> Dict[str, object]:
    """Check the archive against its checksum, unpack it into `staging` and check every file. Returns the manifest."""
    expected = checksum.read_text().split()[0] if checksum.is_file() else ""
    if expected != sha256(archive):
        raise BackupError("The backup's checksum doesn't match; it may be incomplete or damaged.")
    _private_directory(staging)
    with tarfile.open(archive, "r:gz") as tar:
        members = _safe_members(tar)
        for member in members:
            target = staging / member.name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tar.extractfile(member) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            os.chmod(target, 0o600)
    manifest_path = staging / "manifest.json"
    if not manifest_path.is_file() or not (staging / DATABASE).is_file():
        raise BackupError("The backup has no manifest or no database.")
    manifest = json.loads(manifest_path.read_text())
    for name, digest in manifest["files"].items():
        if not (staging / name).is_file() or sha256(staging / name) != digest:
            raise BackupError("A file in the backup doesn't match its manifest.")
    check_database(staging / DATABASE)
    return manifest


def _compose(repo: Path, *arguments: str) -> List[str]:
    return ["docker", "compose", "-f", str(repo / "deploy" / "aws" / "compose.yaml"), *arguments]


def _origin_token(data_dir: Path) -> str:
    for line in (data_dir / "private" / "app.env").read_text().splitlines():
        if line.startswith("ORIGIN_TOKEN="):
            return line.split("=", 1)[1]
    raise BackupError("No ORIGIN_TOKEN in private/app.env, so readiness can't be checked.")


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    if not hasattr(os, "chown"):
        return
    os.chown(path, uid, gid)
    for child in path.rglob("*"):
        os.chown(child, uid, gid)


def _step(run: Runner, step: str, command: Sequence[str]) -> None:
    try:
        run(command)
    except subprocess.CalledProcessError as error:
        raise StepFailed(step, error.returncode) from None


def _wait_until_ready(run: Runner, token: str, attempts: int = 10, pause: float = 3.0,
                      sleep: Callable[[float], None] = time.sleep) -> None:
    # The web container has no health check of its own, so nginx may need a moment after `up --wait`.
    command = ["curl", "--fail", "--silent", "--show-error", "--max-time", "5",
               "-H", f"X-Taasheera-Origin: {token}", "http://127.0.0.1/health/ready"]
    for attempt in range(attempts):
        try:
            run(command)
            return
        except subprocess.CalledProcessError as error:
            if attempt == attempts - 1:
                raise StepFailed("The readiness check", error.returncode) from None
            sleep(pause)


def restore_backup(data_dir: Path, staging: Path, repo: Path, run: Runner = run_command,
                   now: Optional[datetime] = None, sleep: Callable[[float], None] = time.sleep) -> Path:
    """Swap the verified backup in `staging` into place. Returns where the replaced data was kept.

    The site is down from "stop" until the containers report healthy again. If a step after the
    swap fails, the error says which and where the old data is (docs/BACKUPS.md, "If a restore fails").
    """
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    kept = _private_directory(data_dir / "private" / f"pre-restore-{stamp}")
    owner = data_dir.stat()
    token = _origin_token(data_dir)  # read before anything stops
    _step(run, "Stopping the containers", _compose(repo, "stop", "web", "api"))
    live = data_dir / DATABASE
    # Kept, not deleted, so anything written since the backup can still be recovered by hand. A plain
    # copy, not SQLite's backup: the API is stopped, and a damaged database (the usual reason to
    # restore) can't be opened at all.
    for name in (DATABASE, f"{DATABASE}-journal", f"{DATABASE}-wal", f"{DATABASE}-shm"):
        if (data_dir / name).is_file():
            shutil.copy2(data_dir / name, kept / name)
            if name != DATABASE:
                (data_dir / name).unlink()
    os.replace(staging / DATABASE, live)
    for folder in FOLDERS:
        if (data_dir / folder).exists():
            os.replace(data_dir / folder, kept / folder)
        if (staging / folder).exists():
            os.replace(staging / folder, data_dir / folder)
        else:
            (data_dir / folder).mkdir()
    for path in [live] + [data_dir / folder for folder in FOLDERS]:
        if path.is_dir():
            _chown_tree(path, owner.st_uid, owner.st_gid)
        elif hasattr(os, "chown"):
            os.chown(path, owner.st_uid, owner.st_gid)
    try:
        # A backup from an older schema is brought up to date before the API starts.
        _step(run, "The migration", _compose(repo, "run", "--rm", "migrate"))
        _step(run, "Starting the containers", _compose(repo, "up", "-d", "--wait", "--wait-timeout", "180"))
        _wait_until_ready(run, token, sleep=sleep)
    except StepFailed as error:
        raise BackupError(f"{error} The backup is in place; the replaced data is in {kept}.") from None
    return kept


@contextmanager
def _single_run(lock: Path):
    """One backup or restore at a time: the timer must not fire in the middle of a restore."""
    try:
        import fcntl
    except ImportError:  # Windows, in development: nothing else runs these there
        yield
        return
    with open(lock, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError("Another backup or restore is running.") from None
        yield


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("keep at least one backup")
    return number


# --- Command line -------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Back up or restore Ta'asheera's database and passport files.")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("TAASHEERA_DATA_DIR", "/srv/taasheera")))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--lock", type=Path, default=LOCK, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Make a backup and upload it to the private bucket.")
    backup.add_argument("--keep", type=_positive, default=7, help="Archives to keep on the host (default 7).")
    backup.add_argument("--no-upload", action="store_true", help="Keep the backup on the host only.")
    restore = commands.add_parser("restore", help="Check a backup and, with --yes, put it in place.")
    which = restore.add_mutually_exclusive_group(required=True)
    which.add_argument("--latest", action="store_true")
    which.add_argument("--key", help="A bucket key such as db/20261031T030000Z.tar.gz")
    which.add_argument("--archive", type=Path, help="A local archive (its .sha256 must sit beside it).")
    restore.add_argument("--yes", action="store_true", help="Really replace the live data (the site goes down briefly).")
    args = parser.parse_args(argv)

    try:
        with _single_run(args.lock):
            return _backup(args) if args.command == "backup" else _restore(args)
    except subprocess.CalledProcessError as error:
        # Never the command line itself, which can hold the origin token.
        print(f"Backup tool failed: {Path(str(error.cmd[0])).name} exited {error.returncode}.", file=sys.stderr)
    except OSError as error:
        # The reason only: paths under passports/ contain traveler ids.
        print(f"Backup tool failed: {error.strerror or type(error).__name__}.", file=sys.stderr)
    except (BackupError, sqlite3.Error) as error:
        print(f"Backup tool failed: {error}", file=sys.stderr)
    return 1


def _backup(args) -> int:
    # Checked first, so a missing bucket setting fails before any work is done.
    uploader = None if args.no_upload else AwsCliUploader(os.environ.get("TAASHEERA_BACKUP_BUCKET", ""))
    archive = create_backup(args.data_dir, args.data_dir / "private" / "backups" / "scheduled")
    # Restorable before it counts: unpacked and checked once, as a restore would.
    with tempfile.TemporaryDirectory(dir=archive.parent) as check:
        verify_backup(archive, archive.with_name(archive.name + ".sha256"), Path(check) / "staging")
    if uploader:
        print(f"Uploaded {upload_backup(uploader, archive)}")
    prune(archive.parent, args.keep)
    print(f"Backup {archive.name} created and checked.")
    return 0


def _restore(args) -> int:
    work = _private_directory(args.data_dir / "private" / "restore")
    downloaded: List[Path] = []
    if args.archive:
        archive, checksum = args.archive, args.archive.with_name(args.archive.name + ".sha256")
    else:
        uploader = AwsCliUploader(os.environ.get("TAASHEERA_BACKUP_BUCKET", ""))
        key = args.key or max(uploader.keys(), default="")
        if not key:
            raise BackupError("No backup found in the bucket.")
        if not key.startswith(PREFIX) or not key.endswith(SUFFIX) or ".." in key:
            raise BackupError("Give a key like db/<name>.tar.gz.")
        archive, checksum = work / Path(key).name, work / (Path(key).name + ".sha256")
        downloaded = [archive, checksum]
        uploader.download(key, archive)
        uploader.download(key + ".sha256", checksum)
    staging = Path(tempfile.mkdtemp(prefix="staging-", dir=work))
    try:
        _check_space(work, archive.stat().st_size * 3)
        manifest = verify_backup(archive, checksum, staging)
        print(f"Backup {archive.name} is sound: schema {manifest['revision']}, rows {manifest['counts']}.")
        if not args.yes:
            print("Nothing changed. Run again with --yes to put it in place.")
            return 0
        kept = restore_backup(args.data_dir, staging, args.repo)
        print(f"Restored and ready. The replaced data is kept in {kept}.")
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        for path in downloaded:
            path.unlink(missing_ok=True)

if __name__ == "__main__":
    sys.exit(main())
