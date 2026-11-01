import os
import dev
import preview


def test_preview_has_separate_config_data_and_persistent_signing_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    private = tmp_path / '.env.local'
    private.write_text('JWT_SECRET=original-existing-value\n')
    public = tmp_path / '.env.development'
    public.write_text('GOOGLE_CLIENT_ID=synthetic.apps.googleusercontent.com\n')
    original_database = tmp_path / 'original.db'; original_database.write_bytes(b'existing-data')
    monkeypatch.setattr(preview, 'DATA', tmp_path / 'preview')
    monkeypatch.setattr(dev, 'PRIVATE_CONFIG', private)
    monkeypatch.setattr(dev, 'PUBLIC_CONFIG', public)
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{original_database}')
    monkeypatch.setenv('JWT_SECRET', 'original-production-secret')
    monkeypatch.setenv('SENTRY_DSN', 'https://public@example.com/1')
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-never-send')
    preview.configure(8100, 5273)
    first_secret = os.environ['JWT_SECRET']
    assert first_secret != 'original-production-secret'
    assert 'preview/preview.db' in os.environ['DATABASE_URL']
    assert os.environ['SENTRY_DSN'] == '' and 'GEMINI_API_KEY' not in os.environ
    assert os.environ['AUTH_ALLOWED_ORIGINS'] == 'http://127.0.0.1:5273,http://127.0.0.1:8100,http://localhost:5273,http://localhost:8100'
    preview.configure(8100, 5273)
    assert os.environ['JWT_SECRET'] == first_secret
    assert private.read_text() == 'JWT_SECRET=original-existing-value\n'
    assert original_database.read_bytes() == b'existing-data'


def test_free_ports_targets_only_requested_listeners(monkeypatch):
    from types import SimpleNamespace
    import psutil
    monkeypatch.setattr(psutil, 'net_connections', lambda **kwargs: [
        SimpleNamespace(pid=11, status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=5173)),
        SimpleNamespace(pid=22, status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=9999))])
    terminated = []
    class Process:
        def __init__(self, pid): self.pid = pid
        def terminate(self): terminated.append(self.pid)
        def wait(self, timeout): pass
    monkeypatch.setattr(psutil, 'Process', Process)
    preview.prepare_ports([], free_ports=True)
    assert terminated == []
    # Bind checks are left to the OS; port 0 obtains a free disposable port.
    preview.prepare_ports([0], free_ports=True)
    assert terminated == []
    bound = []
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def setsockopt(self, *args): pass
        def bind(self, address): bound.append(address)
    monkeypatch.setattr(preview.socket, 'socket', Socket)
    preview.prepare_ports([5173], free_ports=True)
    assert terminated == [11]
    assert bound == [('127.0.0.1', 5173)]


def test_free_ports_accepts_exited_zombie_once_its_socket_is_released(monkeypatch):
    from types import SimpleNamespace
    import psutil
    monkeypatch.setattr(psutil, 'net_connections', lambda **kwargs: [
        SimpleNamespace(pid=11, status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=5173))])
    class Zombie:
        pid = 11
        def terminate(self): pass
        def wait(self, timeout): raise psutil.TimeoutExpired(timeout)
        def status(self): return psutil.STATUS_ZOMBIE
        def kill(self): raise AssertionError('Exited process needs no further signals')
    class ReleasedSocket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def setsockopt(self, *args): pass
        def bind(self, address): assert address == ('127.0.0.1', 5173)
    monkeypatch.setattr(psutil, 'Process', lambda pid: Zombie())
    monkeypatch.setattr(preview.socket, 'socket', ReleasedSocket)
    preview.prepare_ports([5173], free_ports=True)
