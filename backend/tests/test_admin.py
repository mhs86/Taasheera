import base64
import io
import json
import logging
import re
import time
from types import SimpleNamespace

import bcrypt
import jwt
import pytest
from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.admin_api import FORBIDDEN, require_role
from app.auth import create_current_traveler
from app.main import create_app
from app.models import ActivityEvent, AuthSession, Traveler
from app.observability import RequestJsonFormatter, request_log


PASSWORD = "Staff-password-123"
# Hashed once at a low cost to keep the module fast; bcrypt.checkpw accepts any cost.
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
ACTORS = {
    "traveler": ("traveler", "active"),
    "support": ("support", "active"),
    "admin": ("admin", "active"),
    "suspended_admin": ("admin", "suspended"),
    "suspended_support": ("support", "suspended"),
    "suspended_traveler": ("traveler", "suspended"),
}
REFUSED = [name for name in ACTORS if name != "admin"]
CLAIMS = {"sub", "sid", "type", "iat", "exp", "iss", "aud", "jti"}


def email_of(name):
    return f"{name.replace('_', '-')}@example.com"


def add_accounts(app, names=ACTORS):
    ids = {}
    with Session(app.state.engine) as session:
        for name in names:
            role, status = ACTORS[name]
            traveler = Traveler(name=name.replace("_", " ").title(), email=email_of(name),
                                password_hash=PASSWORD_HASH, role=role, status=status)
            session.add(traveler)
            session.commit()
            ids[name] = traveler.id
    return ids


def login(client, name):
    # start_session revokes the session behind any refresh cookie it receives.
    client.cookies.clear()
    response = client.post("/auth/login", json={"email": email_of(name), "password": PASSWORD})
    client.cookies.clear()
    assert response.status_code == 200
    return response.json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def update_account(app, traveler_id, **changes):
    with Session(app.state.engine) as session:
        traveler = session.get(Traveler, traveler_id)
        for field, value in changes.items():
            setattr(traveler, field, value)
        session.add(traveler)
        session.commit()


def unverified_claims(token):
    return jwt.decode(token, options={"verify_signature": False})


@pytest.fixture
def api(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'admin.db').as_posix()}")
    with TestClient(app) as client:
        ids = add_accounts(app)
        tokens = {name: login(client, name) for name in ACTORS}
        yield SimpleNamespace(client=client, app=app, ids=ids, tokens=tokens)


def admin_route_contexts(app):
    return [context for context in iter_route_contexts(app.routes)
            if context.path == "/admin" or (context.path or "").startswith("/admin/")]


def declared_roles(context):
    """Roles a route admits: every gate declared on the route or its router must pass."""
    gates = [depends.dependency.allowed_roles for depends in context.dependencies
             if hasattr(depends.dependency, "allowed_roles")]
    return frozenset.intersection(*gates) if gates else None


def admitted_actors(context):
    allowed = declared_roles(context)
    return {name for name, (role, status) in ACTORS.items() if status == "active" and role in allowed}


def role_gates(dependant):
    found, pending = [], [dependant]
    while pending:
        current = pending.pop()
        allowed = getattr(current.call, "allowed_roles", None)
        if allowed is not None:
            found.append(allowed)
        pending.extend(current.dependencies)
    return found


def test_admin_me_returns_the_signed_in_admin(api):
    response = api.client.get("/admin/me", headers=bearer(api.tokens["admin"]))
    assert response.status_code == 200
    assert response.json() == {"id": api.ids["admin"], "name": "Admin", "email": "admin@example.com", "role": "admin"}
    assert response.headers["cache-control"] == "no-store"
    assert "password_hash" not in response.text and "status" not in response.json()


