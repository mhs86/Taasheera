import base64
import gzip
import importlib.util
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'deploy/aws' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


worker = load('install_public_policies')
publisher = load('publish_public_policies')
HOME = b'<!doctype html><html><head><title>Current app</title></head><body><div id="root"></div><script type="module" src="/assets/current-abc123.js"></script></body></html>'


def assets():
    return {name: (ROOT / 'frontend/public' / name).read_bytes() for name in worker.ASSETS}


class Files:
    def __init__(self):
        self.data = {'index.html': HOME, 'privacy.html': b'Previous privacy notice', 'legal.css': b'Previous CSS'}
        self.reads, self.writes = [], []
    def read(self, name): self.reads.append(name); return self.data.get(name)
    def write(self, name, content): self.writes.append(name); self.data[name] = content
    def remove(self, name): self.data.pop(name, None)


def test_homepage_patch_preserves_existing_app_assets_and_is_idempotent():
    updated = worker.patch_homepage(HOME)
    assert b'<div id="root"></div>' in updated
    assert re.findall(rb'<script.*?</script>', updated) == re.findall(rb'<script.*?</script>', HOME)
    assert updated.count(worker.START.encode()) == 1
    assert b'href="/privacy.html"' in updated and b'href="/terms.html"' in updated
    assert worker.patch_homepage(updated) == updated
    assert worker.patch_homepage(worker.patch_homepage((ROOT / 'frontend/index.html').read_bytes())) == worker.patch_homepage((ROOT / 'frontend/index.html').read_bytes())


def test_google_public_verification_tag_is_added_once_and_preserves_other_owners():
    existing = HOME.replace(b'</head>', b'<meta name="google-site-verification" content="another-owner" /></head>')
    updated = worker.patch_homepage(existing, 'public-verification-value-1234')
    assert b'content="another-owner"' in updated
    assert updated.count(b'id="taasheera-google-site-verification"') == 1
    assert worker.patch_homepage(updated, 'public-verification-value-1234') == updated
    assert b'content="updated-verification-value"' in worker.patch_homepage(updated, 'updated-verification-value')


def test_verification_tag_cannot_inject_html_or_shell_commands():
    for invalid in ('<script>bad</script>', 'token" onclick="bad', '$(command)', ''):
        with pytest.raises(ValueError): worker.patch_homepage(HOME, invalid)
        with pytest.raises(ValueError): publisher.make_command('https://d3vh2ppjrlwxee.cloudfront.net', invalid)


@pytest.mark.parametrize('content', [b'not an HTML document', HOME + worker.START.encode(), HOME + (worker.START + worker.END).encode() * 2])
def test_ambiguous_or_malformed_homepage_is_refused(content):
    with pytest.raises(ValueError): worker.patch_homepage(content)


def test_public_install_backs_up_only_public_files_and_verifies_after_homepage(tmp_path):
    files = Files(); observed = []
    before = dict(files.data)
    worker.install(files, assets(), tmp_path / 'backup', lambda: observed.append(dict(files.data)))
    assert len(observed) == 1
    assert files.writes == [*worker.ASSETS, 'index.html']
    assert set(files.reads) == set(worker.FILES)
    for name, content in before.items(): assert (tmp_path / 'backup' / name).read_bytes() == content
    assert json.loads((tmp_path / 'backup/manifest.json').read_text())['terms.html'] is None


def test_failed_public_verification_restores_previous_files_and_removes_new_ones(tmp_path):
    files = Files(); before = dict(files.data)
    def failed(): raise RuntimeError('simulated CDN failure')
    with pytest.raises(RuntimeError, match='previous public files were restored'):
        worker.install(files, assets(), tmp_path / 'backup', failed)
    assert files.data == before


def test_partial_public_file_copy_failure_also_rolls_back(tmp_path):
    files = Files(); before = dict(files.data); write = files.write; failed = False
    def flaky(name, content):
        nonlocal failed
        if name == 'terms.html' and not failed:
            failed = True; raise OSError('copy failed')
        write(name, content)
    files.write = flaky
    with pytest.raises(RuntimeError, match='restored'):
        worker.install(files, assets(), tmp_path / 'backup', lambda: None)
    assert files.data == before


def test_unexpected_asset_is_refused_before_any_write(tmp_path):
    files = Files()
    with pytest.raises(ValueError):
        worker.install(files, {**assets(), '../private/app.env': b'bad'}, tmp_path / 'backup', lambda: None)
    assert files.writes == []
    with pytest.raises(ValueError): worker.WebFiles.path(None, '../private/app.env')


class Aws:
    def __init__(self, account=publisher.ACCOUNT): self.account=account; self.calls=[]
    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ('sts', 'get-caller-identity'): return {'Account': self.account}
        if args[:2] == ('cloudformation', 'describe-stacks'):
            return {'Stacks': [{'Outputs': [
                {'OutputKey': 'InstanceId', 'OutputValue': 'i-1234567890abcdef0'},
                {'OutputKey': 'SiteUrl', 'OutputValue': 'https://d3vh2ppjrlwxee.cloudfront.net'}]}]}
        if args[:2] == ('ssm', 'send-command'):
            parameters = json.loads(Path(args[-1].removeprefix('file://')).read_text())
            assert set(parameters) == {'commands', 'executionTimeout'}
            assert 'app.env' not in parameters['commands'][0]
            return {'Command': {'CommandId': 'synthetic-command-id'}}
        if args[:2] == ('ssm', 'list-command-invocations'):
            return {'CommandInvocations': [{'Status': 'Success'}]}
        raise AssertionError(args)


def test_wrong_aws_account_is_refused_before_stack_access_or_publish():
    aws = Aws('000000000000')
    with pytest.raises(ValueError, match='not the documented'): publisher.publish(aws, execute=True)
    assert len(aws.calls) == 1


def test_plan_does_not_send_any_remote_command():
    aws = Aws(); publisher.publish(aws)
    assert len(aws.calls) == 2
    assert all(call[0] != 'ssm' for call in aws.calls)


def test_execute_uses_existing_instance_and_ssm_without_releasing_application():
    aws = Aws(); publisher.publish(aws, execute=True, sleep=lambda _: None)
    sent = next(call for call in aws.calls if call[:2] == ('ssm', 'send-command'))
    assert sent[3] == 'i-1234567890abcdef0'
    assert {call[0] for call in aws.calls} == {'sts', 'cloudformation', 'ssm'}


def test_ssm_payload_contains_exact_public_assets_and_worker_under_size_limit():
    command, digest = publisher.make_command('https://d3vh2ppjrlwxee.cloudfront.net')
    packed = re.search(r"b64decode\('([^']+)'\)", command)[1]
    payload = json.loads(gzip.decompress(base64.b64decode(packed)))
    assert set(payload['assets']) == set(worker.ASSETS)
    assert payload['bundle_sha256'] == digest
    assert payload['worker'] == (ROOT / 'deploy/aws/install_public_policies.py').read_text()
    for name, content in payload['assets'].items(): assert base64.b64decode(content) == assets()[name]
    assert len(command.encode()) <= 24000
