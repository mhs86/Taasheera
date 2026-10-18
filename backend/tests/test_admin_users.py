"""US 133: the admin user-management API and what suspension does to sign-in."""

import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.admin_api as admin_api
from app.admin_api import FORBIDDEN
from app.auth import COOKIE_NAME
from app.main import create_app
from app.models import ActivityEvent, AuthSession, GoogleIdentity, Traveler


PASSWORD = "Staff-password-123"
# Hashed once at a low cost to keep the module fast; bcrypt.checkpw accepts any cost.
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
CLIENT_ID = "test-web-client.apps.googleusercontent.com"
SUSPENDED = {"detail": {"code": "account_suspended", "message": "This account is suspended."}}
ORIGIN = {"Origin": "http://127.0.0.1:5173"}
# Field names that would mean passport or profile data leaked into an admin response.
PASSPORT_WORDS = ("passport", "mrz", "document", "birth", "nationality", "surname", "given", "expiry",
                  "sex", "address", "phone", "upload_id", "image", "review")
DETAIL_FIELDS = {"id", "name", "email", "auth_type", "role", "status", "created_at", "last_sign_in_at",
                 "sso_email", "password_enabled", "google_linked", "last_sign_in_method", "counts"}
SUMMARY_FIELDS = {"id", "name", "email", "auth_type", "role", "status", "created_at", "last_sign_in_at"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("PASSPORT_STORAGE_DIR", str(tmp_path / "passports"))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    app = create_app(f"sqlite:///{(tmp_path / 'users.db').as_posix()}")
    with TestClient(app) as client:
        ids = {}
        with Session(app.state.engine) as session:
            for key, name, email, role in [
                ("admin", "Adam Admin", "adam@example.com", "admin"),
                ("other_admin", "Rana Admin", "rana@example.com", "admin"),
                ("maya", "Maya Haddad", "maya@example.com", "traveler"),
                ("omar", "Omar Khalil", "omar@example.com", "traveler"),
                ("sara", "Sara 100%_Real", "sara@example.com", "support"),
            ]:
                traveler = Traveler(name=name, email=email, password_hash=PASSWORD_HASH, role=role)
                session.add(traveler)
                session.commit()
                ids[key] = traveler.id
        state = SimpleNamespace(client=client, app=app, ids=ids, storage=tmp_path / "passports",
                                activity=tmp_path / "activity-logs")
        state.admin = bearer(login(state, "adam@example.com"))
        yield state


def login(api, email, password=PASSWORD):
    api.client.cookies.clear()
    response = api.client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}", **ORIGIN}


def traveler(api, key):
    with Session(api.app.state.engine) as session:
        return session.get(Traveler, api.ids[key])


def events(api, traveler_id=None):
    with Session(api.app.state.engine) as session:
        query = select(ActivityEvent).order_by(ActivityEvent.id)
        if traveler_id is not None:
            query = query.where(ActivityEvent.traveler_id == traveler_id)
        return [(event.traveler_id, event.event_type, event.identifier, event.outcome)
                for event in session.exec(query)]


def active_sessions(api, traveler_id):
    with Session(api.app.state.engine) as session:
        return len(session.exec(select(AuthSession).where(
            AuthSession.traveler_id == traveler_id, AuthSession.revoked.is_(False))).all())


def suspend(api, key, headers=None):
    return api.client.post(f"/admin/users/{api.ids[key]}/suspend", headers=headers or api.admin)


def reactivate(api, key, headers=None):
    return api.client.post(f"/admin/users/{api.ids[key]}/reactivate", headers=headers or api.admin)


def set_role(api, key, role, headers=None):
    return api.client.put(f"/admin/users/{api.ids[key]}/role", json={"role": role}, headers=headers or api.admin)


def admin_events(api):
    return [event for event in events(api) if event[1] in {"status_change", "role_change"}]


# --- Suspension and sign-in (CMPS271-200) -----------------------------------------------------