def test_every_admin_route_admits_only_active_admins(api):
    contexts = admin_route_contexts(api.app)
    assert contexts
    assert all(isinstance(context.original_route, APIRoute) for context in contexts)
    for context in contexts:
        path = re.sub(r"\{[^}]+\}", "1", context.path)
        for method in sorted(context.methods):
            anonymous = api.client.request(method, path)
            assert anonymous.status_code == 401, (method, path)
            assert anonymous.headers["www-authenticate"] == "Bearer"
            assert anonymous.headers["cache-control"] == "no-store"
            admitted_names = admitted_actors(context)
            for name in ACTORS:
                response = api.client.request(method, path, headers=bearer(api.tokens[name]))
                if name in admitted_names:
                    assert response.status_code not in {401, 403}, (method, path, name)
                    if method == "GET" and "{" not in context.path:
                        assert response.status_code == 200
                else:
                    assert response.status_code == 403, (method, path, name)
                    assert response.json() == {"detail": FORBIDDEN}
                assert response.headers["cache-control"] == "no-store"


def test_admin_routes_are_gated_and_role_gates_exist_only_under_admin(api):
    contexts = admin_route_contexts(api.app)
    assert contexts
    for context in contexts:
        # Declared on the route or its router, not only as an endpoint parameter that a later edit could drop.
        allowed = declared_roles(context)
        assert allowed and "traveler" not in allowed, context.path
        assert role_gates(context.dependant), context.path
    assert {context.path: declared_roles(context) for context in contexts}["/admin/me"] == {"admin"}
    others = [context for context in iter_route_contexts(api.app.routes) if context not in contexts]
    assert others
    for context in others:
        dependant = getattr(context, "dependant", None)
        if dependant is not None:
            assert role_gates(dependant) == [], context.path


def test_role_and_status_are_read_from_the_database_on_every_request(api):
    headers = bearer(api.tokens["admin"])
    admin_id = api.ids["admin"]
    steps = [
        ({}, 200), ({"role": "traveler"}, 403), ({"role": "admin"}, 200), ({"status": "suspended"}, 403),
        ({"status": "active"}, 200), ({"role": "support"}, 403),
    ]
    for changes, expected in steps:
        update_account(api.app, admin_id, **changes)
        assert api.client.get("/admin/me", headers=headers).status_code == expected, changes
        assert api.client.get("/auth/me", headers=headers).status_code == 200


def test_promoted_traveler_gains_access_with_the_same_token(api):
    headers = bearer(api.tokens["traveler"])
    assert api.client.get("/admin/me", headers=headers).status_code == 403
    update_account(api.app, api.ids["traveler"], role="admin")
    response = api.client.get("/admin/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_access_tokens_carry_no_role_claim(api):
    for name in ("admin", "traveler", "suspended_admin"):
        assert set(unverified_claims(api.tokens[name])) == CLAIMS


def test_role_claims_in_a_validly_signed_token_are_ignored(api):
    claims = {**unverified_claims(api.tokens["traveler"]),
              "role": "admin", "roles": ["admin"], "is_admin": True, "status": "active"}
    token = jwt.encode(claims, api.app.state.auth_settings.jwt_secret, algorithm="HS256")
    assert api.client.get("/auth/me", headers=bearer(token)).status_code == 200  # The signature is valid.
    response = api.client.get("/admin/me", headers=bearer(token))
    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN}


@pytest.mark.parametrize("headers,params", [
    ({"X-Role": "admin"}, {}), ({"X-User-Role": "admin"}, {}), ({"X-Admin": "true"}, {}),
    ({"X-Forwarded-User": "admin@example.com"}, {}), ({"X-Original-URL": "/admin/me"}, {}),
    ({"X-HTTP-Method-Override": "GET"}, {}), ({"Cookie": "role=admin"}, {}),
    ({}, {"role": "admin"}), ({}, {"as": "admin"}), ({}, {"admin": "true"}), ({}, {"status": "active"}),
])
def test_client_supplied_role_hints_are_ignored(api, headers, params):
    for name in REFUSED:
        response = api.client.get("/admin/me", headers={**bearer(api.tokens[name]), **headers}, params=params)
        assert response.status_code == 403, name
        assert response.json() == {"detail": FORBIDDEN}


def unsigned(claims):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}."


