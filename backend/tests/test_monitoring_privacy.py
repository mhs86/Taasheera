import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import jwt
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, Session, select

from app.account_lock import account_lock
from app.activity import record_activity
from app.auth import COOKIE_NAME
from app.database import build_engine
from app.main import create_app
from app.models import (APPLICATION_STATUSES, AccountErasure, ActivityEvent, AuthSession, DocumentAccess,
    GoogleIdentity, PasswordResetChallenge, PasswordResetToken, RefreshToken, Traveler, TravelerProfile, Application, ApplicationAnswer)
from app.monitoring import configure_monitoring, scrub_event
from app.passport.extraction import Extraction, ExtractionStatus
from app.privacy import retry_erasures
from app.schema import migration_config
from scripts.monitor_uptime import alert_team, check_uptime

PASSWORD = 'Synthetic-password-123'
HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()


@pytest.fixture(params=['sqlite', pytest.param('postgres', marks=pytest.mark.skipif(
    not os.environ.get('TEST_POSTGRES_URL'), reason='needs disposable PostgreSQL'))])
def api(tmp_path, monkeypatch, request):
    monkeypatch.setenv('PASSPORT_STORAGE_DIR', str(tmp_path / 'passports'))
    monkeypatch.delenv('SENTRY_DSN', raising=False)
    server = None
    name = f'privacy_{uuid4().hex[:12]}'
    if request.param == 'postgres':
        server_url = make_url(os.environ['TEST_POSTGRES_URL'])
        server = build_engine(server_url.render_as_string(hide_password=False)).execution_options(isolation_level='AUTOCOMMIT')
        with server.connect() as connection: connection.execute(text(f'CREATE DATABASE "{name}"'))
        url = server_url.set(database=name).render_as_string(hide_password=False)
    else:
        url = f"sqlite:///{tmp_path / 'features.db'}"
    app = create_app(url)
    # Verify erasure ordering with real FK enforcement, including the two session tables.
    @event.listens_for(app.state.engine, 'connect')
    def foreign_keys(connection, _):
        if request.param == 'sqlite': connection.execute('PRAGMA foreign_keys=ON')
    with TestClient(app) as client:
        ids, tokens, cookies = {}, {}, {}
        for key in ('admin', 'support', 'one', 'two'):
            with Session(app.state.engine) as session:
                traveler = Traveler(name=f'Synthetic {key}', email=f'{key}@example.com', password_hash=HASH,
                                    role=key if key in {'admin', 'support'} else 'traveler')
                session.add(traveler); session.commit(); ids[key] = traveler.id
            client.cookies.clear()
            signed_in = client.post('/auth/login', json={'email': f'{key}@example.com', 'password': PASSWORD})
            tokens[key] = signed_in.json()['access_token']
            cookies[key] = client.cookies.get(COOKIE_NAME)
        client.cookies.clear()
        yield SimpleNamespace(app=app, client=client, ids=ids, tokens=tokens, cookies=cookies,
                              headers=lambda key: {'Authorization': f'Bearer {tokens[key]}'})
    if server is not None:
        with server.connect() as connection: connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        server.dispose()


def upload(api, key='one'):
    image = io.BytesIO(); Image.new('RGB', (400, 300), 'white').save(image, format='JPEG')
    response = api.client.post('/passports', files={'file': ('specimen.jpg', image.getvalue(), 'image/jpeg')},
                               headers=api.headers(key))
    assert response.status_code == 201
    return response.json()['id']


def review_fields():
    return dict(surname='SPECIMEN', given_names='TEST', document_number='TEST0001', nationality='LBN',
                issuing_country='LBN', birth_date='1990-01-01', sex='X', expiry_date='2030-01-01', personal_number='')


def deletion_data(api, key='one'):
    return {'confirmation': 'DELETE', 'expected_traveler_id': api.ids[key], 'password': PASSWORD}


def test_application_registry_and_dashboard_show_real_owner_scoped_data(api):
    draft = api.client.post('/applications', headers=api.headers('one'), json={
        'destination': 'SCHENGEN', 'visa_type': 'short_stay'})
    assert draft.status_code == 201 and draft.json()['status'] == 'DRAFT'
    app_id = draft.json()['id']
    assert api.client.get(f'/applications/{app_id}', headers=api.headers('two')).status_code == 404
    assert api.client.get('/applications', headers=api.headers('two')).json() == []
    assert len(api.client.get('/applications', headers=api.headers('one')).json()) == 1
    with Session(api.app.state.engine) as session:
        for status in APPLICATION_STATUSES[1:]:
            session.add(Application(id=uuid4().hex, traveler_id=api.ids['two'], destination='SCHENGEN',
                questionnaire_id='schengen-short-stay', questionnaire_version=1, visa_type='short_stay', status=status))
        session.commit()
    response = api.client.get('/admin/monitoring', headers=api.headers('admin'))
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['applications_by_status'] == {status: 1 for status in APPLICATION_STATUSES}
    assert response.json()['total_applications'] == len(APPLICATION_STATUSES)
    assert response.json()['agent_failures_available'] is False
    assert not {'traveler_id', 'email', 'destination'} & set(response.json())