def test_suspension_ends_every_session_and_blocks_password_sign_in(api):
    tokens = [login(api, "maya@example.com") for _ in range(2)]
    api.client.cookies.clear()
    refresh_cookie = api.client.post("/auth/login", json={"email": "maya@example.com", "password": PASSWORD}).cookies[COOKIE_NAME]
    assert active_sessions(api, api.ids["maya"]) == 3
    signed_in_at = traveler(api, "maya").last_login_at

    assert suspend(api, "maya").status_code == 200
    assert active_sessions(api, api.ids["maya"]) == 0
    for token in tokens:
        assert api.client.get("/auth/me", headers=bearer(token)).status_code == 401
    api.client.cookies.clear()
    api.client.cookies.set(COOKIE_NAME, refresh_cookie, path="/auth")
    assert api.client.post("/auth/refresh").status_code == 401
    api.client.cookies.clear()

    # The right password learns of the suspension; a wrong one gets the usual answer.
    wrong = api.client.post("/auth/login", json={"email": "maya@example.com", "password": "Wrong-password-1"})
    assert (wrong.status_code, wrong.json()) == (401, {"detail": "Invalid email or password."})
    refused = api.client.post("/auth/login", json={"email": "maya@example.com", "password": PASSWORD})
    assert (refused.status_code, refused.json()) == (403, SUSPENDED)
    assert refused.headers["cache-control"] == "no-store"
    assert COOKIE_NAME not in refused.cookies
    assert active_sessions(api, api.ids["maya"]) == 0
    assert traveler(api, "maya").last_login_at == signed_in_at
    assert events(api, api.ids["maya"])[-2:] == [
        (api.ids["maya"], "sign_in", "email_password", "failure"),
        (api.ids["maya"], "sign_in", "email_password", "suspended")]

    assert reactivate(api, "maya").status_code == 200
    assert api.client.get("/auth/me", headers=bearer(login(api, "maya@example.com"))).status_code == 200


def test_suspended_accounts_cannot_sign_in_with_google(api, monkeypatch):
    monkeypatch.setattr("app.google_auth.id_token.verify_oauth2_token", Mock(return_value={
        "iss": "https://accounts.google.com", "aud": CLIENT_ID, "exp": int(time.time()) + 3600,
        "sub": "google-subject-omar", "email": "omar@example.com", "email_verified": True, "name": "Omar",
    }))
    with Session(api.app.state.engine) as session:
        session.add(GoogleIdentity(subject="google-subject-omar", traveler_id=api.ids["omar"]))
        session.commit()
    api.client.cookies.clear()
    assert api.client.post("/auth/google", json={"id_token": "test-google-token"}).status_code == 200
    assert suspend(api, "omar").status_code == 200
    api.client.cookies.clear()
    refused = api.client.post("/auth/google", json={"id_token": "test-google-token"})
    assert (refused.status_code, refused.json()) == (403, SUSPENDED)
    assert active_sessions(api, api.ids["omar"]) == 0
    assert events(api, api.ids["omar"])[-1] == (api.ids["omar"], "sign_in", "google", "suspended")


def test_a_status_set_outside_the_api_still_signs_the_account_out(api):
    # An operator editing the row directly does not revoke sessions; the token check still refuses them.
    token = login(api, "maya@example.com")
    api.client.cookies.clear()
    refresh_cookie = api.client.post("/auth/login", json={"email": "maya@example.com", "password": PASSWORD}).cookies[COOKIE_NAME]
    api.client.cookies.clear()
    with Session(api.app.state.engine) as session:
        maya = session.get(Traveler, api.ids["maya"])
        maya.status = "suspended"
        session.add(maya)
        session.commit()
    assert api.client.get("/auth/me", headers=bearer(token)).status_code == 401
    assert api.client.get("/profile", headers=bearer(token)).status_code == 401
    # Reactivating must not bring those sessions back: they end, and the account signs in afresh.
    assert reactivate(api, "maya").status_code == 200
    assert api.client.get("/auth/me", headers=bearer(token)).status_code == 401
    api.client.cookies.set(COOKIE_NAME, refresh_cookie, path="/auth")
    assert api.client.post("/auth/refresh").status_code == 401
    api.client.cookies.clear()
    assert active_sessions(api, api.ids["maya"]) == 0
    assert api.client.get("/auth/me", headers=bearer(login(api, "maya@example.com"))).status_code == 200


