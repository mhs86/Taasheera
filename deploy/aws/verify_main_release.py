"""Refuse stale commits or manual deployments without successful main push CI."""
import json
import os
import re
import subprocess
import sys


def verify(revision, repository, *, run=subprocess.run):
    if not re.fullmatch(r"[a-f0-9]{40}", revision) or repository != "mhs86/Taasheera":
        raise ValueError("Invalid release identity.")

    def api(path):
        return json.loads(run(["gh", "api", f"repos/{repository}/{path}"],
                              check=True, capture_output=True, text=True).stdout)

    if api("git/ref/heads/main")["object"]["sha"] != revision:
        raise RuntimeError("This commit has been superseded on main; deploy the latest tested commit.")
    runs = api("actions/workflows/ci.yml/runs?branch=main&event=push&status=success&per_page=100")
    if not any(item["head_sha"] == revision and item["head_branch"] == "main"
               and item["event"] == "push" and item["conclusion"] == "success"
               for item in runs["workflow_runs"]):
        raise RuntimeError("This main commit has no successful push CI run; wait for CI before deploying.")


if __name__ == "__main__":
    verify(sys.argv[1], os.environ["GITHUB_REPOSITORY"])
