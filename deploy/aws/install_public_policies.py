"""SSM worker: publish public files only, preserving the running app and its settings."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request


ASSETS = ("privacy.html", "terms.html", "legal.css")
FILES = (*ASSETS, "index.html")
START = "<!-- taasheera-public-policies:start -->"
END = "<!-- taasheera-public-policies:end -->"
FOOTER = """<!-- taasheera-public-policies:start -->
    <footer class="public-policies" aria-label="Taasheera policies">
      <p>Taasheera helps you prepare visa application information. Google Sign-In is used to authenticate your account.</p>
      <nav aria-label="Policies"><a href="/privacy.html">Privacy policy</a><a href="/terms.html">Terms of Service</a><a href="mailto:sharafm032@gmail.com">Contact</a></nav>
    </footer>
    <!-- taasheera-public-policies:end -->"""
STYLESHEET = '<link id="taasheera-policy-styles" rel="stylesheet" href="/legal.css" />'


def patch_homepage(original: bytes, google_token=None) -> bytes:
    html = original.decode("utf-8")
    if html.count(START) != html.count(END) or html.count(START) > 1:
        raise ValueError("Homepage policy markers are ambiguous.")
    if not re.search(r"</head\s*>", html, re.I) or not re.search(r"</body\s*>", html, re.I):
        raise ValueError("Homepage is not a complete HTML document.")
    html = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: FOOTER, html, flags=re.S)
    if START not in html:
        html = re.sub(r"</body\s*>", lambda match: FOOTER + "\n" + match[0], html, count=1, flags=re.I)
    if 'id="taasheera-policy-styles"' not in html:
        html = re.sub(r"</head\s*>", lambda match: STYLESHEET + "\n" + match[0], html, count=1, flags=re.I)
    if google_token is not None:
        if not isinstance(google_token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,300}", google_token):
            raise ValueError("Use the public HTML-tag verification content from Google Search Console.")
        tag = '<meta id="taasheera-google-site-verification" name="google-site-verification" content="' + google_token + '" />'
        pattern = r'<meta\b[^>]*\bid=[\"\x27]taasheera-google-site-verification[\"\x27][^>]*>'
        if re.search(pattern, html, re.I):
            html = re.sub(pattern, lambda _: tag, html, count=1, flags=re.I)
        else:
            html = re.sub(r"</head\s*>", lambda match: tag + "\n" + match[0], html, count=1, flags=re.I)
    return html.encode("utf-8")


class WebFiles:
    """Only the running Compose web container and these four public filenames."""
    def __init__(self):
        result = subprocess.run(["docker", "ps", "--filter", "label=com.docker.compose.project=taasheera",
            "--filter", "label=com.docker.compose.service=web", "--format", "{{.ID}}"],
            check=True, capture_output=True, text=True)
        ids = result.stdout.split()
        if len(ids) != 1 or not re.fullmatch(r"[0-9a-f]{12,64}", ids[0]):
            raise RuntimeError("Expected exactly one running Taasheera web container.")
        self.container = ids[0]

    def path(self, name):
        if name not in FILES:
            raise ValueError("Only public policy files and the homepage may be changed.")
        return "/usr/share/nginx/html/" + name

    def read(self, name):
        path = self.path(name)
        exists = subprocess.run(["docker", "exec", self.container, "test", "-f", path], capture_output=True)
        if exists.returncode == 1:
            return None
        exists.check_returncode()
        return subprocess.run(["docker", "exec", self.container, "cat", path],
                              check=True, capture_output=True).stdout

    def write(self, name, content):
        destination = self.path(name)
        temporary = destination + ".taasheera-policy-new"
        with tempfile.TemporaryDirectory(prefix="taasheera-public-file-") as folder:
            local = Path(folder) / name
            local.write_bytes(content)
            local.chmod(0o644)
            subprocess.run(["docker", "cp", str(local), self.container + ":" + temporary],
                           check=True, capture_output=True)
        subprocess.run(["docker", "exec", self.container, "sh", "-c",
            'chmod 0644 "$1" && mv -f "$1" "$2"', "sh", temporary, destination], check=True, capture_output=True)

    def remove(self, name):
        subprocess.run(["docker", "exec", self.container, "rm", "-f", self.path(name)],
                       check=True, capture_output=True)


def verify_public_site(origin, *, google_token=None, attempts=6, delay=3):
    expected = {"/privacy.html": b"<h1>Privacy policy</h1>",
                "/terms.html": b"<h1>Terms of Service</h1>",
                "/legal.css": b".legal-page", "/": START.encode()}
    for attempt in range(attempts):
        try:
            for route, marker in expected.items():
                with urllib.request.urlopen(origin + route, timeout=12) as response:
                    content = response.read(250000)
                    if response.status != 200 or marker not in content:
                        raise ValueError("Public policy content was not served.")
                    if route == "/" and google_token is not None and (
                            'content="' + google_token + '"').encode() not in content:
                        raise ValueError("Google ownership verification tag was not served.")
            with urllib.request.urlopen(origin + "/health/ready", timeout=12) as response:
                if response.status != 200 or json.load(response).get("status") != "ok":
                    raise ValueError("Existing service readiness did not pass.")
            return
        except (OSError, ValueError):
            if attempt + 1 == attempts:
                raise RuntimeError("Public policy/readiness verification failed.") from None
            time.sleep(delay)


def install(files, assets, backup: Path, verify, *, google_token=None):
    if set(assets) != set(ASSETS) or any(not isinstance(content, bytes) for content in assets.values()):
        raise ValueError("Expected exactly the three public policy assets.")
    previous = {name: files.read(name) for name in FILES}
    if previous["index.html"] is None:
        raise ValueError("The existing homepage is missing.")
    replacement = {**assets, "index.html": patch_homepage(previous["index.html"], google_token)}
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {}
    for name, content in previous.items():
        manifest[name] = hashlib.sha256(content).hexdigest() if content is not None else None
        if content is not None:
            (backup / name).write_bytes(content)
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    changed = []
    try:
        for name, content in replacement.items():
            changed.append(name)
            files.write(name, content)
        verify()
    except Exception:
        failed = False
        for name in reversed(changed):
            try:
                if previous[name] is None:
                    files.remove(name)
                else:
                    files.write(name, previous[name])
            except Exception:
                failed = True
        if failed:
            raise RuntimeError("Publishing failed and rollback needs recovery from the public-file backup.") from None
        raise RuntimeError("Publishing failed; previous public files were restored.") from None


def main():
    payload = json.loads(Path(sys.argv[1]).read_text())
    assets = {name: base64.b64decode(value, validate=True) for name, value in payload["assets"].items()}
    origin = payload["site_url"]
    backup = Path("/srv/taasheera/public-policy-backups") / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + payload["bundle_sha256"][:12])
    google_token = payload.get("google_verification")
    install(WebFiles(), assets, backup, lambda: verify_public_site(origin, google_token=google_token), google_token=google_token)
    print("Published privacy.html, terms.html and legal.css; linked them from the existing homepage.")
    print("Public-file backup:", str(backup))
    print("The API, database, private files, cookies and environment settings were not redeployed or changed.")


if __name__ == "__main__":
    main()
