"""Visa application endpoints: start an application, then answer it one question at a time.

Follows the app's router-factory pattern. The server, not the browser, decides
which question comes next (`flow.next_question`), so a client can't skip the
eligibility gate or answer questions out of order. Every answer is checked and
saved as soon as it arrives, and every request checks that the signed-in
traveler owns the application.
"""

from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Session, select

from ..models import Application, ApplicationAnswer, Traveler, TravelerProfile
from ..profile import ProfileFields
from . import actions, completeness, flow

Status = Literal["DRAFT", "INELIGIBLE", "ANSWERS_COMPLETE"]


class VisaOption(BaseModel):
    destination: str
    visa_type: str
    title: str
    destination_label: str
    destination_description: str
    visa_label: str
    visa_description: str


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: str = Field(min_length=1, max_length=20)
    visa_type: str = Field(min_length=1, max_length=40)
    # Counting the traveler. Recorded only: each application is still for one person (US 81 adds groups).
    group_size: int = Field(default=1, ge=1, le=10)


class AnswerRequest(BaseModel):
    """Exactly one of: a `value`; the id of a passport upload whose review the traveler confirmed;
    or `use_suggestion`, confirming what their saved passport or profile says (US 10)."""

    model_config = ConfigDict(extra="forbid")
    value: Any = None
    passport_upload_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    use_suggestion: Literal[True] | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> "AnswerRequest":
        given = ["value" in self.model_fields_set, self.passport_upload_id is not None, self.use_suggestion is not None]
        if sum(given) != 1:
            raise ValueError("Send exactly one of value, passport_upload_id or use_suggestion.")
        return self


class Suggestion(BaseModel):
    """An answer the saved passport or profile already gives. Shown for confirming, never saved unasked."""

    value: Any
    source: Literal["passport", "profile"]


class QuestionPublic(BaseModel):
    id: str
    step_id: str
    type: flow.AnswerType
    prompt: str
    help: str | None
    required: bool
    options: list[flow.Option] | None
    max_length: int
    # Allowed date range given the answers so far, so the date picker can grey out the rest.
    date_min: date | None = None
    date_max: date | None = None
    suggestion: Suggestion | None = None


class AnswerPublic(BaseModel):
    question: QuestionPublic
    value: Any
    source: str


class StepPublic(BaseModel):
    id: str
    title: str


class ApplicationSummary(BaseModel):
    """What the applications sidebar shows (US 12): the visa, where to, when, and how far along."""

    id: str
    title: str
    destination: str
    visa_type: str
    destination_label: str
    visa_label: str
    status: Status
    group_size: int
    # From the answers the question file names in "summary", once given: "France", "2027-01-10".
    place: str | None
    trip_date: date | None
    answered: int
    total: int
    created_at: datetime
    updated_at: datetime


class ApplicationState(ApplicationSummary):
    steps: list[StepPublic]
    progress: flow.Progress
    # Answered questions in the order they were asked: the chat's history.
    answers: list[AnswerPublic]
    # The question to ask now; null when the application is complete or stopped.
    current: QuestionPublic | None
    # Why the flow stopped (e.g. the stay is longer than a short-stay visa allows).
    stopped: str | None
    # Answers removed because an earlier change made them no longer apply.
    cleared: list[str]


def _utc(value: datetime) -> datetime:
    # SQLite drops timezone information when reading a datetime back (as in sessions.py).
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _summary(application: Application, questionnaire: flow.Questionnaire,
             answers: flow.Answers) -> dict[str, Any]:
    progress = flow.progress(questionnaire, answers)
    trip_date = answers.get(questionnaire.summary.date) if questionnaire.summary.date else None
    return dict(
        id=application.id, title=questionnaire.title, destination=application.destination,
        visa_type=application.visa_type, destination_label=questionnaire.destination_label,
        visa_label=questionnaire.visa_label, status=application.status, group_size=application.group_size,
        place=flow.summary_place(questionnaire, answers), trip_date=trip_date,
        answered=progress.answered, total=progress.total,
        created_at=_utc(application.created_at), updated_at=_utc(application.updated_at),
    )