def test_dashboard_errors_are_newest_first_bounded_and_do_not_return_identifiers(api):
    with Session(api.app.state.engine) as session:
        for index in range(4):
            session.add(ActivityEvent(traveler_id=api.ids['one'], event_type='sign_in',
                identifier='secret-user@example.com', outcome='failure',
                occurred_at=datetime.now(timezone.utc) + timedelta(seconds=index)))
        session.commit()
    reply = api.client.get('/admin/monitoring?limit=2', headers=api.headers('admin'))
    errors = reply.json()['recent_errors']
    assert len(errors) == 2 and errors[0]['id'] > errors[1]['id']
    assert 'secret-user' not in reply.text
    for query in ('limit=0', 'limit=101'):
        assert api.client.get(f'/admin/monitoring?{query}', headers=api.headers('admin')).status_code == 422


def test_every_passport_content_read_is_audited_and_owner_cannot_forge_history(api, monkeypatch):
    upload_id = upload(api)
    monkeypatch.setattr('app.passport.router.extract_passport', lambda image, reader: Extraction(status=ExtractionStatus.UNREADABLE))
    headers = api.headers('one')
    assert api.client.get(f'/passports/{upload_id}/image', headers=headers).status_code == 200
    assert api.client.post(f'/passports/{upload_id}/extract', headers=headers).status_code == 200
    assert api.client.put(f'/passports/{upload_id}/review', headers=headers, json=review_fields()).status_code == 200
    assert api.client.get(f'/passports/{upload_id}/review', headers=headers).status_code == 200
    api.app.state.passport_storage.latest_review(api.ids['one'])
    response = api.client.get('/activity/documents', headers=headers)
    assert response.headers['cache-control'] == 'no-store'
    rows = response.json()['items']
    assert [row['purpose'] for row in rows] == ['assistant_context', 'review_read', 'review_update', 'extraction', 'image_view']
    assert all(row['actor_id'] == api.ids['one'] and row['accessor'] == 'You' for row in rows)
    assert 'TEST0001' not in response.text
    assert api.client.get('/activity/documents', headers=api.headers('two')).json()['total'] == 0
    assert api.client.get(f'/passports/{upload_id}/image', headers=api.headers('two')).status_code == 404
    assert api.client.get('/activity/documents?traveler_id=1', headers=headers).status_code == 422
    assert api.client.post('/activity/events', headers=headers, json={
        'event_type': 'document_access', 'page': 'passport', 'outcome': 'success'}).status_code == 422
    assert api.client.get('/activity/documents?page_size=1&page=2', headers=headers).json()['items'][0]['purpose'] == 'review_read'


def test_audit_failure_blocks_passport_content(api, monkeypatch):
    upload_id = upload(api)
    def failed(*args):
        raise OperationalError('metadata only', None, Exception('private details'))
    monkeypatch.setattr('app.main.record_document_access', failed)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.get(f'/passports/{upload_id}/image', headers=api.headers('one'))
        assert response.status_code == 500 and 'private details' not in response.text
        errors = client.get('/admin/monitoring', headers=api.headers('admin')).json()['recent_errors']
        assert errors[0]['event_type'] == 'api_error'
        assert errors[0]['source'] == '/passports/{upload_id}/image'


