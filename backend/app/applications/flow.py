"""The guided questionnaire's flow engine (US 9).

The questions, their order, which answers skip which questions and which dates
are allowed all live in a per-destination data file (`questionnaires/*.json`).
This module reads that file and decides, from the answers given so far, what
to ask next. The AI never chooses a question: the flow is deterministic, so
the same answers always lead to the same questions and every rule can be tested.

Everything here is pure: no database, no web framework, and "today" is passed
in. The router stores answers and calls these functions.
"""

from calendar import monthrange
from collections.abc import Iterator
from datetime import date, timedelta
from functools import cache
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..passport.router import PassportFields
from ..profile import ProfileFields

QUESTIONNAIRE_DIR = Path(__file__).resolve().parent / "questionnaires"
Answers = dict[str, Any]
AnswerType = Literal["choice", "yes_no", "text", "date", "country", "phone", "address", "passport"]
# A reference used by a date rule: "today", a question id, or "question.field" for an answer
# made of several fields, such as "passport.expiry_date".
_REF = re.compile(r"today|[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?")


class _Strict(BaseModel):
    # A typo in the data file (say "show_iff") fails loudly instead of being ignored.
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Option(_Strict):
    value: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=100)


class Condition(_Strict):
    question: str
    values: list[str | bool] = Field(alias="in", min_length=1)


class StopRule(_Strict):
    values: list[str | bool] = Field(alias="in", min_length=1)
    message: str = Field(min_length=1)


class DateRule(_Strict):
    """The answer must be `op` the referenced date, shifted by `months` and `days`."""

    op: Literal[">=", "<="]
    ref: str = Field(pattern=_REF.pattern)
    months: int = 0
    days: int = 0
    message: str = Field(min_length=1)


class Question(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)
    type: AnswerType
    prompt: str = Field(min_length=1)
    help: str | None = None
    required: bool = True
    options: list[Option] | None = None
    max_length: int = Field(default=200, ge=1, le=1000)
    rules: list[DateRule] = Field(default_factory=list)
    show_if: Condition | None = None
    stop_if: StopRule | None = None


class Step(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1)
    questions: list[Question] = Field(min_length=1)


class Questionnaire(_Strict):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    version: int = Field(ge=1)
    destination: str
    visa_type: str
    title: str
    source: str
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def check_references(self) -> "Questionnaire":
        """Check the file's internal wiring once, when it loads, not when a traveler hits it."""
        seen: dict[str, Question] = {}
        for question in self.questions():
            if question.id in seen:
                raise ValueError(f"Question id {question.id!r} is used twice.")
            if (question.type == "choice") != bool(question.options):
                raise ValueError(f"{question.id}: choice questions, and only they, need options.")
            if question.rules and question.type != "date":
                raise ValueError(f"{question.id}: only date questions can have date rules.")
            # Conditions and rules may only look backwards, so the flow can never loop.
            if question.show_if:
                source = seen.get(question.show_if.question)
                if source is None:
                    raise ValueError(f"{question.id}: show_if must refer to an earlier question.")
                _check_values(question.id, source, question.show_if.values)
            if question.stop_if:
                _check_values(question.id, question, question.stop_if.values)
            for rule in question.rules:
                name = rule.ref.split(".")[0]
                if rule.ref != "today" and name not in seen:
                    raise ValueError(f"{question.id}: rule refers to {rule.ref!r}, which isn't an earlier question.")
            seen[question.id] = question
        return self

    def questions(self) -> Iterator[Question]:
        for step in self.steps:
            yield from step.questions

    def question(self, question_id: str) -> Question | None:
        return next((question for question in self.questions() if question.id == question_id), None)

    def step_of(self, question_id: str) -> Step:
        return next(step for step in self.steps if any(q.id == question_id for q in step.questions))


def _check_values(question_id: str, source: Question, values: list) -> None:
    allowed = {True, False} if source.type == "yes_no" else {o.value for o in source.options or []}
    if source.type not in {"yes_no", "choice"} or any(value not in allowed for value in values):
        raise ValueError(f"{question_id}: a condition uses a value {source.id!r} can't have.")


@cache
def load_questionnaire(questionnaire_id: str) -> Questionnaire:
    if not re.fullmatch(r"[a-z0-9-]+", questionnaire_id):
        raise KeyError(questionnaire_id)
    path = QUESTIONNAIRE_DIR / f"{questionnaire_id}.json"
    if not path.is_file():
        raise KeyError(questionnaire_id)
    return Questionnaire.model_validate_json(path.read_text(encoding="utf-8"))