def _status(questionnaire: flow.Questionnaire, answers: flow.Answers) -> Status:
    if flow.stop_message(questionnaire, answers):
        return "INELIGIBLE"
    return "DRAFT" if flow.next_question(questionnaire, answers) else "ANSWERS_COMPLETE"


def saved_profile(session: Session, traveler_id: int) -> dict | None:
    stored = session.get(TravelerProfile, traveler_id)
    return ProfileFields.model_validate(stored, from_attributes=True).model_dump(mode="json") if stored else None


def _owned_answers(session: Session, traveler_id: int, application_id: str):
    application = session.get(Application, application_id)
    if application is None or application.traveler_id != traveler_id:
        return None
    rows = session.exec(select(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id))
    return application, flow.load_questionnaire(application.questionnaire_id), {row.question_id: row.value for row in rows}


def application_context(session: Session, traveler_id: int, application_id: str, *,
                        latest_passport: dict | None = None, today: date | None = None) -> str | None:
    """The assistant's view of one application (US 47), or None if it isn't this traveler's.

    Built here on every call, never sent by the browser: the answers, where the traveler
    is, the questions the assistant's tools may point at, and what is still missing.
    """
    found = _owned_answers(session, traveler_id, application_id)
    if found is None:
        return None
    application, questionnaire, answers = found
    today = today or date.today()
    answers, _ = flow.reconcile(questionnaire, answers, today)
    progress = flow.progress(questionnaire, answers)
    report = completeness.check(questionnaire, answers, today, latest_passport=latest_passport,
                                profile=saved_profile(session, traveler_id))
    return "\n\n".join([
        flow.describe(questionnaire, answers, application.group_size),
        f"Current step: {progress.step_title} (step {progress.step_number} of {progress.step_count})",
        actions.catalog(questionnaire, answers),
        completeness.describe(report),
    ])


def application_proposal(session: Session, traveler_id: int, application_id: str, name: str, args: dict, *,
                         latest_passport: dict | None = None, today: date | None = None) -> actions.Proposal | None:
    """A checked proposal for one assistant tool call (US 110), or None if it isn't this traveler's.

    Raises flow.InvalidAnswer when the proposal breaks a rule. Saves nothing.
    """
    found = _owned_answers(session, traveler_id, application_id)
    if found is None:
        return None
    _, questionnaire, answers = found
    return actions.propose(questionnaire, answers, name, args, today or date.today(),
                           latest_passport=latest_passport, profile=saved_profile(session, traveler_id))


