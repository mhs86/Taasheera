import ipaddress
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import create_app
from app.models import ResetRateLimit, Traveler
from app.security import client_address


def test_login_throttles_known_and_unknown_accounts_before_bcrypt(tmp_path, monkeypatch):
    app = create_app(f'sqlite:///{tmp_path / "limits.db"}')
    with TestClient(app) as client:
        check = Mock(return_value=False)
        monkeypatch.setattr('app.auth.bcrypt.checkpw', check)
        for _ in range(10):
            assert client.post('/auth/login', json={'email': 'missing@example.com', 'password': 'wrong-password'}).status_code == 401
        limited = client.post('/auth/login', json={'email': 'missing@example.com', 'password': 'wrong-password'}, headers={'X-Forwarded-For': '9.9.9.9'})
        assert limited.status_code == 429 and limited.headers['retry-after'] == '900'
        assert check.call_count == 10
        with Session(app.state.engine) as session:
            assert all('missing@example.com' not in r.key and 'testclient' not in r.key for r in session.exec(select(ResetRateLimit)).all())


def test_google_exchange_is_throttled_before_provider_requests(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'test.apps.googleusercontent.com')
    verify = Mock(side_effect=ValueError('not valid'))
    monkeypatch.setattr('app.google_auth.id_token.verify_oauth2_token', verify)
    with TestClient(create_app(f'sqlite:///{tmp_path / "google.db"}')) as client:
        for _ in range(30):
            assert client.post('/auth/google', json={'id_token': 'synthetic-bad-token'}).status_code == 401
        assert client.post('/auth/google', json={'id_token': 'synthetic-bad-token'}).status_code == 429
        assert verify.call_count == 30


def test_registration_cannot_set_roles_or_account_type_and_has_origin_protection(tmp_path):
    with TestClient(create_app(f'sqlite:///{tmp_path / "register.db"}')) as client:
        body = {'name': 'Specimen', 'email': 'specimen@example.com', 'password': 'synthetic-password'}
        for extra in ({'auth_type': 'google'}, {'admin': True}, {'sso_email': 'other@example.com'}):
            assert client.post('/auth/register', json={**body, **extra}).status_code == 422
        assert client.post('/auth/register', json=body, headers={'Origin': 'https://evil.invalid'}).status_code == 403
        assert client.post('/auth/register', json=body).status_code == 201
        assert client.post('/auth/register', json=body).status_code == 409
        assert client.post('/auth/register', json=body).status_code == 409
        assert client.post('/auth/register', json=body).status_code == 429


@pytest.mark.parametrize('value,expected', [('203.0.113.9:443', '203.0.113.9'), ('[2001:db8::9]:443', '2001:db8::9'), ('invalid', 'testclient')])
def test_trusted_cloudfront_client_addresses_are_parsed_only_when_enabled(tmp_path, monkeypatch, value, expected):
    monkeypatch.setenv('AUTH_TRUST_CLOUDFRONT_PROXY', 'true')
    app = create_app(f'sqlite:///{tmp_path / "proxy.db"}')
    from fastapi import Request
    @app.get('/test-address')
    def address(request: Request):
        return {'address': client_address(request)}
    with TestClient(app) as client:
        assert client.get('/test-address', headers={'X-Taasheera-Client-IP': value}).json() == {'address': expected}