def test_delete_account_removes_all_related_rows_files_and_invalidates_both_tokens(api):
    upload_id = upload(api)
    assert api.client.get(f'/passports/{upload_id}/image', headers=api.headers('one')).status_code == 200
    owner = api.ids['one']
    with Session(api.app.state.engine) as session:
        session.add(TravelerProfile(traveler_id=owner, surname='SPECIMEN'))
        session.add(GoogleIdentity(subject='synthetic-google-sub', traveler_id=owner))
        session.add(PasswordResetChallenge(traveler_id=owner, nonce='n', code_digest='digest', expires_at=int(time.time()) + 90))
        session.add(PasswordResetToken(token_hash='test-grant', traveler_id=owner, expires_at=int(time.time()) + 90))
        application_id = uuid4().hex
        session.add(Application(id=application_id, traveler_id=owner, destination='SCHENGEN',
            questionnaire_id='schengen-short-stay', questionnaire_version=1, visa_type='short_stay'))
        session.flush()
        session.add(ApplicationAnswer(application_id=application_id, question_id='main_destination',
            value='FR', source='traveler'))
        session.commit()
    response = api.client.request('DELETE', '/auth/account', json=deletion_data(api), headers=api.headers('one'))
    assert response.status_code == 204 and response.headers['cache-control'] == 'no-store'
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert not (api.app.state.passport_storage.root / str(owner)).exists()
    assert not (api.app.state.activity_directory / str(owner)).exists()
    with Session(api.app.state.engine) as session:
        assert session.get(Traveler, owner) is None
        for model in (TravelerProfile, ActivityEvent, GoogleIdentity, PasswordResetToken, PasswordResetChallenge,
                      AuthSession, Application, DocumentAccess, AccountErasure):
            assert not session.exec(select(model).where(model.traveler_id == owner)).all(), model
        assert not session.exec(select(ApplicationAnswer).where(ApplicationAnswer.application_id == application_id)).all()
        assert session.get(Traveler, api.ids['two']) is not None
    assert api.client.get('/auth/me', headers=api.headers('one')).status_code == 401
    api.client.cookies.set(COOKIE_NAME, api.cookies['one'], domain='testserver.local', path='/auth')
    assert api.client.post('/auth/refresh').status_code == 401
    assert api.client.post('/auth/login', json={'email': 'one@example.com', 'password': PASSWORD}).status_code == 401


@pytest.mark.parametrize('change,status', [({'password': 'wrong'}, 403), ({'confirmation': 'delete'}, 422),
    ({'expected_traveler_id': 999}, 409), ({'role': 'admin'}, 422)])
def test_deletion_requires_exact_confirmation_current_identity_and_password(api, change, status):
    response = api.client.request('DELETE', '/auth/account', json={**deletion_data(api), **change}, headers=api.headers('one'))
    assert response.status_code == status
    assert api.client.get('/auth/me', headers=api.headers('one')).status_code == 200


def test_deletion_refuses_cookie_from_a_different_signed_in_account(api):
    api.client.cookies.set(COOKIE_NAME, api.cookies['two'], domain='testserver.local', path='/auth')
    reply = api.client.request('DELETE', '/auth/account', json=deletion_data(api), headers=api.headers('one'))
    assert reply.status_code == 409
    assert api.client.get('/auth/me', headers=api.headers('one')).status_code == 200
    assert api.client.get('/auth/me', headers=api.headers('two')).status_code == 200


def test_failed_filesystem_cleanup_is_durable_blocks_reactivation_and_can_be_retried(api, monkeypatch):
    upload(api)
    from app.privacy import remove_owner_folder
    monkeypatch.setattr('app.privacy.remove_owner_folder', lambda *args: (_ for _ in ()).throw(OSError('do not leak path')))
    response = api.client.request('DELETE', '/auth/account', json=deletion_data(api), headers=api.headers('one'))
    assert response.status_code == 202 and response.json()['status'] == 'pending'
    assert 'do not leak' not in response.text
    assert api.client.get('/auth/me', headers=api.headers('one')).status_code == 401
    assert api.client.post(f"/admin/users/{api.ids['one']}/reactivate", headers=api.headers('admin')).status_code == 409
    assert api.client.get('/admin/monitoring', headers=api.headers('admin')).json()['pending_erasures'] == 1
    monkeypatch.setattr('app.privacy.remove_owner_folder', remove_owner_folder)
    assert retry_erasures(api.app.state.engine, api.app.state.passport_storage,
                         api.app.state.activity_directory, api.app.state.auth_settings.jwt_secret) == 0
    with Session(api.app.state.engine) as session:
        assert session.get(Traveler, api.ids['one']) is None


def test_admin_delete_is_role_gated_and_cannot_delete_admin_or_self(api):
    target = api.ids['one']
    data = {'confirmation': 'DELETE', 'expected_user_id': target}
    for key, expected in [('one', 403), ('support', 403), ('admin', 204)]:
        response = api.client.request('DELETE', f'/admin/users/{target}', json=data, headers=api.headers(key))
        assert response.status_code == expected
    assert api.client.get('/auth/me', headers=api.headers('one')).status_code == 401
    response = api.client.request('DELETE', f"/admin/users/{api.ids['admin']}", headers=api.headers('admin'),
                                 json={'confirmation': 'DELETE', 'expected_user_id': api.ids['admin']})
    assert response.status_code == 409
    assert api.client.request('DELETE', '/auth/account', json=deletion_data(api, 'admin'), headers=api.headers('admin')).status_code == 409


