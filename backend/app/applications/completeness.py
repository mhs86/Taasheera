"""The completeness check before submission (US 13).

Lists what still stands between an application and submission: questions not
answered yet, an eligibility answer that stops the application, and answers that
disagree with the traveler's own saved passport or profile. Like the flow engine
it is pure and deterministic: the same answers always give the same issues, so the
check can be tested, and the assistant can call it as a tool without the model
deciding what counts as "complete".

Answers that broke a rule since they were given (a trip date now in the past) are
already removed by `flow.reconcile`, so they show up here as unanswered.
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from . import flow

Kind = Literal["missing", "ineligible", "inconsistent"]
Severity = Literal["blocking", "warning"]

# Passport fields compared with the profile, and how each is named to the traveler.
_PROFILE_FIELDS = {"surname": "surname", "given_names": "given names", "birth_date": "date of birth",
                   "nationality": "nationality"}


class Issue(BaseModel):
    kind: Kind
    # Blocking issues stop submission; warnings are worth a look but the traveler may be right.
    severity: Severity
    message: str
    # Where it can be fixed (the fix links themselves are US 14).
    question_id: str | None = None
    step_id: str | None = None


class Report(BaseModel):
    ready: bool
    answered: int
    total: int
    issues: list[Issue]


def _same(left: Any, right: Any) -> bool:
    return " ".join(str(left).split()).casefold() == " ".join(str(right).split()).casefold()


def _passport_issues(questionnaire: flow.Questionnaire, answers: flow.Answers,
                     latest_passport: dict | None, profile: dict | None) -> list[Issue]:
    question = next((q for q in flow.visible_questions(questionnaire, answers) if q.type == "passport"), None)
    if question is None or question.id not in answers:
        return []
    given = answers[question.id]
    where = dict(question_id=question.id, step_id=questionnaire.step_of(question.id).id)
    issues = []
    # Answers are copies, so a passport confirmed later doesn't change this application by itself.
    if latest_passport and any(not _same(given.get(key), latest_passport.get(key))
                               for key in ("document_number", "expiry_date")):
        issues.append(Issue(kind="inconsistent", severity="warning", **where, message=(
            "You've confirmed a different passport since you answered. "
            "If you'll travel on the new one, update the passport in this application.")))
    for key, name in _PROFILE_FIELDS.items():
        saved = (profile or {}).get(key)
        if saved and given.get(key) and not _same(given[key], saved):
            issues.append(Issue(kind="inconsistent", severity="warning", **where, message=(
                f"The {name} on your passport ({given[key]}) doesn't match your profile ({saved}). "
                "Embassies expect the passport version; fix whichever one is wrong.")))
    return issues


def check(questionnaire: flow.Questionnaire, answers: flow.Answers, today: date, *,
          latest_passport: dict | None = None, profile: dict | None = None) -> Report:
    """What is missing or inconsistent in an application, and whether it is ready to submit."""
    answers, _ = flow.reconcile(questionnaire, answers, today)
    issues: list[Issue] = []
    stopped = flow.stop_message(questionnaire, answers)
    if stopped:
        stopper = next(q for q in flow.visible_questions(questionnaire, answers)
                       if q.stop_if and answers.get(q.id) in q.stop_if.values)
        issues.append(Issue(kind="ineligible", severity="blocking", message=stopped, question_id=stopper.id,
                            step_id=questionnaire.step_of(stopper.id).id))
    else:
        issues += [Issue(kind="missing", severity="blocking", message=f"Not answered yet: {question.prompt}",
                         question_id=question.id, step_id=questionnaire.step_of(question.id).id)
                   for question in flow.visible_questions(questionnaire, answers) if question.id not in answers]
    issues += _passport_issues(questionnaire, answers, latest_passport, profile)
    progress = flow.progress(questionnaire, answers)
    return Report(ready=not any(issue.severity == "blocking" for issue in issues),
                  answered=progress.answered, total=progress.total, issues=issues)


def describe(report: Report) -> str:
    """Plain text for the assistant's prompt."""
    if not report.issues:
        return "Completeness check: nothing is missing; the answers are ready for review."
    lines = [f"Completeness check: {'ready, with warnings' if report.ready else 'not ready'} "
             f"({report.answered} of {report.total} questions answered)."]
    lines += [f"- [{issue.severity}] {issue.message}" for issue in report.issues]
    return "\n".join(lines)
