"""Adversarial recovery tests: guesses, replay, resends, races, and account types."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
import hmac
import io
import json
import logging
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlmodel import Session, select

from app.auth import token_hash
from app.main import create_app
from app.models import (ActivityEvent, GoogleIdentity, PasswordResetChallenge,
                        PasswordResetToken, ResetRateLimit, Traveler)
from app.observability import RequestJsonFormatter
from app.security import security_log
from test_password_reset import api, clear_limits, EMAIL, OLD, NEW, login, reset


def request_code(api, email=EMAIL):
    client, _, sender = api
    assert client.post('/auth/forgot-password', json={'email': email}).status_code == 202
    return sender.messages[-1][1]


def verify(client, code, email=EMAIL, **extra):
    return client.post('/auth/verify-reset-code', json={'email': email, 'code': code, **extra})


def test_full_otp_flow_stores_no_plaintext_and_updates_same_user(api):
    client, app, _ = api
    logged_in = login(client)
    code = request_code(api)
    with Session(app.state.engine) as session:
        original = session.get(Traveler, 1).password_hash
        challenge = session.get(PasswordResetChallenge, 1)
        assert challenge.code_digest != hashlib.sha256(code.encode()).hexdigest()
        assert session.exec(select(PasswordResetToken)).all() == []
    grant = verify(client, code)
    assert grant.status_code == 200
    assert grant.headers['cache-control'] == 'no-store'
    assert grant.json()['expires_in'] == 300
    raw = grant.json()['reset_token']
    assert len(raw) == 43 and raw != code
    assert verify(client, code).status_code == 400
    assert reset(client, raw).status_code == 204
    assert reset(client, raw).status_code == 400
    assert login(client, OLD).status_code == 401
    assert login(client, NEW).status_code == 200
    assert client.get('/auth/me', headers={'Authorization': 'Bearer ' + logged_in.json()['access_token']}).status_code == 401
    with Session(app.state.engine) as session:
        user = session.exec(select(Traveler)).one()
        assert user.id == 1 and user.password_hash != original and user.auth_type == 'email_password'
        event = session.exec(select(ActivityEvent).where(ActivityEvent.event_type == 'password_reset')).one()
        assert event.traveler_id == 1 and event.identifier == 'email_otp'


def test_five_guesses_lock_even_the_correct_code_and_survive_a_new_process(api):
    client, app, sender = api
    code = request_code(api)
    wrong = '999999' if code != '999999' else '888888'
    for _ in range(5):
        assert verify(client, wrong).status_code == 400
    replacement = create_app(str(app.state.engine.url), reset_sender=sender)
    with TestClient(replacement) as other:
        assert verify(other, code).status_code == 400
    with Session(app.state.engine) as session:
        challenge = session.get(PasswordResetChallenge, 1)
        assert challenge.attempts == 5 and challenge.consumed
    assert login(client).status_code == 200


def test_expired_code_and_expired_grant_are_rejected_without_password_change(api):
    client, app, _ = api
    code = request_code(api)
    with Session(app.state.engine) as session:
        row = session.get(PasswordResetChallenge, 1)
        row.expires_at = int(time.time())
        session.add(row); session.commit()
    assert verify(client, code).status_code == 400
    clear_limits(app)
    grant = verify(client, request_code(api)).json()['reset_token']
    with Session(app.state.engine) as session:
        row = session.get(PasswordResetToken, token_hash(grant))
        row.expires_at = int(time.time())
        session.add(row); session.commit()
    assert reset(client, grant).status_code == 400
    assert login(client).status_code == 200


def test_resend_invalidates_old_code_and_old_grants(api, monkeypatch):
    client, app, _ = api
    monkeypatch.setattr('app.password_reset.secrets.randbelow', lambda _: 123456)
    first = request_code(api)
    first_grant = verify(client, first).json()['reset_token']
    clear_limits(app)
    monkeypatch.setattr('app.password_reset.secrets.randbelow', lambda _: 654321)
    second = request_code(api)
    assert verify(client, first).status_code == 400
    assert reset(client, first_grant).status_code == 400
    assert reset(client, verify(client, second).json()['reset_token']).status_code == 204


@pytest.mark.parametrize('code', ['12345', '1234567', '１２３４５６', '١٢٣٤٥٦', '12a456', ' 12345', None, 123456])
def test_malformed_or_non_ascii_codes_are_never_echoed(api, code):
    client, app, _ = api
    request_code(api)
    response = verify(client, code)
    assert response.status_code == 422
    if isinstance(code, str):
        assert code not in response.text
    with Session(app.state.engine) as session:
        assert session.get(PasswordResetChallenge, 1).attempts == 0


def test_unknown_and_google_only_accounts_get_identical_recovery_results(api):
    client, app, sender = api
    with Session(app.state.engine) as session:
        user = Traveler(name='Google user', email='google@example.com', sso_email='google@example.com', password_hash='', auth_type='google')
        session.add(user); session.flush()
        session.add(GoogleIdentity(subject='google-only-sub', traveler_id=user.id)); session.commit()
    responses = [client.post('/auth/forgot-password', json={'email': e}) for e in (EMAIL, 'missing@example.com', 'google@example.com')]
    assert all(r.status_code == 202 and r.json() == responses[0].json() for r in responses)
    assert len(sender.messages) == 1
    errors = [verify(client, '123456', email=e) for e in ('missing@example.com', 'google@example.com')]
    assert errors[0].status_code == errors[1].status_code == 400 and errors[0].json() == errors[1].json()
    with Session(app.state.engine) as session:
        assert session.get(PasswordResetChallenge, 2) is None
        assert session.get(Traveler, 2).password_hash == ''


def test_email_password_account_with_explicit_google_link_keeps_password_recovery(api):
    client, app, _ = api
    with Session(app.state.engine) as session:
        user = session.get(Traveler, 1)
        user.sso_email = 'different-google@example.com'
        session.add(user); session.add(GoogleIdentity(subject='linked-sub', traveler_id=1)); session.commit()
    grant = verify(client, request_code(api)).json()['reset_token']
    assert reset(client, grant).status_code == 204
    with Session(app.state.engine) as session:
        assert session.get(GoogleIdentity, 'linked-sub').traveler_id == 1
        assert session.get(Traveler, 1).auth_type == 'email_password'


def test_code_is_bound_to_email_and_extra_owner_fields_are_rejected(api):
    client, _, _ = api
    code = request_code(api)
    assert verify(client, code, email='someone-else@example.com').status_code == 400
    assert verify(client, code, traveler_id=2).status_code == 422
    assert reset(client, verify(client, code).json()['reset_token']).status_code == 204


def test_concurrent_code_verification_has_exactly_one_winner(api):
    _, app, _ = api
    code = request_code(api)
    gate = Barrier(2)
    def attempt(_):
        with TestClient(app) as other:
            gate.wait(timeout=5)
            return verify(other, code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(r.status_code for r in results) == [200, 400]
    with Session(app.state.engine) as session:
        assert len(session.exec(select(PasswordResetToken)).all()) == 1


def test_code_verification_rate_limit_applies_to_unknown_email_and_ignores_spoofed_forwarding(api):
    client, _, _ = api
    for _ in range(10):
        assert verify(client, '123456', email='unknown@example.com').status_code == 400
    response = client.post('/auth/verify-reset-code', json={'email': 'unknown@example.com', 'code': '123456'},
                           headers={'X-Forwarded-For': '1.2.3.4', 'X-Taasheera-Client-IP': '1.2.3.4:443'})
    assert response.status_code == 429 and response.headers['retry-after'] == '900'


def test_untrusted_origins_cannot_request_verify_or_complete(api):
    client, _, _ = api
    for path, body in [('/auth/forgot-password', {'email': EMAIL}),
                       ('/auth/verify-reset-code', {'email': EMAIL, 'code': '123456'}),
                       ('/auth/reset-password', {'token': 'unknown', 'password': NEW})]:
        assert client.post(path, json=body, headers={'Origin': 'https://evil.invalid'}).status_code == 403


def test_security_logs_have_request_ids_and_no_email_code_password_or_grant(api):
    client, _, _ = api
    output = io.StringIO()
    handler = logging.StreamHandler(output); handler.setFormatter(RequestJsonFormatter())
    security_log.addHandler(handler)
    try:
        code = request_code(api)
        grant = verify(client, code).json()['reset_token']
        assert reset(client, grant).status_code == 204
    finally:
        security_log.removeHandler(handler)
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert {'reset-request', 'reset-delivery', 'reset-verify', 'reset-complete'} <= {r['operation'] for r in records}
    assert all(len(r['request_id']) == 32 for r in records)
    for secret in (EMAIL, OLD, NEW, code, grant):
        assert secret not in output.getvalue()