# --- Users list (CMPS271-198) ------------------------------------------------------------------

def test_users_list_is_newest_first_and_paginated(api):
    first = api.client.get("/admin/users", params={"page_size": 2}, headers=api.admin)
    assert first.status_code == 200
    body = first.json()
    assert (body["total"], body["page"], body["page_size"]) == (5, 1, 2)
    assert [item["id"] for item in body["items"]] == [api.ids["sara"], api.ids["omar"]]
    assert all(set(item) == SUMMARY_FIELDS for item in body["items"])
    last = api.client.get("/admin/users", params={"page_size": 2, "page": 3}, headers=api.admin).json()
    assert [item["id"] for item in last["items"]] == [api.ids["admin"]]
    beyond = api.client.get("/admin/users", params={"page": 9}, headers=api.admin).json()
    assert (beyond["items"], beyond["total"]) == ([], 5)
    assert "password_hash" not in first.text and PASSWORD_HASH not in first.text


@pytest.mark.parametrize("params,expected", [
    ({"q": "maya"}, ["maya"]),
    ({"q": "  HADDAD "}, ["maya"]),
    ({"q": "@EXAMPLE.com"}, ["sara", "omar", "maya", "other_admin", "admin"]),
    ({"q": "admin"}, ["other_admin", "admin"]),
    ({"q": "%"}, ["sara"]),
    ({"q": "_"}, ["sara"]),
    ({"q": "nobody"}, []),
    ({"q": ""}, ["sara", "omar", "maya", "other_admin", "admin"]),
    ({"role": "admin"}, ["other_admin", "admin"]),
    ({"role": "support"}, ["sara"]),
    ({"status": "suspended"}, []),
    ({"q": "a", "role": "traveler"}, ["omar", "maya"]),
])
def test_users_list_searches_names_and_emails_and_filters(api, params, expected):
    response = api.client.get("/admin/users", params=params, headers=api.admin)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [api.ids[key] for key in expected]
    assert response.json()["total"] == len(expected)


def test_users_list_filters_by_status(api):
    assert suspend(api, "omar").status_code == 200
    suspended = api.client.get("/admin/users", params={"status": "suspended"}, headers=api.admin).json()
    assert [(item["id"], item["status"]) for item in suspended["items"]] == [(api.ids["omar"], "suspended")]
    active = api.client.get("/admin/users", params={"status": "active"}, headers=api.admin).json()
    assert api.ids["omar"] not in [item["id"] for item in active["items"]] and active["total"] == 4


@pytest.mark.parametrize("params", [
    {"role": "Admin"}, {"role": "superuser"}, {"status": "banned"}, {"page": 0}, {"page": 10_001},
    {"page_size": 0}, {"page_size": 101}, {"q": "x" * 255}, {"statu": "suspended"}, {"sort": "email"},
])
def test_users_list_refuses_invalid_or_unknown_parameters(api, params):
    response = api.client.get("/admin/users", params=params, headers=api.admin)
    assert response.status_code == 422
    assert "x" * 255 not in response.text  # Validation errors never echo the input.


# --- User detail (CMPS271-199) -----------------------------------------------------------------