def available_questionnaires() -> list[Questionnaire]:
    return [load_questionnaire(path.stem) for path in sorted(QUESTIONNAIRE_DIR.glob("*.json"))]


# --- Deciding what to ask -----------------------------------------------------


def is_visible(question: Question, answers: Answers) -> bool:
    return question.show_if is None or answers.get(question.show_if.question) in question.show_if.values


def visible_questions(questionnaire: Questionnaire, answers: Answers) -> list[Question]:
    return [question for question in questionnaire.questions() if is_visible(question, answers)]


def stop_message(questionnaire: Questionnaire, answers: Answers) -> str | None:
    """Why the flow can't go on (e.g. "a short stay covers 90 days at most"), or None."""
    for question in visible_questions(questionnaire, answers):
        if question.stop_if and question.id in answers and answers[question.id] in question.stop_if.values:
            return question.stop_if.message
    return None


def next_question(questionnaire: Questionnaire, answers: Answers) -> Question | None:
    """The first visible question without an answer, or None when finished or stopped."""
    if stop_message(questionnaire, answers):
        return None
    return next((q for q in visible_questions(questionnaire, answers) if q.id not in answers), None)


class Progress(BaseModel):
    step_number: int
    step_count: int
    step_title: str
    answered: int
    total: int


def progress(questionnaire: Questionnaire, answers: Answers) -> Progress:
    visible = visible_questions(questionnaire, answers)
    current = next_question(questionnaire, answers)
    step = questionnaire.step_of(current.id) if current else questionnaire.steps[-1]
    return Progress(
        step_number=questionnaire.steps.index(step) + 1,
        step_count=len(questionnaire.steps),
        step_title=step.title,
        answered=sum(question.id in answers for question in visible),
        total=len(visible),
    )


# --- Checking answers ---------------------------------------------------------


class InvalidAnswer(ValueError):
    """The answer breaks a rule. The message is written for the traveler."""


class AddressAnswer(BaseModel):
    # Same names as the profile's address_* fields, so the profile can pre-fill it (US 10).
    model_config = ConfigDict(extra="forbid")
    line1: str = Field(min_length=1, max_length=200)
    line2: str = Field(default="", max_length=200)
    city: str = Field(min_length=1, max_length=100)
    region: str = Field(default="", max_length=100)
    postal_code: str = Field(default="", max_length=20)
    country: str = Field(pattern=r"^[A-Z]{1,3}$")


