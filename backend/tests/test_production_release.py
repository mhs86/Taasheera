"""Release guardrails: preserve private config and verify both client/API versions."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

AWS = Path(__file__).resolve().parents[2] / "deploy/aws"


@pytest.fixture
def release(monkeypatch):
    monkeypatch.syspath_prepend(str(AWS))
    spec = importlib.util.spec_from_file_location("production_release", AWS / "release_production.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_release_preserves_exact_private_config_and_requires_existing_files(tmp_path):
    # Run the production configuration step with synthetic private files. This
    # catches a future rewrite of OAuth/SES/secrets even if the release is healthy.
    source = (AWS / "bootstrap.sh").read_text()
    start = source.index('if [ "${TAASHEERA_PRESERVE_CONFIG:-0}" = 1 ]; then')
    end = source.index('# Resolve the image', start)
    script = source[start:end].replace('/srv/taasheera/private', str(tmp_path / 'private'))
    script = script.replace('/etc/taasheera', str(tmp_path / 'etc'))
    private, etc = tmp_path / 'private', tmp_path / 'etc'
    private.mkdir(); etc.mkdir()
    for filename in ['app.env', 'web.env']:
        path = private / filename
        path.write_bytes(b'CUSTOM=keep-this-exactly\nSECRET=synthetic-only\n')
        path.chmod(0o600)
        (etc / filename).symlink_to(path)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in private.iterdir()}
    subprocess.run(['bash', '-ec', 'TAASHEERA_PRESERVE_CONFIG=1\n' + script], check=True)
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in private.iterdir()} == before
    (private / 'web.env').unlink()
    assert subprocess.run(['bash', '-ec', 'TAASHEERA_PRESERVE_CONFIG=1\n' + script]).returncode != 0
    assert not (private / 'web.env').exists()  # Cannot silently generate missing settings.


def public_responses():
    return {
        '/health/ready': (200, 'application/json', '{"status":"ok"}'),
        '/': (200, 'text/html', '<script src="/assets/app.js"></script><a href="/privacy.html">Privacy</a><a href="/terms.html">Terms</a>'),
        '/assets/app.js': (200, 'text/javascript', 'Staff dashboard /backoffice /apply Link Google and sign in Add an admin'),
        '/auth/google/link-login': (422, 'application/json', '{}'),
        '/admin-api/admins/lookup': (401, 'application/json', '{}'),
        '/admin-api/admins': (401, 'application/json', '{}'),
        '/privacy.html': (200, 'text/html', 'Privacy'), '/terms.html': (200, 'text/html', 'Terms'),
    }


def test_release_checks_features_api_authorization_and_policies_without_mutating_accounts(release, monkeypatch):
    responses, seen = public_responses(), []
    def get(url, data=None):
        path = url.removeprefix('https://travel.example')
        seen.append((path, data))
        return responses[path]
    monkeypatch.setattr(release, 'get', get)
    release.verify('https://travel.example')
    assert [data for _, data in seen if data] == [b'{}', b'{}', b'{}']


@pytest.mark.parametrize('path,replacement', [('/assets/app.js', (200, 'text/javascript', 'old application')),
    ('/admin-api/admins', (200, 'text/html', 'SPA fallback')),
    ('/admin-api/admins/lookup', (200, 'application/json', '{}')),
    ('/privacy.html', (404, 'text/html', 'missing'))])
def test_release_refuses_stale_frontend_missing_policies_and_unprotected_api(release, monkeypatch, path, replacement):
    responses = public_responses(); responses[path] = replacement
    monkeypatch.setattr(release, 'get', lambda url, data=None: responses[url.removeprefix('https://travel.example')])
    with pytest.raises(RuntimeError): release.verify('https://travel.example')


def test_release_plan_is_read_only_and_execution_uses_configuration_preservation(release, monkeypatch):
    monkeypatch.setattr(release, 'revision', lambda: 'a' * 40)
    monkeypatch.setattr(release, 'Aws', lambda **kwargs: object())
    monkeypatch.setattr(release, 'inspect_target', lambda *args: ('i-1234567890abcdef0', 'https://travel.example'))
    calls = []
    monkeypatch.setattr(release.subprocess, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(sys, 'argv', ['release_production.py'])
    release.main()
    assert calls == []
    verified = []
    monkeypatch.setattr(release, 'verify', verified.append)
    monkeypatch.setattr(sys, 'argv', ['release_production.py', '--execute'])
    release.main()
    assert calls[0][1]['env']['TAASHEERA_PRESERVE_CONFIG'] == '1'
    assert verified == ['https://travel.example']


def test_admin_only_plan_and_execution_cannot_redeploy_or_rebuild(release, monkeypatch):
    monkeypatch.setattr(release, 'revision', lambda: 'a' * 40)
    aws = object()
    monkeypatch.setattr(release, 'Aws', lambda **kwargs: aws)
    monkeypatch.setattr(release, 'inspect_target', lambda *args: ('i-1234567890abcdef0', 'https://travel.example'))
    monkeypatch.setattr(release.subprocess, 'run', lambda *args, **kwargs: pytest.fail('Admin-only must not redeploy'))
    monkeypatch.setattr(release, 'verify', lambda *args: pytest.fail('Admin-only must not require a frontend release'))
    grants = []
    monkeypatch.setattr(release, 'promote', lambda *args: grants.append(args))
    monkeypatch.setattr(sys, 'argv', ['release_production.py', '--admin-only', '--admin-email', 'admin@example.com'])
    release.main()
    assert grants == []
    monkeypatch.setattr(sys, 'argv', [*sys.argv, '--execute'])
    release.main()
    assert grants == [(aws, 'i-1234567890abcdef0', 'admin@example.com')]


def test_admin_only_requires_an_explicit_account_before_accessing_aws(release, monkeypatch):
    monkeypatch.setattr(release, 'Aws', lambda **kwargs: pytest.fail('No account was selected'))
    monkeypatch.setattr(sys, 'argv', ['release_production.py', '--admin-only', '--execute'])
    with pytest.raises(SystemExit): release.main()


@pytest.mark.parametrize('google', [False, True])
def test_remote_admin_program_updates_the_existing_account_and_verifies_staff_access(
        release, monkeypatch, tmp_path, capsys, google):
    import bcrypt
    import migrate
    from fastapi.testclient import TestClient
    from sqlmodel import Session, select
    from app.main import create_app
    from app.models import GoogleIdentity, Traveler

    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "admin-role.db"}')
    migrate.upgrade()
    app = create_app()
    email, password = 'operator-target@example.com', 'Synthetic-test-password-123'
    if google:
        monkeypatch.setenv('GOOGLE_CLIENT_ID', 'synthetic.apps.googleusercontent.com')
        monkeypatch.setattr('app.google_auth.verify_google_token', lambda *args: {
            'sub': 'synthetic-operator-subject', 'email': email, 'name': 'Provider name'})
        app = create_app()
    with TestClient(app) as client:
        with Session(app.state.engine) as session:
            target = Traveler(name='Existing target', email=email, auth_type='google' if google else 'email_password',
                password_hash='' if google else bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode())
            session.add(target); session.flush()
            if google: session.add(GoogleIdentity(subject='synthetic-operator-subject', traveler_id=target.id))
            session.commit()
            owner_id, original_hash = target.id, target.password_hash
        signed_in = (client.post('/auth/google', json={'id_token': 'synthetic'}) if google else
                     client.post('/auth/login', json={'email': email, 'password': password}))
        headers = {'Authorization': 'Bearer ' + signed_in.json()['access_token']}
        assert client.get('/admin/me', headers=headers).status_code == 403
        captured = {}
        def aws(*args):
            if args[:2] == ('ssm', 'send-command'):
                parameters = Path(args[args.index('--parameters') + 1].removeprefix('file://'))
                command = json.loads(parameters.read_text())['commands'][0]
                code = command.split("<<'TAASHEERA_ADMIN'\n", 1)[1].rsplit('\nTAASHEERA_ADMIN', 1)[0]
                output = io.StringIO()
                with contextlib.redirect_stdout(output): exec(code, {})
                captured['stdout'] = output.getvalue()
                return {'Command': {'CommandId': 'synthetic-command'}}
            if args[:2] == ('ssm', 'list-command-invocations'):
                return {'CommandInvocations': [{'Status': 'Success'}]}
            if args[:2] == ('ssm', 'get-command-invocation'):
                return {'StandardOutputContent': captured['stdout']}
            pytest.fail('Unexpected AWS call')
        release.promote(aws, 'i-1234567890abcdef0', email.upper())
        assert client.get('/admin/me', headers=headers).status_code == 200  # Same session; no JWT role claims.
        with Session(app.state.engine) as session:
            owners = session.exec(select(Traveler)).all()
            assert len(owners) == 1
            assert owners[0].id == owner_id and owners[0].password_hash == original_hash
            assert owners[0].role == 'admin' and owners[0].status == 'active'
        output = capsys.readouterr().out
        assert 'role=admin, status=active' in output
        assert email not in output and password not in output


@pytest.mark.parametrize('output', ['', 'TAASHEERA_ADMIN_RESULT={"id":1,"role":"traveler","status":"active"}',
    'TAASHEERA_ADMIN_RESULT={"id":1,"role":"admin","status":"suspended"}'])
def test_admin_setup_never_reports_success_without_verified_active_role(release, tmp_path, output):
    def aws(*args):
        if args[:2] == ('ssm', 'send-command'): return {'Command': {'CommandId': 'synthetic-command'}}
        if args[:2] == ('ssm', 'list-command-invocations'): return {'CommandInvocations': [{'Status': 'Success'}]}
        return {'StandardOutputContent': output}
    with pytest.raises(RuntimeError, match='verified active access'):
        release.promote(aws, 'i-1234567890abcdef0', 'admin@example.com')
