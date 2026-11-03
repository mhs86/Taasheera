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


def proxy_app(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTH_TRUST_CLOUDFRONT_PROXY', 'true')
    app = create_app(f'sqlite:///{tmp_path / "viewer.db"}')
    from fastapi import Request
    from app.security import admitted

    @app.get('/test-address')
    def address(request: Request):
        return {'address': client_address(request)}

    @app.get('/test-admit')
    def admit(request: Request):
        with Session(app.state.engine) as db:
            return {'admitted': admitted(request, db, [('viewer-test', client_address(request), 1, 60)])}
    return app


@pytest.mark.parametrize('value,expected', [
    ('2001:db8::1:46532', '2001:db8::1'),      # CloudFront IPv6: unbracketed, with port
    ('[2001:db8::1]:46532', '2001:db8::1'),    # bracketed, with port
    ('203.0.113.9:46532', '203.0.113.9'),      # IPv4 with port
    ('203.0.113.9', '203.0.113.9'),            # IPv4, no port
    # Unsupported: nginx always sends a port, so a bare IPv6 loses its last group as a "port",
    # fails validation ("2001:db8:") and falls back to the proxy peer.
    ('2001:db8::1', 'testclient'),
    ('not-an-address', 'testclient'),          # garbage falls back to the proxy peer
    ('2001:db8::1:99999', 'testclient'),       # port out of range is not a viewer address
    ('2001:db8::1:abc', 'testclient'),         # non-numeric port
    ('203.0.113.9:abc', 'testclient'),
])
def test_cloudfront_viewer_address_formats(tmp_path, monkeypatch, value, expected):
    with TestClient(proxy_app(tmp_path, monkeypatch)) as client:
        assert client.get('/test-address', headers={'X-Taasheera-Client-IP': value}).json() == {'address': expected}


def test_distinct_ipv6_viewers_do_not_share_a_limiter_bucket(tmp_path, monkeypatch):
    with TestClient(proxy_app(tmp_path, monkeypatch)) as client:
        def admit(value):
            return client.get('/test-admit', headers={'X-Taasheera-Client-IP': value}).json()['admitted']
        assert admit('2001:db8::1:46532') is True
        assert admit('2001:db8::1:46533') is False      # same viewer, new port: same bucket
        assert admit('2001:db8::2:46532') is True       # different viewer: own bucket


def test_same_ipv6_viewer_on_different_source_ports_gets_one_key(tmp_path, monkeypatch):
    with TestClient(proxy_app(tmp_path, monkeypatch)) as client:
        seen = {client.get('/test-address', headers={'X-Taasheera-Client-IP': f'2001:db8::1:{port}'}).json()['address']
                for port in (443, 8080, 46532)}
        assert seen == {'2001:db8::1'}
