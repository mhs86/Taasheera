"""Loopback-only feature preview, isolated from .env.local and the existing database.

python preview.py run --seed-demo --free-ports
python preview.py admin --email your-local-account@example.com
python preview.py retry-erasures
"""
import argparse
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
DATA = BACKEND / "storage" / os.environ.get("TAASHEERA_PREVIEW_NAME", "feature-preview")
if DATA.name != os.environ.get("TAASHEERA_PREVIEW_NAME", "feature-preview") or DATA.name in {".", ".."}:
    raise SystemExit("TAASHEERA_PREVIEW_NAME must be a single directory name.")


def configure(api_port=8000, web_port=5173, *, enable_monitoring=False):
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret_file = DATA / "jwt.secret"
    try:
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(48))
    # These overrides belong only to child preview processes. Existing files are never loaded or changed.
    os.environ.update({
        "DATABASE_URL": f"sqlite:///{(DATA / 'preview.db').as_posix()}",
        "JWT_SECRET": secret_file.read_text().strip(), "APP_ENV": "development",
        "SCHEMA_AUTO_CREATE": "false", "AUTH_COOKIE_SECURE": "false",
        "AUTH_TRUST_CLOUDFRONT_PROXY": "false", "PASSPORT_UPLOADS_ENABLED": "true",
        "PASSPORT_STORAGE_DIR": str(DATA / "passports"), "ACTIVITY_LOG_DIR": str(DATA / "activity-logs"),
        "AUTH_ALLOWED_ORIGINS": ",".join(f"http://{host}:{port}" for host in ("127.0.0.1", "localhost")
                                         for port in (web_port, api_port)),
        "TAASHEERA_API_TARGET": f"http://127.0.0.1:{api_port}", "TAASHEERA_WEB_PORT": str(web_port),
    })
    if not enable_monitoring:
        os.environ.update({"VITE_SENTRY_DSN": "", "SENTRY_DSN": ""})
    # Never send mail or passport context to external services during the isolated preview.
    for name in ("SMTP_HOST", "SMTP_FROM", "RESET_MAIL_PROVIDER", "SES_FROM_EMAIL", "RESET_FRONTEND_URL",
                 "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(name, None)
    from dev import PUBLIC_CONFIG, read_optional_setting
    os.environ["GOOGLE_CLIENT_ID"] = read_optional_setting(PUBLIC_CONFIG, "GOOGLE_CLIENT_ID") or ""
    import migrate
    migrate.upgrade()


def seed_demo():
    import bcrypt
    from sqlmodel import Session, select
    from uuid import uuid4
    from app.database import build_engine
    from app.models import ActivityEvent, Traveler, VisaApplication
    engine = build_engine()
    with Session(engine) as session:
        for label, role in (("admin", "admin"), ("traveler", "traveler"), ("delete-me", "traveler")):
            email = f"qa-{label}@example.com"
            if session.exec(select(Traveler).where(Traveler.email == email)).first() is not None:
                continue
            traveler = Traveler(name=f"Demo {label.title()}", email=email, role=role,
                password_hash=bcrypt.hashpw(b"Local-preview-only-123!", bcrypt.gensalt()).decode())
            session.add(traveler); session.flush()
            if role == "traveler":
                for status in ("DRAFT", "IN_PROGRESS", "FAILED"):
                    session.add(VisaApplication(id=uuid4().hex, traveler_id=traveler.id,
                        destination="FRA", nationality="LBN", visa_type="Demo tourist", status=status))
                session.add(ActivityEvent(traveler_id=traveler.id, event_type="passport_extraction",
                                          identifier="passport", outcome="unreadable"))
        session.commit()
    engine.dispose()
    print("Synthetic local accounts: qa-admin@example.com, qa-traveler@example.com, qa-delete-me@example.com")
    print("Local demo password: Local-preview-only-123!")


def prepare_ports(ports, free_ports=False):
    if free_ports:
        import psutil
        processes = {entry.pid for entry in psutil.net_connections(kind="inet")
                     if entry.status == psutil.CONN_LISTEN and entry.laddr.port in ports and entry.pid}
        for pid in processes:
            try:
                process = psutil.Process(pid)
                if process.pid == os.getpid():
                    raise SystemExit("Cannot stop this launcher to free a port.")
                print(f"Stopping process {pid} occupying a required preview port.", flush=True)
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    # An exited non-child can remain a zombie until its own parent
                    # reaps it. It has no sockets and needs no further signals.
                    if process.status() != psutil.STATUS_ZOMBIE:
                        process.kill()
                        try:
                            process.wait(timeout=5)
                        except psutil.TimeoutExpired:
                            if process.status() != psutil.STATUS_ZOMBIE:
                                raise SystemExit(f"Listener {pid} did not stop. Stop it in its owning terminal.") from None
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                raise SystemExit(f"Cannot stop listener {pid}. Stop it in its owning terminal and rerun.") from None
    for port in ports:
        with socket.socket() as check:
            if os.name != "nt":
                check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                check.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"Port {port} is in use. Rerun with --free-ports to stop its listener.") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--api-port", type=int, default=8000)
    run.add_argument("--web-port", type=int, default=5173)
    run.add_argument("--seed-demo", action="store_true")
    run.add_argument("--free-ports", action="store_true")
    run.add_argument("--api-only", action="store_true")
    run.add_argument("--enable-monitoring", action="store_true", help="Opt in to exported Sentry DSNs for synthetic testing")
    admin = sub.add_parser("admin"); admin.add_argument("--email", required=True)
    sub.add_parser("retry-erasures")
    args = parser.parse_args(argv)
    api_port, web_port = getattr(args, "api_port", 8000), getattr(args, "web_port", 5173)
    if not 1024 <= api_port <= 65535 or not 1024 <= web_port <= 65535 or api_port == web_port:
        parser.error("Use two different ports between 1024 and 65535.")
    if args.command == "run":
        prepare_ports([api_port] if args.api_only else [api_port, web_port], args.free_ports)
    configure(api_port, web_port, enable_monitoring=getattr(args, "enable_monitoring", False))
    if args.command == "admin":
        from manage import set_role
        print(set_role(args.email, "admin")); return
    if args.command == "retry-erasures":
        from app.database import build_engine
        from app.passport.storage import PassportImageStorage
        from app.privacy import retry_erasures
        engine = build_engine()
        try:
            pending = retry_erasures(engine, PassportImageStorage(os.environ["PASSPORT_STORAGE_DIR"]),
                                    Path(os.environ["ACTIVITY_LOG_DIR"]), os.environ["JWT_SECRET"])
        finally:
            engine.dispose()
        print(f"Pending erasures: {pending}"); return
    if args.seed_demo:
        seed_demo()
    children = []
    def stop(_signum=None, _frame=None):
        for child in children:
            if child.poll() is None: child.terminate()
    for name in ("SIGINT", "SIGTERM"):
        signal.signal(getattr(signal, name), stop)
    try:
        children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                          "--port", str(api_port), "--no-access-log"], cwd=BACKEND))
        if not args.api_only:
            # Run Vite directly so the launcher can reap its own node child,
            # without leaving a shell/npm grandchild behind during a restart.
            children.append(subprocess.Popen(["node", str(BACKEND.parent / "frontend/node_modules/vite/bin/vite.js")],
                                              cwd=BACKEND.parent / "frontend"))
        print(f"Preview: http://127.0.0.1:{web_port}/sign-in | Admin: /backoffice | API: http://127.0.0.1:{api_port}/docs", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(.25)
    finally:
        stop()
        for child in children:
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired: child.kill(); child.wait()


if __name__ == "__main__":
    main()