def create_applications_router(
    get_session,
    current_traveler,
    load_confirmed_passport: Callable[[int, str], dict | None],
    *,
    load_latest_passport: Callable[[int], dict | None] = lambda traveler_id: None,
    today: Callable[[], date] = date.today,
) -> APIRouter:
    from ..auth import check_origin

    router = APIRouter(prefix="/applications", tags=["applications"])
    SessionDep = Annotated[Session, Depends(get_session)]
    TravelerDep = Annotated[Traveler, Depends(current_traveler)]

    def owned(session: Session, traveler: Traveler, application_id: str) -> Application:
        application = session.get(Application, application_id)
        if application is None or application.traveler_id != traveler.id:
            # 404 either way, so another traveler's ids can't be probed.
            raise HTTPException(status_code=404, detail="Application not found.")
        return application

    def stored_answers(session: Session, application: Application) -> dict[str, ApplicationAnswer]:
        rows = session.exec(select(ApplicationAnswer).where(ApplicationAnswer.application_id == application.id))
        return {row.question_id: row for row in rows}

    def save(session: Session, application: Application, rows: dict[str, ApplicationAnswer],
             questionnaire: flow.Questionnaire) -> tuple[flow.Answers, list[str]]:
        """Re-check every answer, delete the ones that no longer apply, update the status, commit.

        Runs on every read too, so an answer that was valid when given but isn't
        any more (a trip date now in the past) is asked again instead of trusted.
        """
        answers, cleared = flow.reconcile(questionnaire, {key: row.value for key, row in rows.items()}, today())
        for question_id in cleared:
            session.delete(rows.pop(question_id))
        status = _status(questionnaire, answers)
        if cleared or status != application.status:
            application.status = status
            application.updated_at = datetime.now(timezone.utc)
            session.add(application)
        session.commit()
        return answers, cleared

    def suggest(session: Session, traveler: Traveler, question: flow.Question,
                answers: flow.Answers) -> Suggestion | None:
        """What the traveler's own saved passport or profile says for this question, if it passes its rules.

        Loaded here for the signed-in traveler only, and checked like any answer, so an
        expired passport or a half-filled address is never offered.
        """
        if question.prefill is None:
            return None
        passport = load_latest_passport(traveler.id) if question.prefill == "passport" else None
        profile = saved_profile(session, traveler.id) if question.prefill.startswith("profile.") else None
        found = flow.prefill_value(question, passport, profile)
        if found is None:
            return None
        try:
            return Suggestion(value=flow.check_answer(question, found[0], answers, today()), source=found[1])
        except flow.InvalidAnswer:
            return None

    def public_question(questionnaire: flow.Questionnaire, question: flow.Question,
                        answers: flow.Answers, suggestion: Suggestion | None = None) -> QuestionPublic:
        earliest, latest = flow.date_bounds(question, answers, today())
        return QuestionPublic(
            id=question.id, step_id=questionnaire.step_of(question.id).id, type=question.type,
            prompt=question.prompt, help=question.help, required=question.required,
            options=question.options, max_length=question.max_length, date_min=earliest, date_max=latest,
            suggestion=suggestion,
        )

    def state(session: Session, traveler: Traveler, application: Application, questionnaire: flow.Questionnaire,
              answers: flow.Answers, rows: dict[str, ApplicationAnswer], cleared: list[str]) -> ApplicationState:
        current = flow.next_question(questionnaire, answers)
        return ApplicationState(
            **_summary(application, questionnaire, answers),
            steps=[StepPublic(id=step.id, title=step.title) for step in questionnaire.steps],
            progress=flow.progress(questionnaire, answers),
            answers=[
                AnswerPublic(question=public_question(questionnaire, question, answers),
                             value=answers[question.id], source=rows[question.id].source)
                for question in flow.visible_questions(questionnaire, answers) if question.id in answers
            ],
            current=public_question(questionnaire, current, answers, suggest(session, traveler, current, answers))
            if current else None,
            stopped=flow.stop_message(questionnaire, answers),
            cleared=cleared,
        )

    @router.get("/options", response_model=list[VisaOption])
    def options(traveler: TravelerDep):
        return [VisaOption(destination=q.destination, visa_type=q.visa_type, title=q.title,
                           destination_label=q.destination_label, destination_description=q.destination_description,
                           visa_label=q.visa_label, visa_description=q.visa_description)
                for q in flow.available_questionnaires()]

    @router.post("", response_model=ApplicationState, status_code=201, dependencies=[Depends(check_origin)])
    def start(data: StartRequest, traveler: TravelerDep, session: SessionDep, response: Response):
        questionnaire = next((q for q in flow.available_questionnaires()
                              if (q.destination, q.visa_type) == (data.destination, data.visa_type)), None)
        if questionnaire is None:
            raise HTTPException(status_code=422, detail="We can't prepare that visa yet.")
        application = Application(
            id=uuid.uuid4().hex, traveler_id=traveler.id, questionnaire_id=questionnaire.id,
            questionnaire_version=questionnaire.version, destination=questionnaire.destination,
            visa_type=questionnaire.visa_type, group_size=data.group_size,
        )
        session.add(application)
        session.commit()
        response.headers["Cache-Control"] = "private, no-store"
        return state(session, traveler, application, questionnaire, {}, {}, [])

    @router.get("", response_model=list[ApplicationSummary])
    def list_applications(traveler: TravelerDep, session: SessionDep, response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        applications = session.exec(select(Application).where(Application.traveler_id == traveler.id)
                                    .order_by(Application.updated_at.desc())).all()
        # One query for every application's answers, not one per application.
        answers: dict[str, flow.Answers] = {application.id: {} for application in applications}
        rows = session.exec(select(ApplicationAnswer)
                            .where(ApplicationAnswer.application_id.in_(list(answers)))) if answers else []
        for row in rows:
            answers[row.application_id][row.question_id] = row.value
        return [ApplicationSummary(**_summary(application, flow.load_questionnaire(application.questionnaire_id),
                                              answers[application.id]))
                for application in applications]

    @router.get("/{application_id}", response_model=ApplicationState)
    def get_application(application_id: str, traveler: TravelerDep, session: SessionDep, response: Response):
        application = owned(session, traveler, application_id)
        questionnaire = flow.load_questionnaire(application.questionnaire_id)
        rows = stored_answers(session, application)
        answers, cleared = save(session, application, rows, questionnaire)
        response.headers["Cache-Control"] = "private, no-store"
        return state(session, traveler, application, questionnaire, answers, rows, cleared)

    @router.get("/{application_id}/check", response_model=completeness.Report)
    def check(application_id: str, traveler: TravelerDep, session: SessionDep, response: Response):
        """The completeness check (US 13): what is missing or inconsistent before submission."""
        application = owned(session, traveler, application_id)
        questionnaire = flow.load_questionnaire(application.questionnaire_id)
        answers, _ = save(session, application, stored_answers(session, application), questionnaire)
        response.headers["Cache-Control"] = "private, no-store"
        return completeness.check(questionnaire, answers, today(), latest_passport=load_latest_passport(traveler.id),
                                  profile=saved_profile(session, traveler.id))

    @router.put("/{application_id}/answers/{question_id}", response_model=ApplicationState,
                dependencies=[Depends(check_origin)])
    def answer(application_id: str, question_id: str, data: AnswerRequest, traveler: TravelerDep,
               session: SessionDep, response: Response):
        application = owned(session, traveler, application_id)
        questionnaire = flow.load_questionnaire(application.questionnaire_id)
        question = questionnaire.question(question_id)
        if question is None:
            raise HTTPException(status_code=404, detail="Question not found.")
        rows = stored_answers(session, application)
        answers = {key: row.value for key, row in rows.items()}
        # Only the current question, or one already answered (to change it). This keeps the
        # order the file defines, so nobody can skip past the eligibility questions.
        current = flow.next_question(questionnaire, answers)
        if not flow.is_visible(question, answers) or (
                question_id not in answers and (current is None or current.id != question_id)):
            raise HTTPException(status_code=409, detail="Answer the earlier questions first.")

        if data.use_suggestion:
            # Worked out again here, not taken from the browser, so "from your passport" stays true.
            suggestion = suggest(session, traveler, question, answers)
            if suggestion is None:
                raise HTTPException(status_code=409, detail="There's nothing saved to use for this question.")
            value, source = suggestion.value, suggestion.source
        else:
            if data.passport_upload_id is not None:
                if question.type != "passport":
                    raise HTTPException(status_code=422, detail="Only the passport question takes a passport upload.")
                raw = load_confirmed_passport(traveler.id, data.passport_upload_id)
                if raw is None:
                    raise HTTPException(status_code=404, detail="Confirm your passport details first.")
                source = "passport_upload"
            else:
                raw, source = data.value, "traveler"
            try:
                value = flow.check_answer(question, raw, answers, today())
            except flow.InvalidAnswer as error:
                raise HTTPException(status_code=422, detail=str(error)) from None

        row = rows.get(question_id) or ApplicationAnswer(application_id=application.id, question_id=question_id,
                                                         value=value, source=source)
        row.value, row.source, row.answered_at = value, source, datetime.now(timezone.utc)
        session.add(row)
        rows[question_id] = row
        application.updated_at = datetime.now(timezone.utc)
        session.add(application)
        answers, cleared = save(session, application, rows, questionnaire)
        response.headers["Cache-Control"] = "private, no-store"
        return state(session, traveler, application, questionnaire, answers, rows, cleared)

    return router