@pytest.mark.parametrize("case", [
    "alg_none", "wrong_secret", "hs384", "admin_sub_traveler_sid", "traveler_sub_admin_sid",
    "truncated_signature", "cookie", "query_parameter", "basic_scheme",
])
def test_forged_or_altered_tokens_cannot_reach_admin(api, case):
    secret = api.app.state.auth_settings.jwt_secret
    admin_token = api.tokens["admin"]
    admin_claims = unverified_claims(admin_token)
    traveler_claims = unverified_claims(api.tokens["traveler"])
    headers, cookies, params = {}, {}, {}
    if case == "alg_none":
        headers = bearer(unsigned(admin_claims))
    elif case == "wrong_secret":
        headers = bearer(jwt.encode(admin_claims, "a-different-secret-of-at-least-32-bytes!", algorithm="HS256"))
    elif case == "hs384":
        headers = bearer(jwt.encode(admin_claims, secret, algorithm="HS384"))
    elif case == "admin_sub_traveler_sid":
        headers = bearer(jwt.encode({**traveler_claims, "sub": admin_claims["sub"]}, secret, algorithm="HS256"))
    elif case == "traveler_sub_admin_sid":
        headers = bearer(jwt.encode({**admin_claims, "sub": traveler_claims["sub"]}, secret, algorithm="HS256"))
    elif case == "truncated_signature":
        headers = bearer(admin_token[:-4])
    elif case == "cookie":
        cookies = {"access_token": admin_token, "Authorization": f"Bearer {admin_token}"}
    elif case == "query_parameter":
        params = {"access_token": admin_token, "token": admin_token}
    else:
        headers = {"Authorization": f"Basic {admin_token}"}
    api.client.cookies.clear()
    for name, value in cookies.items():
        api.client.cookies.set(name, value)
    try:
        response = api.client.get("/admin/me", headers=headers, params=params)
    finally:
        api.client.cookies.clear()
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("ending", ["logout", "expired", "revoked"])
def test_ended_admin_sessions_are_rejected(api, ending):
    client = api.client
    client.cookies.clear()
    login_response = client.post("/auth/login", json={"email": email_of("admin"), "password": PASSWORD})
    headers = bearer(login_response.json()["access_token"])
    assert client.get("/admin/me", headers=headers).status_code == 200
    if ending == "logout":
        assert client.post("/auth/logout").status_code == 204
    else:
        session_id = unverified_claims(login_response.json()["access_token"])["sid"]
        with Session(api.app.state.engine) as session:
            auth_session = session.get(AuthSession, session_id)
            if ending == "expired":
                auth_session.expires_at = int(time.time()) - 1
            else:
                auth_session.revoked = True
            session.add(auth_session)
            session.commit()
    client.cookies.clear()
    assert client.get("/admin/me", headers=headers).status_code == 401


def test_refusals_do_not_reveal_role_or_status(api):
    refusals = set()
    for name in REFUSED:
        response = api.client.get("/admin/me", headers=bearer(api.tokens[name]))
        refusals.add((response.status_code, response.content, response.headers["cache-control"]))
    assert refusals == {(403, json.dumps({"detail": FORBIDDEN}, separators=(",", ":")).encode(), "no-store")}


@pytest.mark.parametrize("method,path,status", [
    ("GET", "/admin/unknown", 404), ("GET", "/admin", 404), ("POST", "/admin/me", 405),
    ("DELETE", "/admin/me", 405), ("GET", "/admin/me/", 307),
])
def test_every_admin_response_is_no_store(api, method, path, status):
    for headers in ({}, bearer(api.tokens["traveler"]), bearer(api.tokens["admin"])):
        response = api.client.request(method, path, headers=headers, follow_redirects=False)
        assert response.status_code == status
        assert response.headers["cache-control"] == "no-store"
    # Only /admin paths are affected.
    assert "cache-control" not in api.client.get("/health/live").headers
    assert "cache-control" not in api.client.get("/administrator").headers


def test_admin_responses_stay_no_store_behind_a_path_prefix(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'prefixed.db').as_posix()}")
    # uvicorn --root-path /api puts the prefix in scope["path"] as well as scope["root_path"].
    with TestClient(app, root_path="/api") as client:
        add_accounts(app, ["admin"])
        client.cookies.clear()
        token = client.post("/api/auth/login", json={"email": email_of("admin"), "password": PASSWORD}).json()
        response = client.get("/api/admin/me", headers=bearer(token["access_token"]))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/admin/unknown").headers["cache-control"] == "no-store"
        assert "cache-control" not in client.get("/api/health/live").headers