def test_user_detail_reports_account_information_and_counts(api):
    login(api, "maya@example.com")
    login(api, "maya@example.com")
    api.client.cookies.clear()
    api.client.post("/auth/login", json={"email": "maya@example.com", "password": "Wrong-password-1"})
    created = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)
    with Session(api.app.state.engine) as session:
        maya = session.get(Traveler, api.ids["maya"])
        maya.created_at = created
        session.add(maya)
        session.commit()

    response = api.client.get(f"/admin/users/{api.ids['maya']}", headers=api.admin)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    maya = traveler(api, "maya")
    assert {key: body[key] for key in ("id", "name", "email", "auth_type", "role", "status", "sso_email",
                                       "password_enabled", "google_linked", "last_sign_in_method")} == {
        "id": maya.id, "name": "Maya Haddad", "email": "maya@example.com", "auth_type": "email_password",
        "role": "traveler", "status": "active", "sso_email": None, "password_enabled": True,
        "google_linked": False, "last_sign_in_method": "email_password"}
    assert datetime.fromisoformat(body["created_at"]) == created
    assert datetime.fromisoformat(body["last_sign_in_at"]) == datetime.fromtimestamp(maya.last_login_at, timezone.utc)
    assert body["counts"] == {"active_sessions": 2, "sign_ins": 2, "failed_sign_ins": 1, "passport_uploads": 0}


def test_user_detail_counts_passport_uploads_but_never_returns_passport_data(api):
    folder = api.storage / str(api.ids["maya"])
    folder.mkdir(parents=True)
    upload_ids = ["a" * 32, "b" * 32]
    for upload_id in upload_ids:
        (folder / f"{upload_id}.jpg").write_bytes(b"\xff\xd8 test image")
    review = {"surname": "HADDAD", "given_names": "MAYA", "document_number": "L898902C3",
              "nationality": "LBN", "birth_date": "1990-01-01", "expiry_date": "2031-01-01"}
    (folder / f"{upload_ids[0]}.json").write_text(json.dumps(review), encoding="utf-8")
    (folder / "notes.jpg").write_bytes(b"not an upload")

    response = api.client.get(f"/admin/users/{api.ids['maya']}", headers=api.admin)
    assert response.json()["counts"]["passport_uploads"] == 2
    for value in [*review.values(), *upload_ids]:
        assert value not in response.text


@pytest.mark.parametrize("user_id,status", [("999999", 404), ("0", 422), ("-1", 422), ("2147483648", 422), ("abc", 422)])
def test_user_detail_rejects_unknown_and_invalid_ids(api, user_id, status):
    response = api.client.get(f"/admin/users/{user_id}", headers=api.admin)
    assert response.status_code == status
    if status == 404:
        assert response.json() == {"detail": "User not found."}


# --- Suspend, reactivate, change role, and the audit trail (CMPS271-200, CMPS271-201) ----------

def test_every_admin_action_is_recorded_on_the_target_with_the_acting_admin(api):
    admin, maya = api.ids["admin"], api.ids["maya"]
    assert suspend(api, "maya").json()["status"] == "suspended"
    assert reactivate(api, "maya").json()["status"] == "active"
    promoted = set_role(api, "maya", "support")
    assert (promoted.status_code, promoted.json()["role"]) == (200, "support")
    assert set(promoted.json()) == DETAIL_FIELDS
    assert admin_events(api) == [
        (maya, "status_change", f"admin:{admin}:active->suspended", "success"),
        (maya, "status_change", f"admin:{admin}:suspended->active", "success"),
        (maya, "role_change", f"admin:{admin}:traveler->support", "success"),
    ]
    mirror = [json.loads(line) for path in sorted((api.activity / str(maya)).glob("*.jsonl"))
              for line in path.read_text(encoding="utf-8").splitlines()]
    assert [(line["event_type"], line["identifier"]) for line in mirror if line["event_type"].endswith("_change")] == [
        ("status_change", f"admin:{admin}:active->suspended"), ("status_change", f"admin:{admin}:suspended->active"),
        ("role_change", f"admin:{admin}:traveler->support")]


