"""Release guardrails: preserve private config and verify both client/API versions."""
import importlib.util
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