def test_google_only_deletion_verifies_connected_subject(api, monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'synthetic.apps.googleusercontent.com')
    api.app.state.auth_settings = api.app.state.auth_settings.__class__(**{
        **vars(api.app.state.auth_settings), 'google_client_id': 'synthetic.apps.googleusercontent.com'})
    with Session(api.app.state.engine) as session:
        owner = session.get(Traveler, api.ids['one']); owner.auth_type = 'google'; owner.password_hash = ''
        session.add(owner); session.add(GoogleIdentity(subject='owned-subject', traveler_id=owner.id)); session.commit()
    data = {**deletion_data(api), 'google_id_token': 'synthetic'}
    monkeypatch.setattr('app.privacy.verify_google_token', lambda *args: {'sub': 'different-subject'})
    assert api.client.request('DELETE', '/auth/account', json=data, headers=api.headers('one')).status_code == 403
    monkeypatch.setattr('app.privacy.verify_google_token', lambda *args: {'sub': 'owned-subject'})
    assert api.client.request('DELETE', '/auth/account', json=data, headers=api.headers('one')).status_code == 204


def test_all_private_endpoints_reject_anonymous_requests_before_body_validation(api):
    public = {'/auth/register', '/auth/login', '/auth/config', '/auth/google', '/auth/refresh', '/auth/logout',
              '/auth/forgot-password', '/auth/verify-reset-code', '/auth/reset-password',
              '/health/live', '/health/ready'}
    for route in iter_route_contexts(api.app.routes):
        if route.path in public or not hasattr(route, 'dependant'):
            continue
        path = route.path.replace('{upload_id}', 'a' * 32).replace('{user_id}', str(api.ids['two']))
        path = path.replace('{session_id}', str(uuid4())).replace('{application_id}', 'b' * 32)
        for method in route.methods:
            response = api.client.request(method, path)
            assert response.status_code == 401, (method, path, response.text)


@pytest.mark.parametrize('changes', [{'type': 'refresh'}, {'aud': 'other'}, {'iss': 'other'}, {'exp': 1},
    {'iat': True}, {'exp': '9999999999'}, {'jti': ''}, {'sid': ''}, {'sub': '01'}])
def test_strict_jwt_claims_protect_new_endpoints(api, changes):
    claims = jwt.decode(api.tokens['one'], options={'verify_signature': False})
    forged = jwt.encode({**claims, **changes}, api.app.state.auth_settings.jwt_secret, algorithm='HS256')
    response = api.client.get('/activity/documents', headers={'Authorization': f'Bearer {forged}'})
    assert response.status_code == 401


def test_owner_lock_serializes_independent_workers(tmp_path):
    entered = Event(); release = Event(); second_entered = Event()
    def first():
        with account_lock(tmp_path, 7):
            entered.set(); assert release.wait(3)
    def second():
        with account_lock(tmp_path, 7): second_entered.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(first); assert entered.wait(3)
        two = pool.submit(second)
        assert not second_entered.wait(.1)
        release.set(); one.result(); two.result()
    assert second_entered.is_set()


