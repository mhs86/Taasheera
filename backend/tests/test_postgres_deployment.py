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
