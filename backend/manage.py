"""Operator commands that need database access, never an HTTP endpoint.

Usage: python manage.py set-role --email someone@example.com --role admin
"""

import argparse
import sys
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.activity import activity_directory_from_environment, record_activity
from app.database import build_engine
from app.models import ROLES, AccountErasure, Traveler
from app.schema import require_current_schema


def set_role(email: str, role: str) -> str:
    try:
        directory = activity_directory_from_environment()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    try:
        # Normalized the same way as sign-up and Google sign-in.
        email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    except ValidationError:
        raise SystemExit("Enter a valid email address.") from None
    engine = build_engine()
    try:
        url = engine.url
        if url.get_backend_name() == "sqlite" and url.database and not Path(url.database).is_file():
            # Connecting would quietly create an empty database at a mistyped path.
            raise SystemExit("No database file at that path. Check DATABASE_URL, or run "
                             "'python dev.py run' once to create the local database.")
        try:
            require_current_schema(engine)
        except OperationalError:
            raise SystemExit("Could not connect to the database. Check DATABASE_URL.") from None
        except RuntimeError:
            raise SystemExit("Database schema is not current. Run 'python migrate.py upgrade' first.") from None
        with Session(engine) as session:
            # Lock the account first, like login and password reset: a no-op UPDATE takes SQLite's
            # write lock, and FOR UPDATE the PostgreSQL row lock. Concurrent runs then record each
            # change from the right previous role.
            session.execute(update(Traveler).where(Traveler.email == email).values(role=Traveler.role))
            traveler = session.exec(select(Traveler).where(Traveler.email == email).with_for_update()).first()
            if traveler is None:
                raise SystemExit("No account uses that email. Sign up first, then run this command again.")
            if session.get(AccountErasure, traveler.id) is not None:
                raise SystemExit("Account erasure is pending; this account cannot change roles.")
            # Never print the email: terminal output often ends up in shared logs.
            account = f"Account {traveler.id} ({'password' if traveler.password_hash else 'Google'} sign-in)"
            previous, suspended = traveler.role, traveler.status == "suspended"
            if previous != role:
                traveler.role = role
                session.add(traveler)
                # Commits the role change and its audit event together.
                record_activity(session, directory, traveler.id, "role_change", f"cli:{previous}->{role}", "success")
    finally:
        engine.dispose()
    if previous == role:
        message = f"{account} already has the {role} role; nothing changed."
    else:
        message = f"{account} role changed from {previous} to {role}."
    if suspended and role != "traveler":
        message += " It is suspended, so it cannot use admin tools until it is reactivated."
    return message


def main(argv: list[str] | None = None) -> None:
    # No abbreviations: '--em' or '--ro' must not silently mean something.
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    set_role_parser = commands.add_parser(
        "set-role", help="Give an existing account the traveler, support or admin role.", allow_abbrev=False)
    set_role_parser.add_argument("--email", required=True)
    set_role_parser.add_argument("--role", required=True, choices=ROLES)
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] not in commands.choices and argv[0] not in ("-h", "--help"):
        # Anything before the command would be echoed as an invalid choice.
        parser.error(f"start with a command: {', '.join(commands.choices)}")
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        # argparse would echo them, and a mistaken '--password ...' must not reach shared logs.
        parser.error("unrecognized arguments (not shown)")
    print(set_role(args.email, args.role))


if __name__ == "__main__":
    main()
