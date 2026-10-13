import json
import os
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import manage
import migrate
from app.database import build_engine
from app.main import create_app
from app.models import ActivityEvent, GoogleIdentity, Traveler
from app.schema import schema_revision


PASSWORD = "Operator-test-password-123"
# Hashed once at a low cost to keep the module fast; bcrypt.checkpw accepts any cost.
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
MAYA = "maya@example.com"
OMAR = "omar@example.com"
SUSPENDED_NOTE = " It is suspended, so it cannot use admin tools until it is reactivated."


class SeededDatabase:
    def __init__(self, url, engine, activity_dir):
        self.url, self.engine, self.activity_dir = url, engine, activity_dir

    def roles(self):
        with Session(self.engine) as session:
            return {traveler.id: (traveler.role, traveler.status) for traveler in session.exec(select(Traveler))}

    def events(self):
        with Session(self.engine) as session:
            return [(event.traveler_id, event.event_type, event.identifier, event.outcome)
                    for event in session.exec(select(ActivityEvent))]

    def mirror(self):
        return "".join(path.read_text(encoding="utf-8") for path in sorted(self.activity_dir.rglob("*.jsonl")))


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'manage.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate.upgrade()
    engine = build_engine(url)
    with Session(engine) as session:
        session.add(Traveler(id=1, name="Maya", email=MAYA, password_hash=PASSWORD_HASH))
        session.add(Traveler(id=2, name="Omar", email=OMAR, password_hash=""))
        session.commit()
        session.add(GoogleIdentity(subject="google-subject-2", traveler_id=2))
        session.commit()
    yield SeededDatabase(url, engine, tmp_path / "activity-logs")
    engine.dispose()


def set_role(email, role):
    manage.main(["set-role", "--email", email, "--role", role])


def test_set_role_promotes_an_existing_account_and_records_the_change(database, capsys):
    set_role(MAYA, "admin")
    output = capsys.readouterr().out
    assert output == "Account 1 (password sign-in) role changed from traveler to admin.\n"
    assert database.roles()[1] == ("admin", "active")
    assert database.roles()[2] == ("traveler", "active")
    assert database.events() == [(1, "role_change", "cli:traveler->admin", "success")]
    lines = [json.loads(line) for line in database.mirror().splitlines()]
    assert [(line["traveler_id"], line["event_type"], line["identifier"], line["outcome"]) for line in lines] == [
        (1, "role_change", "cli:traveler->admin", "success")]
    assert (database.activity_dir / "1").is_dir()
    for text in (output, database.mirror()):
        assert MAYA not in text and "maya" not in text.lower()


def test_set_role_matches_email_regardless_of_case_and_spaces(database, capsys):
    set_role("  MAYA@Example.COM ", "support")
    assert "Account 1 (password sign-in) role changed from traveler to support." in capsys.readouterr().out
    assert database.roles()[1] == ("support", "active")


def test_set_role_promotes_google_only_accounts(database, capsys):
    set_role(OMAR, "admin")
    assert capsys.readouterr().out == "Account 2 (Google sign-in) role changed from traveler to admin.\n"
    assert database.roles()[2] == ("admin", "active")
    with TestClient(create_app(database.url)) as client:
        for password in ("", PASSWORD):
            assert client.post("/auth/login", json={"email": OMAR, "password": password}).status_code == 401


def test_set_role_is_a_no_op_when_unchanged(database, capsys):
    set_role(MAYA, "admin")
    capsys.readouterr()
    set_role(MAYA, "admin")
    assert capsys.readouterr().out == "Account 1 (password sign-in) already has the admin role; nothing changed.\n"
    assert database.events() == [(1, "role_change", "cli:traveler->admin", "success")]


def test_set_role_rejects_unknown_emails_without_changes(database, capsys):
    with pytest.raises(SystemExit) as refused:
        set_role("missing@example.com", "admin")
    assert refused.value.code == "No account uses that email. Sign up first, then run this command again."
    assert capsys.readouterr().out == ""
    assert database.events() == []
    assert set(database.roles().values()) == {("traveler", "active")}