def test_account_erasure_waits_for_inflight_upload_and_leaves_no_late_files(api, monkeypatch):
    entered, release = Event(), Event()
    save = api.app.state.passport_storage.save
    def slow_save(*args):
        entered.set(); assert release.wait(5)
        return save(*args)
    monkeypatch.setattr(api.app.state.passport_storage, 'save', slow_save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        uploading = pool.submit(upload, api)
        assert entered.wait(5)
        deleting = pool.submit(api.client.request, 'DELETE', '/auth/account',
                               json=deletion_data(api), headers=api.headers('one'))
        assert not deleting.done()
        release.set()
        uploading.result(timeout=5)
        assert deleting.result(timeout=5).status_code == 204
    assert not (api.app.state.passport_storage.root / str(api.ids['one'])).exists()
    assert not (api.app.state.activity_directory / str(api.ids['one'])).exists()


def test_database_cleanup_failure_preserves_durable_task_and_startup_retries(api, monkeypatch):
    from app.privacy import complete_erasure
    def failure(session, owner_id, *args):
        from sqlalchemy import delete
        session.execute(delete(ActivityEvent).where(ActivityEvent.traveler_id == owner_id))
        raise OperationalError('test failure', None, Exception('private path'))
    monkeypatch.setattr('app.privacy.complete_erasure', failure)
    response = api.client.request('DELETE', '/auth/account', json=deletion_data(api), headers=api.headers('one'))
    assert response.status_code == 202
    with Session(api.app.state.engine) as session:
        assert session.get(AccountErasure, api.ids['one']) is not None
        assert session.get(Traveler, api.ids['one']).status == 'suspended'
        assert session.exec(select(ActivityEvent).where(ActivityEvent.traveler_id == api.ids['one'])).first() is not None
    monkeypatch.setattr('app.privacy.complete_erasure', complete_erasure)
    with TestClient(api.app) as restarted:
        assert restarted.get('/auth/me', headers=api.headers('one')).status_code == 401
        with Session(api.app.state.engine) as session:
            assert session.get(Traveler, api.ids['one']) is None
            assert session.get(AccountErasure, api.ids['one']) is None


def test_migration_preserves_existing_users_and_has_no_schema_drift(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{tmp_path / 'migrate.db'}")
    engine = build_engine()
    try:
        config = migration_config(); command.upgrade(config, 'b14ab372b1d2')
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO traveler (id,name,email,password_hash,auth_type) VALUES (41,'Kept','kept@example.com','hash','email_password')"))
        command.upgrade(config, 'head')
        with engine.connect() as connection:
            assert connection.execute(text('SELECT name FROM traveler WHERE id=41')).scalar_one() == 'Kept'
            assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []
        command.downgrade(config, 'b14ab372b1d2'); command.upgrade(config, 'head')
    finally: engine.dispose()


def test_monitoring_scrubs_everything_except_explicit_metadata():
    source = {'event_id': 'test-event', 'message': 'password', 'request': {'headers': {'Authorization': 'secret'}},
              'user': {'email': 'private@example.com'}, 'exception': {'values': [{'value': 'passport number'}]},
              'breadcrumbs': ['secret'], 'tags': {'component': 'backend', 'request_id': 'safe-id', 'token': 'secret'}}
    result = scrub_event(source, {})
    assert result == {'event_id': 'test-event', 'message': 'Taasheera service error',
                      'tags': {'component': 'backend', 'request_id': 'safe-id'}}
    assert not any(value in json.dumps(result) for value in ('password', 'passport number', 'secret', 'private@example.com'))


def test_sentry_sdk_sends_only_sanitized_envelope_through_offline_transport(monkeypatch):
    import sentry_sdk
    from sentry_sdk.transport import Transport
    envelopes = []
    class MemoryTransport(Transport):
        def capture_envelope(self, envelope): envelopes.append(envelope)
    real_init = sentry_sdk.init
    monkeypatch.setattr(sentry_sdk, 'init', lambda **kwargs: real_init(**kwargs, transport=MemoryTransport))
    monkeypatch.setenv('SENTRY_DSN', 'https://public@sentry.example.com/1')
    guard = configure_monitoring()
    try:
        sentry_sdk.set_user({'email': 'private@example.com'})
        sentry_sdk.add_breadcrumb(message='private passport')
        sentry_sdk.capture_exception(ValueError('credential-secret'))
        assert len(envelopes) == 1
        payload = envelopes[0].items[0].get_event()
        assert payload['message'] == 'Taasheera service error'
        assert not any(word in json.dumps(payload) for word in ('private', 'credential-secret', 'ValueError'))
    finally:
        guard.close()
        sentry_sdk.set_user(None)


def test_private_error_responses_are_not_cacheable(api):
    reply = api.client.request('DELETE', '/auth/account', headers=api.headers('one'),
                              json={**deletion_data(api), 'password': 'incorrect'})
    assert reply.status_code == 403 and reply.headers['cache-control'] == 'no-store'
    reply = api.client.get('/applications/missing', headers=api.headers('one'))
    assert reply.status_code == 404 and reply.headers['cache-control'] == 'no-store'


def test_uptime_retries_and_alert_payload_exclude_private_url():
    calls = []
    class Reply:
        status = 200
        def read(self, size): return b'{"status":"ok"}'
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def healthy(request, timeout): calls.append(request); return Reply()
    assert check_uptime('http://127.0.0.1:8000/health/ready', opener=healthy)
    assert len(calls) == 1
    calls.clear()
    def failure(request, timeout): calls.append(request); raise OSError('private credential in error')
    assert not check_uptime('https://example.com/health/ready', opener=failure)
    assert len(calls) == 3
    alert_team('https://example.com/private-hook', opener=healthy)
    assert b'private-hook' not in calls[-1].data and b'Taasheera' in calls[-1].data
    with pytest.raises(ValueError): check_uptime('https://user:secret@example.com/health/ready')
