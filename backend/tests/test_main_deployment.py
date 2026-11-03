"""Release guards fail before publishing/deploying; image retries cannot replace a SHA."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / "aws" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


publish_images = module("publish_images")
verify_release = module("verify_main_release")
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def test_immutable_images_are_reused_without_build_or_push():
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=json.dumps({"images": [{"imageId": {"imageDigest": DIGEST}}]}))

    images = publish_images.publish(SHA, run=run)
    assert len(calls) == 2 and all(command[:3] == ["aws", "ecr", "batch-get-image"] for command in calls)
    assert images == {f"TAASHEERA_{service.upper()}_IMAGE":
                      f"{publish_images.REGISTRY}/taasheera-ec2-{service}@{DIGEST}" for service in ("api", "web")}


def test_missing_images_are_built_for_the_exact_commit_and_resolved_after_push():
    calls, published = [], set()

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["docker", "push"]:
            published.add(command[-1].split("/")[-1].split(":")[0])
        if command[0] == "aws":
            repository = command[command.index("--repository-name") + 1]
            data = ({"images": [{"imageId": {"imageDigest": DIGEST}}]} if repository in published else
                    {"images": [], "failures": [{"failureCode": "ImageNotFound"}]})
            return SimpleNamespace(stdout=json.dumps(data))
        return SimpleNamespace()

    assert len(publish_images.publish(SHA, run=run)) == 2
    builds = [command for command in calls if command[:2] == ["docker", "build"]]
    assert len(builds) == 2
    assert all(f"org.opencontainers.image.revision={SHA}" in command for command in builds)
    assert all(command[command.index("--platform") + 1] == "linux/amd64" for command in builds)


def test_ecr_failure_does_not_trigger_a_build_or_return_deployment_references():
    def run(command, **kwargs):
        assert command[0] == "aws"
        return SimpleNamespace(stdout=json.dumps({"images": [], "failures": [{"failureCode": "KmsError"}]}))

    with pytest.raises(RuntimeError, match="could not resolve"):
        publish_images.publish(SHA, run=run)


def test_second_image_failure_does_not_emit_a_partial_deployment_pair(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr("sys.argv", ["publish_images.py", SHA])
    env_file = tmp_path / "runner.env"
    monkeypatch.setenv("GITHUB_ENV", str(env_file))

    def failed_publish(revision):
        raise subprocess.CalledProcessError(1, ["docker", "push", "web"])

    monkeypatch.setattr(publish_images, "publish", failed_publish)
    with pytest.raises(subprocess.CalledProcessError):
        publish_images.main()
    assert not env_file.exists()


@pytest.mark.parametrize("revision", ["main", "a" * 39, "a" * 40 + "\n", "$(id)"])
def test_invalid_release_identity_cannot_run_commands(revision):
    def run(*args, **kwargs):
        pytest.fail("Invalid revision ran a command")

    with pytest.raises(ValueError):
        publish_images.publish(revision, run=run)
    with pytest.raises(ValueError):
        verify_release.verify(revision, "mhs86/Taasheera", run=run)


@pytest.mark.parametrize("main,ci_ok,expected", [(SHA, True, None), ("c" * 40, True, "superseded"),
                                                (SHA, False, "no successful")])
def test_only_current_main_with_successful_push_ci_can_deploy(main, ci_ok, expected):
    def run(command, **kwargs):
        if command[-1].endswith("git/ref/heads/main"):
            data = {"object": {"sha": main}}
        else:
            # A green PR run or another commit must never authorize a manual release.
            runs = [{"head_sha": "d" * 40, "head_branch": "main", "event": "push", "conclusion": "success"},
                    {"head_sha": SHA, "head_branch": "main", "event": "pull_request", "conclusion": "success"}]
            if ci_ok:
                runs.append({"head_sha": SHA, "head_branch": "main", "event": "push", "conclusion": "success"})
            data = {"workflow_runs": runs}
        return SimpleNamespace(stdout=json.dumps(data))

    if expected:
        with pytest.raises(RuntimeError, match=expected):
            verify_release.verify(SHA, "mhs86/Taasheera", run=run)
    else:
        verify_release.verify(SHA, "mhs86/Taasheera", run=run)