def test_set_role_exits_with_status_1_and_a_message_on_stderr(database):
    # Runs the real command line once: SystemExit messages become exit status 1 on stderr.
    result = subprocess.run(
        [sys.executable, "manage.py", "set-role", "--email", "missing@example.com", "--role", "admin"],
        cwd=Path(manage.__file__).resolve().parent, env=os.environ.copy(),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "No account uses that email. Sign up first, then run this command again."
    assert database.events() == []


def test_set_role_rejects_invalid_emails(database):
    with pytest.raises(SystemExit) as refused:
        set_role("not-an-email", "admin")
    assert refused.value.code == "Enter a valid email address."
    assert database.events() == []


@pytest.mark.parametrize("role", ["Admin", " admin", "admin ", "superuser", ""])
def test_set_role_accepts_only_exact_role_names(database, role):
    with pytest.raises(SystemExit) as refused:
        set_role(MAYA, role)
    assert refused.value.code == 2
    assert set(database.roles().values()) == {("traveler", "active")}
    assert database.events() == []


@pytest.mark.parametrize("argv", [
    ["set-role", "--email", MAYA, "--role", "admin", "--password", "x"],
    ["--email", MAYA, "--role", "admin"],
    [],
])
def test_set_role_has_no_password_option_and_needs_a_command(database, argv):
    with pytest.raises(SystemExit) as refused:
        manage.main(argv)
    assert refused.value.code == 2
    assert set(database.roles().values()) == {("traveler", "active")}


@pytest.mark.parametrize("argv", [
    ["set-role", "--em", MAYA, "--role", "admin"],
    ["set-role", "--email", MAYA, "--ro", "admin"],
])
def test_set_role_rejects_abbreviated_options(database, argv):
    with pytest.raises(SystemExit) as refused:
        manage.main(argv)
    assert refused.value.code == 2
    assert set(database.roles().values()) == {("traveler", "active")}


@pytest.mark.parametrize("argv", [
    ["set-role", "--email", MAYA, "--role", "admin", "--password", "Typed-By-Mistake-123"],
    ["--password", "Typed-By-Mistake-123", "set-role", "--email", MAYA, "--role", "admin"],
    ["Typed-By-Mistake-123"],
])
def test_set_role_does_not_echo_unrecognized_arguments(database, capsys, argv):
    with pytest.raises(SystemExit) as refused:
        manage.main(argv)
    assert refused.value.code == 2
    assert "Typed-By-Mistake-123" not in capsys.readouterr().err
    assert set(database.roles().values()) == {("traveler", "active")}


def test_failed_audit_event_leaves_the_role_unchanged(database, monkeypatch):
    def failing_record_activity(*args, **kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(manage, "record_activity", failing_record_activity)
    with pytest.raises(RuntimeError, match="audit store unavailable"):
        set_role(MAYA, "admin")
    # The role change and its audit event commit together or not at all.
    assert database.roles()[1] == ("traveler", "active")
    assert database.events() == []


@pytest.mark.parametrize("path", ["missing.db", "missing-folder/manage.db"])
def test_set_role_refuses_a_missing_sqlite_file_without_creating_it(tmp_path, monkeypatch, path):
    target = tmp_path / path
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target.as_posix()}")
    with pytest.raises(SystemExit) as refused:
        set_role(MAYA, "admin")
    assert refused.value.code.startswith("No database file at that path. Check DATABASE_URL")
    assert not target.exists()


def test_set_role_reports_an_invalid_activity_log_directory(database, monkeypatch):
    monkeypatch.setenv("ACTIVITY_LOG_DIR", "relative/activity-logs")
    with pytest.raises(SystemExit) as refused:
        set_role(MAYA, "admin")
    assert refused.value.code == "ACTIVITY_LOG_DIR must be an absolute directory path."
    assert database.roles()[1] == ("traveler", "active")


def test_set_role_refuses_an_unmigrated_database(sprint1_database):
    with pytest.raises(SystemExit) as refused:
        set_role(MAYA, "admin")
    assert refused.value.code == "Database schema is not current. Run 'python migrate.py upgrade' first."
    engine = build_engine(sprint1_database)
    try:
        assert schema_revision(engine)[0] is None
    finally:
        engine.dispose()


def test_cli_role_changes_apply_to_the_next_api_request(database, capsys):
    with TestClient(create_app(database.url)) as client:
        login = client.post("/auth/login", json={"email": MAYA, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/admin/me", headers=headers).status_code == 403
        set_role(MAYA, "admin")
        assert client.get("/admin/me", headers=headers).status_code == 200
        set_role(MAYA, "traveler")
        assert client.get("/admin/me", headers=headers).status_code == 403
    assert [event for event in database.events() if event[1] == "role_change"] == [
        (1, "role_change", "cli:traveler->admin", "success"), (1, "role_change", "cli:admin->traveler", "success")]


def test_set_role_on_a_suspended_account_warns_it_cannot_use_admin_tools(database, capsys):
    with Session(database.engine) as session:
        maya = session.get(Traveler, 1)
        maya.status = "suspended"
        session.add(maya)
        session.commit()
    set_role(MAYA, "admin")
    assert capsys.readouterr().out == (
        "Account 1 (password sign-in) role changed from traveler to admin." + SUSPENDED_NOTE + "\n")
    assert database.roles()[1] == ("admin", "suspended")
    set_role(MAYA, "admin")
    assert capsys.readouterr().out == (
        "Account 1 (password sign-in) already has the admin role; nothing changed." + SUSPENDED_NOTE + "\n")
    set_role(MAYA, "traveler")
    assert capsys.readouterr().out == "Account 1 (password sign-in) role changed from admin to traveler.\n"
    assert database.roles()[1] == ("traveler", "suspended")


def test_concurrent_role_changes_keep_an_accurate_audit_trail(database):
    # SQLite has no FOR UPDATE; the command's no-op UPDATE takes the write lock instead.
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda role: manage.set_role(MAYA, role), ["admin", "support", "traveler"] * 4))
    changes = [identifier.removeprefix("cli:").split("->") for _, _, identifier, _ in database.events()]
    assert changes and changes[0][0] == "traveler" and changes[-1][1] == database.roles()[1][0]
    assert all(earlier[1] == later[0] for earlier, later in zip(changes, changes[1:]))