def add_months(day: date, months: int) -> date:
    """Calendar months, clamping to the month's last day (31 Jan + 1 month = 28/29 Feb)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def _resolve(ref: str, answers: Answers, today: date) -> date | None:
    if ref == "today":
        return today
    name, _, field = ref.partition(".")
    value = answers.get(name)
    if field:
        value = value.get(field) if isinstance(value, dict) else None
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def date_bounds(question: Question, answers: Answers, today: date) -> tuple[date | None, date | None]:
    """The earliest and latest allowed dates, for the date picker. The server still checks."""
    earliest = latest = None
    for rule in question.rules:
        anchor = _resolve(rule.ref, answers, today)
        if anchor is None:
            continue
        limit = add_months(anchor, rule.months) + timedelta(days=rule.days)
        if rule.op == ">=":
            earliest = max(earliest, limit) if earliest else limit
        else:
            latest = min(latest, limit) if latest else limit
    return earliest, latest


_FIELD_LABELS = {
    "line1": "Street address", "line2": "Second address line", "city": "City", "region": "Region",
    "postal_code": "Postal code", "country": "Country", "surname": "Surname", "given_names": "Given names",
    "document_number": "Passport number", "nationality": "Nationality", "issuing_country": "Issuing country",
    "birth_date": "Date of birth", "sex": "Sex", "expiry_date": "Expiry date", "personal_number": "Personal number",
}


def _first_error(error: ValidationError) -> str:
    """A short message for the traveler; never echoes the submitted value."""
    detail = error.errors()[0]
    label = _FIELD_LABELS.get(str(detail["loc"][0]), "This answer") if detail["loc"] else "This answer"
    if detail["type"] in {"missing", "string_too_short"}:
        return f"{label} is required."
    if detail["type"] == "extra_forbidden":
        return "This answer has a field we don't recognise."
    return f"{label}: {detail['msg'].removeprefix('Value error, ')}"


def check_answer(question: Question, raw: Any, answers: Answers, today: date) -> Any:
    """Return the value to store, or raise InvalidAnswer with a message for the traveler.

    `answers` holds the other answers, so rules such as "leave after you arrive"
    can look at them. Values are stored as JSON (dates as YYYY-MM-DD).
    """
    match question.type:
        case "choice":
            if raw not in {option.value for option in question.options or []}:
                raise InvalidAnswer("Choose one of the options.")
            return raw
        case "yes_no":
            if not isinstance(raw, bool):
                raise InvalidAnswer("Answer yes or no.")
            return raw
        case "text":
            if not isinstance(raw, str):
                raise InvalidAnswer("Type your answer.")
            value = " ".join(raw.split())
            if question.required and not value:
                raise InvalidAnswer("This question needs an answer.")
            if len(value) > question.max_length:
                raise InvalidAnswer(f"Keep it under {question.max_length} characters.")
            return value
        case "country":
            if not isinstance(raw, str) or not re.fullmatch(r"[A-Z]{1,3}", raw):
                raise InvalidAnswer("Choose a country.")
            return raw
        case "phone":
            try:
                phone = ProfileFields(phone=raw).phone
            except ValidationError as error:
                raise InvalidAnswer(error.errors()[0]["msg"].removeprefix("Value error, ")) from None
            if phone is None:
                raise InvalidAnswer("This question needs an answer.")
            return phone
        case "address":
            try:
                return AddressAnswer.model_validate(raw).model_dump()
            except ValidationError as error:
                raise InvalidAnswer(_first_error(error)) from None
        case "passport":
            try:
                fields = PassportFields.model_validate(raw)
            except ValidationError as error:
                raise InvalidAnswer(_first_error(error)) from None
            if fields.birth_date is None or fields.expiry_date is None:
                raise InvalidAnswer("Your passport's date of birth and expiry date are both needed.")
            if fields.expiry_date <= today:
                raise InvalidAnswer("This passport has expired. You'll need to renew it before applying.")
            return fields.model_dump(mode="json")
        case "date":
            if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
                raise InvalidAnswer("Choose a date.")
            try:
                value = date.fromisoformat(raw)
            except ValueError:
                raise InvalidAnswer("Choose a real date.") from None
            for rule in question.rules:
                anchor = _resolve(rule.ref, answers, today)
                # A rule about an answer we don't have yet can't be judged; it applies once it exists.
                if anchor is None:
                    continue
                limit = add_months(anchor, rule.months) + timedelta(days=rule.days)
                if (rule.op == ">=" and value < limit) or (rule.op == "<=" and value > limit):
                    raise InvalidAnswer(rule.message)
            return raw
    raise AssertionError(question.type)


def reconcile(questionnaire: Questionnaire, answers: Answers, today: date) -> tuple[Answers, list[str]]:
    """Drop answers that no longer apply after an earlier answer changed.

    Walks the questions in order and keeps an answer only if its question is
    still shown and it still passes its rules. Changing "staying with family" to
    "a hotel" drops the host's details; moving the arrival date can drop a
    departure date that's now too far away, so the flow asks for it again.
    Returns the answers to keep and the ids that were dropped.
    """
    kept: Answers = {}
    dropped: list[str] = []
    for question in questionnaire.questions():
        if question.id not in answers:
            continue
        if not is_visible(question, kept):
            dropped.append(question.id)
            continue
        try:
            kept[question.id] = check_answer(question, answers[question.id], kept, today)
        except InvalidAnswer:
            dropped.append(question.id)
    return kept, dropped


# --- Describing an application to the assistant -------------------------------


def display_value(question: Question, value: Any) -> str:
    if question.type == "choice":
        return next((option.label for option in question.options or [] if option.value == value), str(value))
    if question.type == "yes_no":
        return "Yes" if value else "No"
    if isinstance(value, dict):
        return ", ".join(f"{key.replace('_', ' ')}: {item}" for key, item in value.items() if item)
    return str(value) if value != "" else "(left empty)"


def describe(questionnaire: Questionnaire, answers: Answers) -> str:
    """Plain text for the assistant's prompt: the visa, where the traveler is, and their answers."""
    current = next_question(questionnaire, answers)
    stopped = stop_message(questionnaire, answers)
    lines = [f"Visa: {questionnaire.title}"]
    if stopped:
        lines.append(f"The application can't go on: {stopped}")
    lines.append(f"Current question: {current.prompt}" if current else
                 "Current question: none, every question is answered." if not stopped else "Current question: none.")
    lines.append("Answers so far:")
    lines += [f"- {question.prompt} {display_value(question, answers[question.id])}"
              for question in visible_questions(questionnaire, answers) if question.id in answers]
    return "\n".join(lines)
