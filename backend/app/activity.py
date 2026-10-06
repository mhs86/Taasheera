"""Small, allowlisted audit events. No request bodies or user supplied text is stored."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session

from .models import ActivityEvent, Traveler


log = logging.getLogger(__name__)
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "storage" / "activity-logs"


def activity_directory_from_environment() -> Path:
    directory = Path(os.environ.get("ACTIVITY_LOG_DIR", str(DEFAULT_DIRECTORY)))
    if not directory.is_absolute() or (directory.exists() and not directory.is_dir()):
        raise RuntimeError("ACTIVITY_LOG_DIR must be an absolute directory path.")
    return directory

# Only static UI identifiers may cross the browser boundary. In particular,
# URLs, element text, form fields, error messages and Google responses are excluded.
Page = Literal["home", "faq", "passport", "sign-in", "create-account", "forgot-password", "reset-password", "not-found"]
Control = Literal[
    "home-link", "how-it-works-link", "destinations-link", "privacy-link", "faq-link",
    "login-link", "get-started-link", "skip-link", "menu-toggle", "password-toggle",
    "forgot-password-link", "create-account-link", "sign-in-link", "submit-login",
    "submit-registration", "logout-button", "google-retry", "google-cancel",
    "faq-question", "reset-request", "reset-submit", "reset-link",
    "passport-choose-file", "passport-take-photo", "passport-replace", "passport-confirm",
    "assistant-open", "assistant-close", "assistant-send", "assistant-suggestion", "passport-link",
]


class FrontendActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["page_visit", "click"]
    page: Page
    control: Control | None = None
    outcome: Literal["visited", "initiated"]


def record_activity(session: Session, directory: Path, traveler_id: int, event_type: str,
                    identifier: str, outcome: str) -> ActivityEvent:
    event = ActivityEvent(traveler_id=traveler_id, event_type=event_type,
                          identifier=identifier, outcome=outcome)
    session.add(event)
    session.commit()
    session.refresh(event)
    # The database is authoritative. A failed mirror must not turn a completed
    # registration, login, or upload into an apparent failure to the traveler.
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            directory.chmod(0o700)
        owner_dir = directory / str(traveler_id)
        owner_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            owner_dir.chmod(0o700)
        path = owner_dir / f"{event.occurred_at.date().isoformat()}.jsonl"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps({
                "id": event.id, "traveler_id": traveler_id,
                "occurred_at": event.occurred_at.replace(tzinfo=timezone.utc).isoformat(),
                "event_type": event_type, "identifier": identifier, "outcome": outcome,
            }, separators=(",", ":")) + "\n")
    except OSError:
        log.error("Activity JSONL mirror failed; database event was saved")
    return event


def create_activity_router(get_session, current_traveler):
    from .auth import check_origin
    router = APIRouter(prefix="/activity", tags=["Activity"])
    SessionDep = Annotated[Session, Depends(get_session)]
    TravelerDep = Annotated[Traveler, Depends(current_traveler)]

    @router.post("/events", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(check_origin)])
    def create_event(data: FrontendActivity, request: Request, session: SessionDep, traveler: TravelerDep):
        # Ownership comes exclusively from the verified bearer token. The
        # payload contains no traveler id and cannot name another account.
        if data.event_type == "page_visit":
            if data.control is not None or data.outcome != "visited":
                raise HTTPException(422, "Invalid page visit event")
            identifier = data.page
        else:
            if data.control is None or data.outcome != "initiated":
                raise HTTPException(422, "Invalid click event")
            identifier = f"{data.page}:{data.control}"
        record_activity(session, request.app.state.activity_directory, traveler.id,
                        data.event_type, identifier, data.outcome)

    return router