def test_admins_cannot_suspend_or_demote_themselves(api):
    me = f"/admin/users/{api.ids['admin']}"
    for response, message in [
        (api.client.post(f"{me}/suspend", headers=api.admin), "You can't suspend your own account."),
        (api.client.put(f"{me}/role", json={"role": "traveler"}, headers=api.admin), "You can't change your own role."),
        (api.client.put(f"{me}/role", json={"role": "support"}, headers=api.admin), "You can't change your own role."),
        (api.client.put(f"{me}/role", json={"role": "admin"}, headers=api.admin), "You can't change your own role."),
        (api.client.post(f"{me}/reactivate", headers=api.admin), "This account is already active."),
    ]:
        assert (response.status_code, response.json()) == (409, {"detail": message})
    adam = traveler(api, "admin")
    assert (adam.role, adam.status) == ("admin", "active")
    assert active_sessions(api, api.ids["admin"]) == 1
    assert admin_events(api) == []


def test_repeated_actions_are_refused_without_a_new_event(api):
    assert suspend(api, "maya").status_code == 200
    assert (suspend(api, "maya").status_code, suspend(api, "maya").json()) == (
        409, {"detail": "This account is already suspended."})
    assert reactivate(api, "omar").json() == {"detail": "This account is already active."}
    assert set_role(api, "omar", "traveler").json() == {"detail": "This account already has the traveler role."}
    assert len(admin_events(api)) == 1


def test_an_admin_can_promote_and_demote_other_admins(api):
    maya_token = bearer(login(api, "maya@example.com"))
    assert api.client.get("/admin/me", headers=maya_token).status_code == 403
    assert set_role(api, "maya", "admin").status_code == 200
    assert api.client.get("/admin/me", headers=maya_token).status_code == 200
    # The new admin can act at once, including on the admin who promoted her.
    assert set_role(api, "admin", "traveler", headers=maya_token).status_code == 200
    assert api.client.get("/admin/me", headers=api.admin).status_code == 403
    assert admin_events(api)[-1] == (api.ids["admin"], "role_change", f"admin:{api.ids['maya']}:admin->traveler", "success")


def test_suspending_another_admin_closes_their_admin_access(api):
    rana = bearer(login(api, "rana@example.com"))
    assert suspend(api, "other_admin").status_code == 200
    assert api.client.get("/admin/users", headers=rana).status_code == 401
    assert suspend(api, "maya", headers=rana).status_code == 401
    assert traveler(api, "maya").status == "active"


@pytest.mark.parametrize("body", [{}, {"role": "Admin"}, {"role": "superuser"}, {"role": None},
                                  {"role": "support", "status": "active"}, {"role": "support", "id": 1}])
def test_role_change_accepts_only_a_known_role_and_nothing_else(api, body):
    response = api.client.put(f"/admin/users/{api.ids['maya']}/role", json=body, headers=api.admin)
    assert response.status_code == 422
    assert traveler(api, "maya").role == "traveler"


@pytest.mark.parametrize("action", ["suspend", "reactivate", "role"])
def test_admin_actions_refuse_other_origins(api, action):
    if action == "reactivate":
        assert suspend(api, "maya").status_code == 200
    headers = {**api.admin, "Origin": "https://evil.example"}
    path = f"/admin/users/{api.ids['maya']}/" + action
    response = (api.client.put(path, json={"role": "admin"}, headers=headers) if action == "role"
                else api.client.post(path, headers=headers))
    assert (response.status_code, response.json()) == (403, {"detail": "Origin is not allowed."})
    maya = traveler(api, "maya")
    assert (maya.role, maya.status) == ("traveler", "suspended" if action == "reactivate" else "active")


def test_unknown_targets_are_not_found(api):
    for response in (api.client.post("/admin/users/999999/suspend", headers=api.admin),
                     api.client.post("/admin/users/999999/reactivate", headers=api.admin),
                     api.client.put("/admin/users/999999/role", json={"role": "admin"}, headers=api.admin)):
        assert (response.status_code, response.json()) == (404, {"detail": "User not found."})


