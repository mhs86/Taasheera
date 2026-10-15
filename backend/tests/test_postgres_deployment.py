"""Opt-in deployment smoke test against a disposable PostgreSQL database."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import migrate
from app.main import create_app


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs disposable PostgreSQL")
def test_migration_and_authenticated_request_on_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SCHEMA_AUTO_CREATE", "false")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://travel.example")
    migrate.upgrade()
    email = f"ci-{uuid4().hex}@example.com"
    with TestClient(create_app(), base_url="https://testserver") as client:
        assert client.get("/health/ready").status_code == 200
        registered = client.post("/auth/register", json={
            "name": "CI traveler", "email": email, "password": "safe-test-password-123",
        })
        assert registered.status_code == 201
        login = client.post("/auth/login", json={
            "email": email, "password": "safe-test-password-123",
        })
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.post("/activity/events", headers=headers, json={
            "event_type": "page_visit", "page": "home", "outcome": "visited",
        }).status_code == 204


@pytest.mark.skipif(not os.environ.get('TEST_POSTGRES_URL'), reason='needs disposable PostgreSQL')
def test_postgres_otp_updates_account_and_revokes_sessions(monkeypatch):
    from unittest.mock import Mock
    from sqlalchemy import text
    from sqlmodel import Session
    monkeypatch.setenv('DATABASE_URL', os.environ['TEST_POSTGRES_URL'])
    monkeypatch.setenv('SCHEMA_AUTO_CREATE', 'false')
    monkeypatch.setenv('RESET_MAIL_PROVIDER', 'ses')
    monkeypatch.setenv('SES_FROM_EMAIL', 'sharafm032@gmail.com')
    migrate.upgrade()
    sender = Mock()
    email = f'otp-{uuid4().hex}@example.com'
    app = create_app(reset_sender=sender)
    with TestClient(app) as client:
        registered = client.post('/auth/register', json={'name': 'OTP specimen', 'email': email, 'password': 'Original-test-password'})
        assert registered.status_code == 201
        owner = registered.json()['id']
        access = client.post('/auth/login', json={'email': email, 'password': 'Original-test-password'}).json()['access_token']
        assert client.post('/auth/forgot-password', json={'email': email}).status_code == 202
        code = sender.send_reset.call_args.args[1]
        assert len(code) == 6 and code.isdigit()
        verified = client.post('/auth/verify-reset-code', json={'email': email, 'code': code})
        assert verified.status_code == 200
        grant = verified.json()['reset_token']
        assert client.post('/auth/verify-reset-code', json={'email': email, 'code': code}).status_code == 400
        assert client.post('/auth/reset-password', json={'token': grant, 'password': 'Replacement-test-password'}).status_code == 204
        assert client.get('/auth/me', headers={'Authorization': 'Bearer ' + access}).status_code == 401
        assert client.post('/auth/login', json={'email': email, 'password': 'Original-test-password'}).status_code == 401
        assert client.post('/auth/login', json={'email': email, 'password': 'Replacement-test-password'}).status_code == 200
        with Session(app.state.engine) as session:
            report = session.execute(text('SELECT auth_type,password_enabled FROM admin_user_auth WHERE id=:id'), {'id': owner}).one()
            assert tuple(report) == ('email_password', 1)
