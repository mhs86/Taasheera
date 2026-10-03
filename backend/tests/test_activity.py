import json
from io import BytesIO

from fastapi.testclient import TestClient
import pytest
from PIL import Image
from sqlmodel import Session, select

from app.main import create_app
from app.models import ActivityEvent
from app.passport.extraction import Extraction, ExtractionStatus


PASSWORD = "private-password-123"


def events(app):
    with Session(app.state.engine) as session:
        return session.exec(select(ActivityEvent).order_by(ActivityEvent.id)).all()


def test_auth_outcomes_are_owned_and_mirrored_without_credentials(tmp_path, monkeypatch):
    directory = tmp_path / "activity-logs"
    monkeypatch.setenv("ACTIVITY_LOG_DIR", str(directory))
    app = create_app(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    with TestClient(app) as client:
        assert client.post("/auth/register", json={"name": "Maya", "email": "maya@example.com",
                                                   "password": PASSWORD}).status_code == 201
        assert client.post("/auth/login", json={"email": "maya@example.com",
                                                "password": "wrong"}).status_code == 401
        login = client.post("/auth/login", json={"email": "maya@example.com",
                                                 "password": PASSWORD})
        assert login.status_code == 200
        assert client.post("/auth/logout").status_code == 204

    rows = events(app)
    assert [(row.traveler_id, row.event_type, row.identifier, row.outcome) for row in rows] == [
        (1, "registration", "email_password", "success"),
        (1, "sign_in", "email_password", "failure"),
        (1, "sign_in", "email_password", "success"),
        (1, "logout", "session", "success"),
    ]
    lines = [json.loads(line) for path in (directory / "1").glob("*.jsonl") for line in path.read_text().splitlines()]
    assert len(lines) == 4
    assert {line["id"] for line in lines} == {row.id for row in rows}
    assert all(line["occurred_at"].endswith("+00:00") for line in lines)
    assert PASSWORD not in json.dumps(lines)
    assert login.json()["access_token"] not in json.dumps(lines)
    assert "maya@example.com" not in json.dumps(lines)


def test_frontend_events_use_bearer_owner_and_reject_free_text(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVITY_LOG_DIR", str(tmp_path / "activity-logs"))
    app = create_app(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    with TestClient(app) as client:
        headers = []
        for email in ("one@example.com", "two@example.com"):
            client.cookies.clear()  # Separate browser sessions; a new login replaces the same cookie.
            assert client.post("/auth/register", json={"name": "Traveler", "email": email,
                                                       "password": PASSWORD}).status_code == 201
            token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
            headers.append({"Authorization": f"Bearer {token}"})
        payload = {"event_type": "page_visit", "page": "faq", "outcome": "visited"}
        assert client.post("/activity/events", json=payload).status_code == 401
        assert client.post("/activity/events", json=payload, headers=headers[0]).status_code == 204
        assert client.post("/activity/events", json={"event_type": "click", "page": "faq",
                                                      "control": "faq-question", "outcome": "initiated"},
                           headers=headers[1]).status_code == 204
        for invalid in (
            {**payload, "traveler_id": 2},
            {**payload, "page": "/reset-password#token=secret"},
            {**payload, "control": "email"},
            {"event_type": "click", "page": "faq", "control": "password",
             "outcome": "initiated"},
            {"event_type": "click", "page": "faq", "control": "faq-question",
             "outcome": "visited"},
        ):
            assert client.post("/activity/events", json=invalid, headers=headers[0]).status_code == 422
        assert client.post("/activity/events", json=payload, headers={**headers[0],
                            "Origin": "https://untrusted.example"}).status_code == 403

    frontend_rows = [row for row in events(app) if row.event_type in {"page_visit", "click"}]
    assert [(row.traveler_id, row.event_type, row.identifier) for row in frontend_rows] == [
        (1, "page_visit", "faq"), (2, "click", "faq:faq-question"),
    ]
    assert len(list((tmp_path / "activity-logs" / "1").glob("*.jsonl"))) == 1
    assert len(list((tmp_path / "activity-logs" / "2").glob("*.jsonl"))) == 1


def test_passport_action_logs_status_without_image_or_mrz(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVITY_LOG_DIR", str(tmp_path / "activity-logs"))
    monkeypatch.setenv("PASSPORT_STORAGE_DIR", str(tmp_path / "passports"))
    monkeypatch.setattr("app.passport.router.extract_passport",
                        lambda image, reader: Extraction(status=ExtractionStatus.UNREADABLE))
    app = create_app(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    image = BytesIO()
    Image.new("RGB", (400, 300), "white").save(image, format="JPEG")
    with TestClient(app) as client:
        client.post("/auth/register", json={"name": "Maya", "email": "maya@example.com", "password": PASSWORD})
        token = client.post("/auth/login", json={"email": "maya@example.com",
                                                 "password": PASSWORD}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post("/passports", files={"file": ("bad.jpg", b"bad", "image/jpeg")},
                           headers=headers).status_code == 422
        upload = client.post("/passports", files={"file": ("passport.jpg", image.getvalue(), "image/jpeg")},
                             headers=headers)
        assert upload.status_code == 201
        assert client.post(f"/passports/{upload.json()['id']}/extract", headers=headers).json()["status"] == "unreadable"

    passport_rows = [row for row in events(app) if row.event_type.startswith("passport_")]
    assert [(row.event_type, row.outcome) for row in passport_rows] == [
        ("passport_upload", "failure"), ("passport_upload", "success"),
        ("passport_extraction", "unreadable"),
    ]
    log_text = "".join(path.read_text() for path in (tmp_path / "activity-logs" / "1").glob("*.jsonl"))
    assert upload.json()["id"] not in log_text
    assert PASSWORD not in log_text


def test_google_sign_in_and_account_creation_are_recorded_without_credential(tmp_path, monkeypatch):
    directory = tmp_path / "activity-logs"
    monkeypatch.setenv("ACTIVITY_LOG_DIR", str(directory))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
    monkeypatch.setattr("app.google_auth.verify_google_token", lambda raw, client_id: {
        "sub": "verified-subject", "email": "google@example.com", "name": "Google Traveler",
    })
    app = create_app(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    with TestClient(app) as client:
        for _ in range(2):
            assert client.post("/auth/google", json={"id_token": "private-google-credential"}).status_code == 200
    assert [(row.event_type, row.identifier, row.outcome) for row in events(app)] == [
        ("registration", "google", "success"),
        ("sign_in", "google", "success"),
        ("sign_in", "google", "success"),
    ]
    log_text = "".join(path.read_text() for path in (directory / "1").glob("*.jsonl"))
    assert "private-google-credential" not in log_text


def test_invalid_activity_directory_fails_at_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVITY_LOG_DIR", "relative/activity-logs")
    app = create_app(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    with pytest.raises(RuntimeError, match="ACTIVITY_LOG_DIR"):
        with TestClient(app):
            pass
