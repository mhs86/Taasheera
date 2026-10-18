"""Owner-scoped active session listing and termination."""
import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import update
from sqlmodel import Session, select

from .auth import check_origin, revoke_other_sessions
from .models import AuthSession, Traveler


class SessionPublic(BaseModel):
    id: str
    device_label: str
    created_at: datetime | None
    last_active_at: datetime | None
    current: bool


class RevokedCount(BaseModel):
    ended: int


def _utc(value: datetime | None) -> datetime | None:
    # SQLite drops timezone information when reading a datetime back.
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def create_sessions_router(get_session, current_traveler) -> APIRouter:
    router = APIRouter(prefix="/sessions", tags=["sessions"])
    SessionDep = Annotated[Session, Depends(get_session)]
    TravelerDep = Annotated[Traveler, Depends(current_traveler)]

    @router.get("", response_model=list[SessionPublic])
    def list_sessions(request: Request, response: Response, traveler: TravelerDep, session: SessionDep):
        response.headers["Cache-Control"] = "private, no-store"
        rows = session.exec(select(AuthSession).where(
            AuthSession.traveler_id == traveler.id,
            AuthSession.revoked.is_(False),
            AuthSession.expires_at > int(time.time()),
        ).order_by(AuthSession.created_at.desc(), AuthSession.id)).all()
        return [SessionPublic(
            id=row.id, device_label=row.device_label or "Unknown device",
            created_at=_utc(row.created_at), last_active_at=_utc(row.last_active_at),
            current=row.id == request.state.auth_session_id,
        ) for row in rows]

    @router.delete("/{session_id}", status_code=204, dependencies=[Depends(check_origin)])
    def end_session(session_id: str, request: Request, traveler: TravelerDep, session: SessionDep):
        row = session.exec(select(AuthSession).where(
            AuthSession.id == session_id, AuthSession.traveler_id == traveler.id,
        )).first()
        if row is None or row.revoked or row.expires_at <= int(time.time()):
            raise HTTPException(404, "Session not found.", headers={"Cache-Control": "private, no-store"})
        if row.id == request.state.auth_session_id:
            raise HTTPException(400, "Use logout to end your current session.",
                                headers={"Cache-Control": "private, no-store"})
        session.execute(update(AuthSession).where(
            AuthSession.id == session_id, AuthSession.traveler_id == traveler.id,
            AuthSession.revoked.is_(False),
        ).values(revoked=True))
        session.commit()
        return Response(status_code=204, headers={"Cache-Control": "private, no-store"})

    @router.post("/revoke-others", response_model=RevokedCount, dependencies=[Depends(check_origin)])
    def end_others(request: Request, response: Response, traveler: TravelerDep, session: SessionDep):
        response.headers["Cache-Control"] = "private, no-store"
        ended = revoke_other_sessions(session, traveler.id, request.state.auth_session_id)
        session.commit()
        return RevokedCount(ended=ended)

    return router