@pytest.mark.parametrize("roles", [(), ("Admin",), (" admin",), ("superuser",), ("admin", "superuser")])
def test_require_role_accepts_only_known_roles(roles):
    with pytest.raises(ValueError, match="require_role"):
        require_role(lambda: None, *roles)


def test_support_can_be_opted_in_with_require_role(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'support.db').as_posix()}")

    def get_session():
        with Session(app.state.engine) as session:
            yield session

    staff = require_role(create_current_traveler(get_session), "admin", "support")
    router = APIRouter(prefix="/admin/support-check", dependencies=[Depends(staff)])

    @router.get("")
    def support_check():
        return {"ok": True}

    app.include_router(router)
    with TestClient(app) as client:
        add_accounts(app, ["admin", "support", "suspended_support", "traveler"])
        for name, expected in [("support", 200), ("admin", 200), ("suspended_support", 403), ("traveler", 403)]:
            response = client.get("/admin/support-check", headers=bearer(login(client, name)))
            assert response.status_code == expected, name
            assert response.headers["cache-control"] == "no-store"
        # The admin-only route stays closed to support.
        assert client.get("/admin/me", headers=bearer(login(client, "support"))).status_code == 403
        context = next(context for context in iter_route_contexts(app.routes) if context.path == "/admin/support-check")
        assert declared_roles(context) == {"admin", "support"}


def test_admin_refusals_are_logged_without_account_details(api):
    with Session(api.app.state.engine) as session:
        events_before = session.exec(select(func.count()).select_from(ActivityEvent)).one()
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(RequestJsonFormatter())
    request_log.addHandler(handler)
    try:
        assert api.client.get("/admin/me", headers=bearer(api.tokens["traveler"])).status_code == 403
    finally:
        request_log.removeHandler(handler)
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [(record["route"], record["status"]) for record in records] == [("/admin/me", 403)]
    assert email_of("traveler") not in output.getvalue()
    assert api.tokens["traveler"] not in output.getvalue()
    # Refused attempts are not audit events: any signed-in traveler could otherwise flood the table.
    with Session(api.app.state.engine) as session:
        assert session.exec(select(func.count()).select_from(ActivityEvent)).one() == events_before


def object_schemas(schema, components, seen):
    """Every object schema a body can contain, following $ref, properties, items and unions."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name not in seen:
            seen.add(name)
            yield from object_schemas(components[name], components, seen)
        return
    if schema.get("type") == "object" or "properties" in schema:
        yield schema
    for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
        for part in schema.get(key, []):
            yield from object_schemas(part, components, seen)
    for child in (schema.get("items"), schema.get("additionalProperties"), *schema.get("properties", {}).values()):
        if isinstance(child, dict):
            yield from object_schemas(child, components, seen)


def test_no_json_request_body_outside_admin_accepts_extra_fields_or_roles(api):
    schema = api.app.openapi()
    components = schema["components"]["schemas"]
    # The assistant's chat history labels each turn as said by the user or the assistant.
    assert components["ChatTurn"]["properties"]["role"]["enum"] == ["user", "assistant"]
    allowed = {"ChatTurn": {"role"}}
    checked = 0
    for path, operations in schema["paths"].items():
        if path == "/admin" or path.startswith("/admin/"):
            continue
        for method, operation in operations.items():
            body = operation.get("requestBody", {}).get("content", {}).get("application/json")
            if body is None:
                continue
            for model in object_schemas(body["schema"], components, set()):
                where = (method, path, model.get("title"))
                assert model.get("additionalProperties") is False, where
                access_fields = {"role", "roles", "status", "is_admin"} & set(model.get("properties", {}))
                assert access_fields <= allowed.get(model.get("title"), set()), where
                checked += 1
    assert checked >= 8


def test_auth_me_is_unchanged_for_admins(api):
    response = api.client.get("/auth/me", headers=bearer(api.tokens["admin"]))
    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["name"], body["email"]) == (api.ids["admin"], "Admin", "admin@example.com")
    assert not {"role", "status"} & set(body)  # Only /admin/me reports the role.
