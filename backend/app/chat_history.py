"""Assistant chat history across visits (US 111).

The server keeps the conversation, per traveler and per application, and it is
also the server that hands earlier turns to the model. The browser no longer
supplies "what the assistant said before", so a client can't plant a fake
assistant turn to steer the model. Every read and write is scoped to the
signed-in traveler; another traveler's application id simply finds nothing.
"""

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlmodel import Session, delete, select

from .models import Application, AssistantMessage

# What one page shows and what the model sees: the newest turns, oldest first.
PAGE_SIZE = 50
ApplicationId = Annotated[str | None, Query(pattern=r"^[0-9a-f]{32}$")]


class MessagePublic(BaseModel):
    role: Literal["user", "assistant"]
    content: str


def _scope(traveler_id: int, application_id: str | None):
    query = select(AssistantMessage).where(AssistantMessage.traveler_id == traveler_id)
    if application_id is None:
        return query.where(AssistantMessage.application_id.is_(None))
    return query.where(AssistantMessage.application_id == application_id)


def load_history(session: Session, traveler_id: int, application_id: str | None, limit: int = PAGE_SIZE) -> list[dict]:
    rows = session.exec(_scope(traveler_id, application_id)
                        .order_by(AssistantMessage.id.desc()).limit(limit)).all()
    return [{"role": row.role, "content": row.content} for row in reversed(rows)]


def save_turn(session: Session, traveler_id: int, application_id: str | None, question: str, reply: str) -> None:
    """Store a question and its answer together, only once the answer exists."""
    if application_id is not None:
        application = session.get(Application, application_id)
        if application is None or application.traveler_id != traveler_id:
            return
    session.add(AssistantMessage(traveler_id=traveler_id, application_id=application_id, role="user", content=question))
    session.add(AssistantMessage(traveler_id=traveler_id, application_id=application_id, role="assistant", content=reply))
    session.commit()


def create_chat_history_router(get_session, current_traveler_id: Callable) -> APIRouter:
    from .auth import check_origin

    router = APIRouter(prefix="/assistant/history", tags=["assistant"])
    SessionDep = Annotated[Session, Depends(get_session)]
    TravelerId = Annotated[int, Depends(current_traveler_id)]

    @router.get("", response_model=list[MessagePublic])
    def history(traveler_id: TravelerId, session: SessionDep, response: Response,
                application_id: ApplicationId = None):
        response.headers["Cache-Control"] = "private, no-store"
        return load_history(session, traveler_id, application_id)

    @router.delete("", status_code=204, dependencies=[Depends(check_origin)])
    def clear(traveler_id: TravelerId, session: SessionDep, application_id: ApplicationId = None):
        ids = [row.id for row in session.exec(_scope(traveler_id, application_id)).all()]
        if ids:
            session.exec(delete(AssistantMessage).where(AssistantMessage.id.in_(ids)))
            session.commit()
        return Response(status_code=204)

    return router
