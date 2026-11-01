"""Exercise deployment orchestration without rebuilding or stopping a real service."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[2] / 'deploy/aws/build_images.py'


@pytest.fixture
def builder():
    spec = importlib.util.spec_from_file_location('production_builder', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runner(replies, calls):
    def run(command, **kwargs):
        calls.append((command, kwargs['env']))
        code, text = replies.pop(0)
        kwargs['stdout'].write(text)
        return SimpleNamespace(returncode=code)
    return run


def test_builds_only_api_then_web_and_keeps_inherited_settings(builder, tmp_path, monkeypatch):
    monkeypatch.setenv('COMPOSE_BAKE', 'true')
    monkeypatch.setenv('TEST_BUILD_SENTINEL', 'synthetic-value')
    calls, replies = [], [(0, 'Backend built'), (0, 'Web built')]
    builder.build_images(tmp_path / 'logs', run=runner(replies, calls))
    assert [command[-2:] for command, _ in calls] == [['build', 'api'], ['build', 'web']]
    assert all(env['COMPOSE_BAKE'] == 'false' and env['COMPOSE_PARALLEL_LIMIT'] == '1' for _, env in calls)
    assert all(env['TEST_BUILD_SENTINEL'] == 'synthetic-value' for _, env in calls)
    assert os.environ['COMPOSE_BAKE'] == 'true'  # Scoped to build child processes.
    assert all(log.stat().st_mode & 0o777 == 0o600 for log in (tmp_path / 'logs').iterdir())


def test_disconnected_session_retries_only_that_image_once_and_then_continues(builder, tmp_path):
    calls, delays = [], []
    replies = [(1, 'DeadlineExceeded: no active session for synthetic: context deadline exceeded'),
               (0, 'Backend built'), (0, 'Web built')]
    builder.build_images(tmp_path, run=runner(replies, calls), sleep=delays.append)
    assert [command[-1] for command, _ in calls] == ['api', 'api', 'web']
    assert delays == [5]
    assert (tmp_path / 'api-1.log').exists() and (tmp_path / 'api-2.log').exists()


@pytest.mark.parametrize('failure', ['package missing', 'No space left on device', 'Killed: out of memory',
                                   'TLS certificate verification failed'])
def test_real_build_failure_stops_without_retries_or_container_operations(builder, tmp_path, failure):
    calls = []
    with pytest.raises(RuntimeError, match='existing services were not stopped'):
        builder.build_images(tmp_path, run=runner([(1, failure)], calls),
                             sleep=lambda _: pytest.fail('Unexpected retry'))
    assert len(calls) == 1 and calls[0][0][-2:] == ['build', 'api']


def test_repeat_session_failure_is_bounded_and_never_starts_web_build(builder, tmp_path):
    calls = []
    with pytest.raises(RuntimeError):
        builder.build_images(tmp_path, run=runner([(1, 'no active session for x'),
            (1, 'no active session for y')], calls), sleep=lambda _: None)
    assert [command[-1] for command, _ in calls] == ['api', 'api']


def test_web_failure_does_not_rebuild_backend_or_run_migrations(builder, tmp_path):
    calls = []
    with pytest.raises(RuntimeError):
        builder.build_images(tmp_path, run=runner([(0, 'API built'), (1, 'compile failed')], calls))
    assert [command[-2:] for command, _ in calls] == [['build', 'api'], ['build', 'web']]
