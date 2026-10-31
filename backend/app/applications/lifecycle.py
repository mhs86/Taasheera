"""Archive, delete and the timeline of one application (US 79, US 20).

Included from the applications router, so every path here sits under
/applications and shares its owner check: another traveler's id is a 404,
the same as an id that doesn't exist.

The timeline is worked out from what is already stored (when the application
was started, when each answer was last saved, when it was archived) instead of
a separate event table, so deleting an application leaves nothing behind.
"""

from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, delete, select

from ..models import Application, ApplicationAnswer, Traveler
from . import flow
from .router import ApplicationSummary, _status, _summary, _utc


class TimelineEvent(BaseModel):
    kind: Literal["started", "answered", "stopped", "complete", "archived"]
    at: datetime
    text: str
    # For answers: which question, and the step it belongs to, so the page can group them.
    question_id: str | None = None
    step_title: str | None = None


class NextStep(BaseModel):
    kind: Literal["answer", "change", "complete", "archived"]
    text: str


class Timeline(BaseModel):
    id: str
    archived_at: datetime | None
    # Oldest first. An answer changed later shows once, at the time it was last saved.
    events: list[TimelineEvent]
    next: NextStep


def delete_application(session: Session, application: Application) -> None:
    """Remove an application and its answers. Answers go first: PostgreSQL enforces the foreign key."""
    session.exec(delete(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id))
    session.delete(application)


def create_lifecycle_router(
    get_session,
    current_traveler,
    *,
    today: Callable[[], date] = date.today,
) -> APIRouter:
    from ..auth import check_origin

    router = APIRouter()
    SessionDep = Annotated[Session, Depends(get_session)]
    TravelerDep = Annotated[Traveler, Depends(current_traveler)]

    def owned(session: Session, traveler: Traveler, application_id: str) -> Application:
        application = session.get(Application, application_id)
        if application is None or application.traveler_id != traveler.id:
            raise HTTPException(status_code=404, detail="Application not found.")
        return application

    def stored_rows(session: Session, application: Application) -> dict[str, ApplicationAnswer]:
        rows = session.exec(select(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id))
        return {row.question_id: row for row in rows}

    def summary(session: Session, application: Application) -> ApplicationSummary:
        answers = {key: row.value for key, row in stored_rows(session, application).items()}
        return ApplicationSummary(**_summary(application, flow.load_questionnaire(application.questionnaire_id),
                                             answers))

    def set_archived(application_id: str, traveler: Traveler, session: Session, response: Response,
                     archived: bool) -> ApplicationSummary:
        application = owned(session, traveler, application_id)
        # Doing it twice changes nothing. `updated_at` stays as it is: it means the last change to the answers.
        if (application.archived_at is not None) != archived:
            application.archived_at = datetime.now(timezone.utc) if archived else None
            session.add(application)
            session.commit()
        response.headers["Cache-Control"] = "private, no-store"
        return summary(session, application)

    @router.post("/{application_id}/archive", response_model=ApplicationSummary,
                 dependencies=[Depends(check_origin)])
    def archive(application_id: str, traveler: TravelerDep, session: SessionDep, response: Response):
        return set_archived(application_id, traveler, session, response, True)

    @router.post("/{application_id}/unarchive", response_model=ApplicationSummary,
                 dependencies=[Depends(check_origin)])
    def unarchive(application_id: str, traveler: TravelerDep, session: SessionDep, response: Response):
        return set_archived(application_id, traveler, session, response, False)

    @router.delete("/{application_id}", status_code=204, dependencies=[Depends(check_origin)])
    def remove(application_id: str, traveler: TravelerDep, session: SessionDep):
        # Passport uploads stay: they belong to the passport page, and answers hold their own copy.
        delete_application(session, owned(session, traveler, application_id))
        session.commit()
        return Response(status_code=204, headers={"Cache-Control": "private, no-store"})

    @router.get("/{application_id}/timeline", response_model=Timeline)
    def timeline(application_id: str, traveler: TravelerDep, session: SessionDep, response: Response):
        application = owned(session, traveler, application_id)
        questionnaire = flow.load_questionnaire(application.questionnaire_id)
        rows = stored_rows(session, application)
        # Checked like the chat does, but only read: answers that no longer apply are left out, not deleted.
        answers, _ = flow.reconcile(questionnaire, {key: row.value for key, row in rows.items()}, today())
        status = _status(questionnaire, answers)

        events = [TimelineEvent(kind="started", at=_utc(application.created_at),
                                text=f"Started the {questionnaire.title} application")]
        answered = [question for question in flow.visible_questions(questionnaire, answers) if question.id in answers]
        events += [TimelineEvent(kind="answered", at=_utc(rows[question.id].answered_at), text=question.prompt,
                                 question_id=question.id, step_title=questionnaire.step_of(question.id).title)
                   for question in answered]
        last_answer = max((_utc(rows[question.id].answered_at) for question in answered), default=None)
        stopped = flow.stop_message(questionnaire, answers)
        if status == "INELIGIBLE" and last_answer:
            events.append(TimelineEvent(kind="stopped", at=last_answer, text=stopped or "An answer stopped the application."))
        elif status == "ANSWERS_COMPLETE" and last_answer:
            events.append(TimelineEvent(kind="complete", at=last_answer, text="Every question answered"))
        if application.archived_at:
            events.append(TimelineEvent(kind="archived", at=_utc(application.archived_at), text="Archived"))
        # Stable sort: answers saved in the same instant keep the questionnaire's order.
        events.sort(key=lambda event: event.at)

        current = flow.next_question(questionnaire, answers)
        if application.archived_at:
            next_step = NextStep(kind="archived", text="This application is archived. Restore it to pick up where you left off.")
        elif status == "INELIGIBLE":
            next_step = NextStep(kind="change", text=f"{stopped} Change the answer that stopped it to carry on.")
        elif current:
            step = questionnaire.step_of(current.id)
            number = questionnaire.steps.index(step) + 1
            next_step = NextStep(kind="answer", text=f"Next question (step {number} of {len(questionnaire.steps)}, "
                                                     f"{step.title}): {current.prompt}")
        else:
            next_step = NextStep(kind="complete", text="Your answers are complete. Supporting documents and a final "
                                                       "review come next; nothing is submitted without your confirmation.")
        response.headers["Cache-Control"] = "private, no-store"
        return Timeline(id=application.id, archived_at=_utc(application.archived_at) if application.archived_at else None,
                        events=events, next=next_step)

    return router