def test_a_failed_audit_event_leaves_the_account_unchanged(api, monkeypatch):
    login(api, "maya@example.com")

    def failing_record_activity(*args, **kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(admin_api, "record_activity", failing_record_activity)
    for action in (lambda: suspend(api, "maya"), lambda: set_role(api, "maya", "admin")):
        with pytest.raises(RuntimeError, match="audit store unavailable"):
            action()
    maya = traveler(api, "maya")
    assert (maya.role, maya.status) == ("traveler", "active")
    assert active_sessions(api, api.ids["maya"]) == 1


def test_the_acting_admin_is_checked_again_under_the_lock(api, monkeypatch):
    # Another admin demotes Adam after his request passed the gate but before it locked the rows.
    original = admin_api.lock_accounts

    def demoted_meanwhile(session, actor_id, target_id):
        with Session(api.app.state.engine) as other:
            adam = other.get(Traveler, actor_id)
            adam.role = "traveler"
            other.add(adam)
            other.commit()
        return original(session, actor_id, target_id)

    monkeypatch.setattr(admin_api, "lock_accounts", demoted_meanwhile)
    response = suspend(api, "maya")
    assert (response.status_code, response.json()) == (403, {"detail": FORBIDDEN})
    assert traveler(api, "maya").status == "active"
    assert admin_events(api) == []


# --- Overview (CMPS271-202) --------------------------------------------------------------------

def test_overview_counts_users_new_this_week_and_suspended(api):
    now = datetime.now(timezone.utc)
    with Session(api.app.state.engine) as session:
        for key, created in [("admin", now - timedelta(days=30)), ("other_admin", None),
                             ("maya", now - timedelta(days=6, hours=23))]:
            row = session.get(Traveler, api.ids[key])
            row.created_at = created
            session.add(row)
        session.commit()
    assert suspend(api, "omar").status_code == 200
    response = api.client.get("/admin/overview", headers=api.admin)
    assert response.status_code == 200
    # Maya, Omar and Sara joined in the last 7 days; Adam earlier; Rana's sign-up time is unknown.
    assert response.json() == {"total_users": 5, "new_last_7_days": 3, "suspended": 1, "applications_started": None}


def test_new_accounts_record_their_sign_up_time(api):
    before = datetime.now(timezone.utc)
    api.client.post("/auth/register", json={"name": "New Person", "email": "new@example.com", "password": PASSWORD},
                    headers=ORIGIN)
    with Session(api.app.state.engine) as session:
        created = session.exec(select(Traveler).where(Traveler.email == "new@example.com")).one().created_at
    assert before <= created <= datetime.now(timezone.utc)


# --- Schemas --------------------------------------------------------------------------------------

def schema_properties(schema, components, seen=None):
    """Every property name an OpenAPI schema can contain, following $ref, items and unions."""
    seen = set() if seen is None else seen
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name in seen:
            return
        seen.add(name)
        schema = components[name]
    for key, child in schema.get("properties", {}).items():
        yield key
        yield from schema_properties(child, components, seen)
    for key in ("anyOf", "allOf", "oneOf"):
        for part in schema.get(key, []):
            yield from schema_properties(part, components, seen)
    if isinstance(schema.get("items"), dict):
        yield from schema_properties(schema["items"], components, seen)


def test_admin_schemas_forbid_extra_input_and_carry_no_passport_fields(api):
    schema = api.app.openapi()
    components = schema["components"]["schemas"]
    admin_paths = {path: operations for path, operations in schema["paths"].items() if path.startswith("/admin/")}
    assert {"/admin/users", "/admin/users/{user_id}", "/admin/overview"} <= set(admin_paths)
    bodies = 0
    for path, operations in admin_paths.items():
        for method, operation in operations.items():
            body = operation.get("requestBody", {}).get("content", {}).get("application/json")
            if body is not None:
                bodies += 1
                assert components[body["schema"]["$ref"].rsplit("/", 1)[-1]]["additionalProperties"] is False
            response = operation["responses"]["200"]["content"]["application/json"]["schema"]
            # The upload count is the one passport-related number the API reports.
            names = set(schema_properties(response, components)) - {"passport_uploads"}
            assert names, (method, path)
            assert not [name for name in names if any(word in name for word in PASSPORT_WORDS)], (method, path)
    assert bodies == 1
