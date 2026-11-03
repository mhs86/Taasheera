"""What the assistant may propose to do in an application (US 110).

The model never changes anything. When the traveler asks for an action ("change
my departure to the 24th", "take me to the trip questions", "is anything
missing?"), the model calls a tool, and this module turns that call into a
*proposal*: checked with the same rules as a typed answer, so the model can't
propose an answer the form would refuse or skip the questions' order. The page
shows the proposal and only the traveler's click saves it, through the normal
answer endpoint, which checks it all again. Nothing is ever submitted.

Pure like the flow engine: no database, and "today" is passed in.
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from . import completeness, flow

# Answers made of several fields are changed in the chat itself, where the form shows every field.
_NOT_BY_ASSISTANT = {"passport", "address"}
_YES = {"yes", "true", "y"}
_NO = {"no", "false", "n"}


class Proposal(BaseModel):
    action: Literal["change_answer", "go_to_question", "check"]
    question_id: str | None = None
    question: str | None = None
    # change_answer: the value to save (already checked) and how it reads, next to the current answer.
    value: Any = None
    display: str | None = None
    current_display: str | None = None
    # check: the completeness report, which is read-only, so it is run straight away.
    report: completeness.Report | None = None


def catalog(questionnaire: flow.Questionnaire, answers: flow.Answers) -> str:
    """The questions the assistant may point at, with the ids its tools take."""
    current = flow.next_question(questionnaire, answers)
    lines = ["Questions (id, type, choices):"]
    for question in flow.visible_questions(questionnaire, answers):
        if question.id not in answers and question is not current:
            continue
        options = f" choices: {', '.join(o.value for o in question.options)}" if question.options else ""
        state = "current question" if question is current else "answered"
        changeable = "" if question.type not in _NOT_BY_ASSISTANT else ", change it in the chat"
        lines.append(f"- {question.id} ({question.type}, {state}{changeable}){options}: {question.prompt}")
    return "\n".join(lines)


def _raw(question: flow.Question, value: str) -> Any:
    if question.type == "yes_no":
        word = value.strip().lower()
        if word in _YES or word in _NO:
            return word in _YES
        raise flow.InvalidAnswer("Answer yes or no.")
    if question.type == "choice":
        word = value.strip().casefold()
        for option in question.options or []:
            if word in {option.value.casefold(), option.label.casefold()}:
                return option.value
        raise flow.InvalidAnswer("That isn't one of the choices for this question.")
    return value


def propose(questionnaire: flow.Questionnaire, answers: flow.Answers, name: str, args: dict, today: date, *,
            latest_passport: dict | None = None, profile: dict | None = None) -> Proposal:
    """Turn one tool call into a checked proposal, or raise InvalidAnswer with a message for the traveler."""
    answers, _ = flow.reconcile(questionnaire, answers, today)
    if name == "run_completeness_check":
        return Proposal(action="check", report=completeness.check(
            questionnaire, answers, today, latest_passport=latest_passport, profile=profile))

    question = questionnaire.question(str(args.get("question_id", "")))
    current = flow.next_question(questionnaire, answers)
    # The same order rule as the answer endpoint: an answered question, or the current one.
    if question is None or not flow.is_visible(question, answers) or (
            question.id not in answers and question is not current):
        raise flow.InvalidAnswer("That question isn't one you can go to yet.")
    where = dict(question_id=question.id, question=question.prompt)
    if name == "go_to_question":
        return Proposal(action="go_to_question", **where)
    if name != "change_answer":
        raise flow.InvalidAnswer("I can't do that here.")
    if question.type in _NOT_BY_ASSISTANT:
        raise flow.InvalidAnswer("That answer has several parts, so change it in the chat, where you can see them all.")
    value = flow.check_answer(question, _raw(question, str(args.get("value", ""))), answers, today)
    current_value = answers.get(question.id)
    return Proposal(action="change_answer", **where, value=value, display=flow.display_value(question, value),
                    current_display=flow.display_value(question, current_value) if question.id in answers else None)
